"""Frozen owner approval and durable independent project initialization."""

import asyncio
import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.github_archive import GitHubPrivateRepository, ProjectArchiveProvider
from app.domain.provisioning import (
    LocalProjectProvisionProvider,
    LocalProvisionReceipt,
    ProvisionFile,
    ProvisionScope,
    managed_root_fingerprint,
)
from app.errors import DomainError
from app.models_project_archives import ProjectArchiveBinding
from app.models_provisioning import ProjectProvisionEvent, ProjectProvisionJob, ProjectProvisionPlan
from app.providers.registry import archive_remote, provision_local
from app.schemas_provisioning import (
    ProvisionCapabilityOut,
    ProvisionFileOut,
    ProvisionPlanCreate,
    ProvisionPlanOut,
    ProvisionStart,
)
from app.services import archive_jobs
from app.services.projects import get_project

LEASE_SECONDS = 600


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def capability() -> ProvisionCapabilityOut:
    settings = get_settings()
    owner = settings.project_provision_github_owner
    root = settings.project_provision_managed_root
    configured = bool(
        root
        and Path(root).is_absolute()
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner)
        and settings.project_provision_github_owner_id > 0
    )
    enabled = (
        configured
        and settings.project_provision_enabled
        and settings.project_archive_write_enabled
        and settings.project_archive_catalog_enabled
    )
    return ProvisionCapabilityOut(
        enabled=enabled,
        managed_root_label=root if configured else "尚未配置项目根目录",
        github_owner=owner or None,
        github_owner_id=settings.project_provision_github_owner_id or None,
        detail="先预览目录、私有仓库与生成文件，再批准后台初始化。"
        if enabled
        else "主机尚未配置或启用独立项目初始化，既有归档仍可使用。",
    )


def _scope(plan: ProjectProvisionPlan) -> ProvisionScope:
    return ProvisionScope(
        str(plan.project_id),
        plan.managed_root_fingerprint,
        plan.folder_name,
        plan.repository_name,
        plan.github_owner,
        plan.github_owner_id,
        plan.plan_sha256,
    )


def _files(plan: ProjectProvisionPlan) -> tuple[ProvisionFile, ...]:
    return TypeAdapter(tuple[ProvisionFile, ...]).validate_python(plan.files_payload)


def _plan_hash(plan: ProjectProvisionPlan) -> str:
    return _hash(
        {
            "id": str(plan.id),
            "owner": str(plan.user_id),
            "project": str(plan.project_id),
            "root": plan.managed_root_fingerprint,
            "folder": plan.folder_name,
            "repository": plan.repository_name,
            "github_owner": plan.github_owner,
            "github_owner_id": plan.github_owner_id,
            "template_key": plan.template_key,
            "template_sha256": plan.template_sha256,
            "files": plan.files_payload,
        }
    )


def _validate_plan(plan: ProjectProvisionPlan) -> None:
    settings = get_settings()
    if (
        _plan_hash(plan) != plan.plan_sha256
        or managed_root_fingerprint(Path(settings.project_provision_managed_root))
        != plan.managed_root_fingerprint
        or (
            settings.project_provision_github_owner.casefold(),
            settings.project_provision_github_owner_id,
        )
        != (plan.github_owner.casefold(), plan.github_owner_id)
    ):
        raise DomainError(
            "PROVISION_SCOPE_CHANGED", "Approved project root, account or source plan changed", 409
        )


def _validate_local(receipt: LocalProvisionReceipt, plan: ProjectProvisionPlan) -> None:
    files = _files(plan)
    expected_root = Path(get_settings().project_provision_managed_root) / plan.folder_name
    manifest_hash = _hash(
        [{"path": row.path, "sha256": row.sha256, "size_bytes": row.size_bytes} for row in files]
    )
    if (
        receipt.workspace_key != "provision-" + plan.project_id.hex
        or os.path.normcase(os.path.abspath(receipt.root_path))
        != os.path.normcase(os.path.abspath(expected_root))
        or receipt.files != files
        or receipt.manifest_sha256 != manifest_hash
    ):
        raise DomainError(
            "PROVISION_LOCAL_RECEIPT_CONFLICT",
            "Local artifacts differ from the approved directory and files",
            409,
        )


def _validate_repository(
    repository: GitHubPrivateRepository, plan: ProjectProvisionPlan, expected_id: int | None = None
) -> None:
    if (
        repository.private is not True
        or repository.push_allowed is not True
        or repository.owner_id != plan.github_owner_id
        or repository.owner_login.casefold() != plan.github_owner.casefold()
        or repository.name.casefold() != plan.repository_name.casefold()
        or (expected_id is not None and repository.repository_id != expected_id)
    ):
        raise DomainError(
            "PROVISION_REMOTE_IDENTITY_CONFLICT",
            "Private repository identity differs from the approved plan",
            409,
        )


def get_plan(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ProjectProvisionPlan:
    get_project(db, owner, project)
    plan = db.scalar(
        select(ProjectProvisionPlan).where(
            ProjectProvisionPlan.id == identity,
            ProjectProvisionPlan.user_id == owner,
            ProjectProvisionPlan.project_id == project,
        )
    )
    if plan is None:
        raise DomainError("NOT_FOUND", "Initialization plan not found in this project", 404)
    return plan


def plan_out(plan: ProjectProvisionPlan) -> ProvisionPlanOut:
    return ProvisionPlanOut.model_validate(
        {
            **{key: getattr(plan, key) for key in ProvisionPlanOut.model_fields if key != "files"},
            "files": [ProvisionFileOut.model_validate(asdict(file)) for file in _files(plan)],
        }
    )


async def create_plan(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    body: ProvisionPlanCreate,
    *,
    local: LocalProjectProvisionProvider | None = None,
) -> ProjectProvisionPlan:
    project = get_project(db, owner, project_id)
    if not capability().enabled:
        raise DomainError(
            "PROVISION_DISABLED", "Project initialization is not configured and enabled", 503
        )
    if (
        db.scalar(
            select(ProjectArchiveBinding.id).where(
                ProjectArchiveBinding.user_id == owner,
                ProjectArchiveBinding.project_id == project_id,
            )
        )
        is not None
    ):
        raise DomainError(
            "PROVISION_ALREADY_BOUND", "Project already has an independent archive binding", 409
        )
    provider = local if local is not None else provision_local()
    files = await asyncio.to_thread(provider.plan_files, str(project_id), project.name)
    payload = [asdict(file) for file in files]
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise DomainError(
            "PROVISION_PLAN_TOO_LARGE", "Generated initialization plan exceeds its size bound", 409
        )
    settings = get_settings()
    plan = ProjectProvisionPlan(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project_id,
        managed_root_fingerprint=managed_root_fingerprint(
            Path(settings.project_provision_managed_root)
        ),
        folder_name=body.folder_name or project.slug,
        repository_name=body.repository_name or project.slug,
        github_owner=settings.project_provision_github_owner,
        github_owner_id=settings.project_provision_github_owner_id,
        template_key="python-context-v1",
        template_sha256=_hash(payload),
        plan_sha256="",
        files_payload=payload,
    )
    plan.plan_sha256 = _plan_hash(plan)
    # Validate scope and reject unrelated existing directories without writing.
    existing = await asyncio.to_thread(provider.inspect, _scope(plan), files)
    if existing is not None:
        raise DomainError(
            "PROVISION_DIRECTORY_EXISTS",
            "Project directory already exists; preserve it and select a new plan",
            409,
        )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def event(db: Session, job: ProjectProvisionJob, kind: str, message: str) -> None:
    db.add(
        ProjectProvisionEvent(
            user_id=job.user_id, job_id=job.id, event_kind=kind, message=message[:2000]
        )
    )


def get_job(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ProjectProvisionJob:
    get_project(db, owner, project)
    job = db.scalar(
        select(ProjectProvisionJob).where(
            ProjectProvisionJob.id == identity,
            ProjectProvisionJob.user_id == owner,
            ProjectProvisionJob.project_id == project,
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Initialization job not found in this project", 404)
    return job


def start(
    db: Session, owner: uuid.UUID, project: uuid.UUID, body: ProvisionStart
) -> ProjectProvisionJob:
    plan = get_plan(db, owner, project, body.plan_id)
    if not capability().enabled:
        raise DomainError("PROVISION_DISABLED", "Project initialization is disabled", 503)
    _validate_plan(plan)
    if plan.plan_sha256 != body.expected_plan_sha256:
        raise DomainError(
            "PROVISION_PLAN_CHANGED", "Preview hash differs from the approved plan", 409
        )
    existing = db.scalar(
        select(ProjectProvisionJob).where(
            ProjectProvisionJob.plan_id == plan.id, ProjectProvisionJob.user_id == owner
        )
    )
    if existing is not None:
        return existing
    if (
        db.scalar(
            select(ProjectArchiveBinding.id).where(
                ProjectArchiveBinding.project_id == project, ProjectArchiveBinding.user_id == owner
            )
        )
        is not None
    ):
        raise DomainError("PROVISION_ALREADY_BOUND", "Project already has an archive binding", 409)
    job = ProjectProvisionJob(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project,
        plan_id=plan.id,
        active_project_id=project,
        status="QUEUED",
    )
    try:
        db.add(job)
        db.flush()
        event(
            db,
            job,
            "APPROVED",
            "Owner approved the frozen directory, private repository and generated source files",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "PROVISION_JOB_ACTIVE",
            "Project already has an active or unconfirmed initialization",
            409,
        ) from None
    db.refresh(job)
    return job


def list_jobs(db: Session, owner: uuid.UUID, project: uuid.UUID) -> list[ProjectProvisionJob]:
    get_project(db, owner, project)
    return list(
        db.scalars(
            select(ProjectProvisionJob)
            .where(ProjectProvisionJob.user_id == owner, ProjectProvisionJob.project_id == project)
            .order_by(ProjectProvisionJob.created_at.desc())
            .limit(100)
        )
    )


def events(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> list[ProjectProvisionEvent]:
    job = get_job(db, owner, project, identity)
    return list(
        db.scalars(
            select(ProjectProvisionEvent)
            .where(ProjectProvisionEvent.user_id == owner, ProjectProvisionEvent.job_id == job.id)
            .order_by(ProjectProvisionEvent.created_at, ProjectProvisionEvent.id)
        )
    )


def cancel(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ProjectProvisionJob:
    job = get_job(db, owner, project, identity)
    changed = db.execute(
        update(ProjectProvisionJob)
        .where(
            ProjectProvisionJob.id == job.id,
            ProjectProvisionJob.user_id == owner,
            ProjectProvisionJob.status == "QUEUED",
        )
        .values(status="CANCELLED", active_project_id=None, finished_at=_now())
        .returning(ProjectProvisionJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if changed is None:
        db.rollback()
        raise DomainError(
            "PROVISION_CANCEL_NOT_QUEUED", "Only an unstarted initialization can be cancelled", 409
        )
    event(db, job, "CANCELLED", "Owner cancelled initialization before execution")
    db.commit()
    db.refresh(job)
    return job


def _reload(db: Session, identity: uuid.UUID) -> ProjectProvisionJob:
    job = db.get(ProjectProvisionJob, identity)
    if job is None:
        raise DomainError("NOT_FOUND", "Initialization job disappeared", 404)
    return job


def checkpoint(
    db: Session,
    job: ProjectProvisionJob,
    lease: uuid.UUID,
    expected: str,
    status: str,
    **values: object,
) -> ProjectProvisionJob:
    changed = db.execute(
        update(ProjectProvisionJob)
        .where(
            ProjectProvisionJob.id == job.id,
            ProjectProvisionJob.user_id == job.user_id,
            ProjectProvisionJob.status == expected,
            ProjectProvisionJob.lease_token == lease,
            ProjectProvisionJob.lease_expires_at > _now(),
        )
        .values(status=status, updated_at=_now(), **values)
        .returning(ProjectProvisionJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if changed is None:
        db.rollback()
        raise DomainError(
            "PROVISION_LEASE_LOST", "Initialization fence changed; retain existing artifacts", 409
        )
    event(db, job, status, "Initialization stage: " + status)
    db.commit()
    db.expire_all()
    return _reload(db, job.id)


def quarantine(db: Session, owner: uuid.UUID) -> None:
    rows = list(
        db.scalars(
            select(ProjectProvisionJob).where(
                ProjectProvisionJob.user_id == owner,
                ProjectProvisionJob.status.in_(
                    ["PREPARING", "LOCAL_READY", "CREATING_REMOTE", "REMOTE_CREATED", "BINDING"]
                ),
                ProjectProvisionJob.lease_expires_at <= _now(),
            )
        )
    )
    for job in rows:
        phase = job.status
        changed = db.execute(
            update(ProjectProvisionJob)
            .where(
                ProjectProvisionJob.id == job.id,
                ProjectProvisionJob.user_id == owner,
                ProjectProvisionJob.lease_expires_at <= _now(),
                ProjectProvisionJob.status == phase,
            )
            .values(
                status="NEEDS_ATTENTION",
                lease_token=None,
                lease_expires_at=None,
                error_code="PROVISION_EXPIRED_" + phase,
                error_message="Host initialization expired; inspect existing artifacts before continuation",
            )
            .returning(ProjectProvisionJob.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if changed is not None:
            event(db, job, "NEEDS_ATTENTION", "Host execution expired in " + phase)
    db.commit()


async def process_next(
    db: Session,
    owner: uuid.UUID,
    *,
    local: LocalProjectProvisionProvider | None = None,
    remote: ProjectArchiveProvider | None = None,
) -> ProjectProvisionJob | None:
    quarantine(db, owner)
    if not capability().enabled:
        return None
    job = db.scalar(
        select(ProjectProvisionJob)
        .where(
            ProjectProvisionJob.user_id == owner,
            ProjectProvisionJob.status.in_(["QUEUED", "LOCAL_READY", "REMOTE_CREATED"]),
        )
        .order_by(ProjectProvisionJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    previous = job.status
    lease = uuid.uuid4()
    initial = (
        "PREPARING"
        if previous == "QUEUED"
        else "LOCAL_READY"
        if previous == "LOCAL_READY"
        else "BINDING"
    )
    changed = db.execute(
        update(ProjectProvisionJob)
        .where(
            ProjectProvisionJob.id == job.id,
            ProjectProvisionJob.user_id == owner,
            ProjectProvisionJob.status == previous,
        )
        .values(
            status=initial,
            lease_token=lease,
            lease_expires_at=_now() + timedelta(seconds=LEASE_SECONDS),
            started_at=_now(),
        )
        .returning(ProjectProvisionJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if changed is None:
        db.rollback()
        return None
    event(db, job, initial, "Host accepted the approved initialization scope")
    db.commit()
    db.expire_all()
    job = _reload(db, job.id)
    try:
        plan = get_plan(db, owner, job.project_id, job.plan_id)
        _validate_plan(plan)
        provider = local if local is not None else provision_local()
        github = (
            remote
            if remote is not None
            else await asyncio.to_thread(archive_remote, plan.github_owner)
        )
        scope, files = _scope(plan), _files(plan)
        with provider.exclusive(scope):
            account = await github.inspect_authenticated_account(
                plan.github_owner, plan.github_owner_id
            )
            if (account.login.casefold(), account.user_id) != (
                plan.github_owner.casefold(),
                plan.github_owner_id,
            ):
                raise DomainError(
                    "PROVISION_ACCOUNT_CHANGED",
                    "Execution account differs from the approved owner",
                    409,
                )
            if initial == "PREPARING":
                local_receipt = await asyncio.to_thread(provider.create, scope, files)
                _validate_local(local_receipt, plan)
                job = checkpoint(
                    db,
                    job,
                    lease,
                    "PREPARING",
                    "LOCAL_READY",
                    lease_expires_at=_now() + timedelta(seconds=LEASE_SECONDS),
                )
            if job.status == "LOCAL_READY":
                inspected_receipt = await asyncio.to_thread(provider.inspect, scope, files)
                if inspected_receipt is None:
                    raise DomainError(
                        "PROVISION_LOCAL_INCOMPLETE",
                        "Approved local files are not ready for repository creation",
                        409,
                    )
                _validate_local(inspected_receipt, plan)
                job = checkpoint(db, job, lease, "LOCAL_READY", "CREATING_REMOTE")
                created = await github.create_private_repository(
                    plan.github_owner,
                    plan.repository_name,
                    expected_owner_id=plan.github_owner_id,
                    description="Private research project code, usage and AI handoff archive",
                )
                _validate_repository(created.repository, plan)
                if created.reconciled_after_unknown:
                    return checkpoint(
                        db,
                        job,
                        lease,
                        "CREATING_REMOTE",
                        "NEEDS_ATTENTION",
                        observed_repository_id=created.repository.repository_id,
                        lease_token=None,
                        lease_expires_at=None,
                        error_code="PROVISION_CREATE_UNKNOWN",
                        error_message="Observed private repository needs explicit owner adoption; creation was not proven",
                    )
                job = checkpoint(
                    db,
                    job,
                    lease,
                    "CREATING_REMOTE",
                    "REMOTE_CREATED",
                    repository_id=created.repository.repository_id,
                )
                job = checkpoint(db, job, lease, "REMOTE_CREATED", "BINDING")
            repository = await github.get_private_owned_repository(
                plan.github_owner,
                plan.repository_name,
                expected_owner_id=plan.github_owner_id,
                expected_repository_id=job.repository_id,
            )
            _validate_repository(repository, plan, job.repository_id)
            _validate_local(
                await asyncio.to_thread(provider.bind_repository, scope, repository), plan
            )
            binding = db.scalar(
                select(ProjectArchiveBinding).where(
                    ProjectArchiveBinding.user_id == owner,
                    ProjectArchiveBinding.project_id == job.project_id,
                )
            )
            if binding is None:
                binding = ProjectArchiveBinding(
                    user_id=owner,
                    project_id=job.project_id,
                    workspace_key="provision-" + job.project_id.hex,
                    local_project_id=str(job.project_id),
                    github_owner=repository.owner_login,
                    github_owner_id=repository.owner_id,
                    github_repository=repository.name,
                    github_repository_id=repository.repository_id,
                    verified_at=_now(),
                    managed_folder_name=plan.folder_name,
                    managed_root_fingerprint=plan.managed_root_fingerprint,
                )
                db.add(binding)
                db.flush()
            elif (
                binding.github_repository_id,
                binding.managed_folder_name,
                binding.managed_root_fingerprint,
                binding.local_project_id,
                binding.workspace_key,
                binding.github_owner.casefold(),
                binding.github_owner_id,
                binding.github_repository.casefold(),
            ) != (
                repository.repository_id,
                plan.folder_name,
                plan.managed_root_fingerprint,
                str(job.project_id),
                "provision-" + job.project_id.hex,
                repository.owner_login.casefold(),
                repository.owner_id,
                repository.name.casefold(),
            ):
                raise DomainError(
                    "PROVISION_BINDING_CONFLICT",
                    "Existing project binding differs from the approved initialization",
                    409,
                )
            from app.models_archive_jobs import ProjectArchiveJob

            initial_tag = "v0.0.0-initial." + job.id.hex[:12]
            if (
                db.scalar(
                    select(ProjectArchiveJob.id).where(
                        ProjectArchiveJob.user_id == owner,
                        ProjectArchiveJob.binding_id == binding.id,
                        ProjectArchiveJob.tag == initial_tag,
                    )
                )
                is None
            ):
                archive_jobs.enqueue(db, binding, initial_tag, commit=False)
            job = checkpoint(
                db,
                job,
                lease,
                "BINDING",
                "COMPLETED",
                active_project_id=None,
                binding_id=binding.id,
                lease_token=None,
                lease_expires_at=None,
                finished_at=_now(),
                error_code=None,
                error_message=None,
            )
            return job
    except Exception as failure:
        db.rollback()
        job = _reload(db, job.id)
        if job.lease_token != lease:
            return job
        uncertain = (
            job.status != "PREPARING"
            or not isinstance(failure, DomainError)
            or failure.code
            not in {
                "PROVISION_SCOPE_CHANGED",
                "PROVISION_DISABLED",
                "PROVISION_CONFIGURATION_INVALID",
            }
        )
        status = "NEEDS_ATTENTION" if uncertain else "FAILED"
        error_code = (
            failure.code[:80] if isinstance(failure, DomainError) else "PROVISION_HOST_FAILURE"
        )
        message = (
            failure.message[:2000]
            if isinstance(failure, DomainError)
            else "Initialization result was not confirmed; preserve local artifacts and inspect the original repository"
        )
        changed = db.execute(
            update(ProjectProvisionJob)
            .where(
                ProjectProvisionJob.id == job.id,
                ProjectProvisionJob.user_id == owner,
                ProjectProvisionJob.lease_token == lease,
            )
            .values(
                status=status,
                active_project_id=job.project_id if uncertain else None,
                lease_token=None,
                lease_expires_at=None,
                error_code=error_code,
                error_message=message,
            )
            .returning(ProjectProvisionJob.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if changed is not None:
            event(db, job, status, message)
        db.commit()
        db.expire_all()
        return _reload(db, job.id)


async def reconcile(
    db: Session,
    job: ProjectProvisionJob,
    *,
    local: LocalProjectProvisionProvider | None = None,
    remote: ProjectArchiveProvider | None = None,
) -> ProjectProvisionJob:
    if job.status != "NEEDS_ATTENTION":
        raise DomainError(
            "PROVISION_NOT_ATTENTION", "Only an unconfirmed initialization can be inspected", 409
        )
    lease = uuid.uuid4()
    claimed = db.execute(
        update(ProjectProvisionJob)
        .where(
            ProjectProvisionJob.id == job.id,
            ProjectProvisionJob.user_id == job.user_id,
            ProjectProvisionJob.status == "NEEDS_ATTENTION",
            (ProjectProvisionJob.lease_expires_at.is_(None))
            | (ProjectProvisionJob.lease_expires_at <= _now()),
        )
        .values(lease_token=lease, lease_expires_at=_now() + timedelta(seconds=LEASE_SECONDS))
        .returning(ProjectProvisionJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if claimed is None:
        db.rollback()
        raise DomainError("PROVISION_BUSY", "Another initialization verification is active", 409)
    db.commit()
    db.expire_all()
    job = _reload(db, job.id)
    try:
        plan = get_plan(db, job.user_id, job.project_id, job.plan_id)
        _validate_plan(plan)
        provider = local if local is not None else provision_local()
        github = (
            remote
            if remote is not None
            else await asyncio.to_thread(archive_remote, plan.github_owner)
        )
        with provider.exclusive(_scope(plan)):
            started_remote = (
                db.scalar(
                    select(ProjectProvisionEvent.id)
                    .where(
                        ProjectProvisionEvent.user_id == job.user_id,
                        ProjectProvisionEvent.job_id == job.id,
                        ProjectProvisionEvent.event_kind == "CREATING_REMOTE",
                    )
                    .limit(1)
                )
                is not None
            )
            receipt = await asyncio.to_thread(provider.inspect, _scope(plan), _files(plan))
            if not started_remote and job.repository_id is None:
                if receipt is None:
                    receipt = await asyncio.to_thread(provider.create, _scope(plan), _files(plan))
                _validate_local(receipt, plan)
                return checkpoint(
                    db,
                    job,
                    lease,
                    "NEEDS_ATTENTION",
                    "LOCAL_READY",
                    lease_token=None,
                    lease_expires_at=None,
                    error_code=None,
                    error_message=None,
                )
            if receipt is None:
                raise DomainError(
                    "PROVISION_LOCAL_INCOMPLETE",
                    "Local approved files are incomplete; repository creation will not be repeated",
                    409,
                )
            _validate_local(receipt, plan)
            repository = await github.get_private_owned_repository(
                plan.github_owner,
                plan.repository_name,
                expected_owner_id=plan.github_owner_id,
                expected_repository_id=job.repository_id,
            )
            _validate_repository(repository, plan, job.repository_id)
            if job.repository_id is None:
                return checkpoint(
                    db,
                    job,
                    lease,
                    "NEEDS_ATTENTION",
                    "NEEDS_ATTENTION",
                    observed_repository_id=repository.repository_id,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code="PROVISION_OBSERVATION_REQUIRES_OWNER",
                    error_message="Review the original account, repository and files before adopting the observed private repository ID",
                )
            return checkpoint(
                db,
                job,
                lease,
                "NEEDS_ATTENTION",
                "REMOTE_CREATED",
                lease_token=None,
                lease_expires_at=None,
                error_code=None,
                error_message=None,
            )
    except Exception as failure:
        db.rollback()
        job = _reload(db, job.id)
        code = failure.code[:80] if isinstance(failure, DomainError) else "PROVISION_VERIFY_FAILURE"
        message = (
            failure.message[:2000]
            if isinstance(failure, DomainError)
            else "Existing initialization artifacts were not confirmed; no repository creation repeated"
        )
        cleared = db.execute(
            update(ProjectProvisionJob)
            .where(
                ProjectProvisionJob.id == job.id,
                ProjectProvisionJob.user_id == job.user_id,
                ProjectProvisionJob.status == "NEEDS_ATTENTION",
                ProjectProvisionJob.lease_token == lease,
            )
            .values(lease_token=None, lease_expires_at=None, error_code=code, error_message=message)
            .returning(ProjectProvisionJob.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if cleared is not None:
            event(db, job, "VERIFY_UNCONFIRMED", message)
            db.commit()
        else:
            db.rollback()
        db.expire_all()
        return _reload(db, job.id)


async def confirm_observed(
    db: Session,
    job: ProjectProvisionJob,
    expected_id: int,
    *,
    remote: ProjectArchiveProvider | None = None,
) -> ProjectProvisionJob:
    if job.status != "NEEDS_ATTENTION" or job.observed_repository_id != expected_id:
        raise DomainError(
            "PROVISION_OBSERVATION_CHANGED",
            "Observed private repository must be reviewed before adoption",
            409,
        )
    plan = get_plan(db, job.user_id, job.project_id, job.plan_id)
    _validate_plan(plan)
    github = (
        remote if remote is not None else await asyncio.to_thread(archive_remote, plan.github_owner)
    )
    repository = await github.get_private_owned_repository(
        plan.github_owner,
        plan.repository_name,
        expected_owner_id=plan.github_owner_id,
        expected_repository_id=expected_id,
    )
    _validate_repository(repository, plan, expected_id)
    changed = db.execute(
        update(ProjectProvisionJob)
        .where(
            ProjectProvisionJob.id == job.id,
            ProjectProvisionJob.user_id == job.user_id,
            ProjectProvisionJob.status == "NEEDS_ATTENTION",
            ProjectProvisionJob.observed_repository_id == expected_id,
            ProjectProvisionJob.lease_token.is_(None),
        )
        .values(
            status="REMOTE_CREATED", repository_id=expected_id, error_code=None, error_message=None
        )
        .returning(ProjectProvisionJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if changed is None:
        db.rollback()
        raise DomainError(
            "PROVISION_BUSY", "Another initialization verification changed this candidate", 409
        )
    event(
        db,
        job,
        "OWNER_ADOPTED_REPOSITORY",
        "Owner explicitly adopted the observed private repository identity",
    )
    db.commit()
    db.refresh(job)
    return job
