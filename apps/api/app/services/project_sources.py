"""Approved immutable source cache placement through a no-execution local provider."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.github_archive import GitHubPrivateRepository
from app.domain.project_sources import (
    ProjectSourceFile as SourceFile,
)
from app.domain.project_sources import (
    ProjectSourceScope,
    ProjectSourceWorkspaceProvider,
)
from app.domain.provisioning import managed_root_fingerprint
from app.errors import DomainError
from app.models import Attachment, ProjectArchiveBinding, ResearchEvent
from app.models_project_sources import (
    ProjectPathBinding,
    ProjectSourceFile,
    ProjectSourceJob,
    ProjectSourcePlan,
    ProjectSourcePlanFile,
)
from app.models_repository_assets import (
    RepositoryAssetFile,
    RepositoryAssetPlan,
    RepositoryAssetPlanFile,
    RepositoryAssetSnapshot,
)
from app.providers.registry import project_source_workspace_provider
from app.schemas_project_sources import (
    ProjectPathBindingOut,
    ProjectSourceCapabilityOut,
    ProjectSourceCheckOut,
    ProjectSourceEventOut,
    ProjectSourceFileOut,
    ProjectSourceJobOut,
    ProjectSourcePlanApprove,
    ProjectSourcePlanCreate,
    ProjectSourcePlanOut,
    ProjectSourceVerifyOut,
)
from app.services import archive_jobs, repository_assets
from app.services.common import cursor_filter, encode_cursor
from app.services.projects import get_project
from app.services.research_briefs import digest


def now() -> datetime:
    return datetime.now(UTC)


def capability() -> ProjectSourceCapabilityOut:
    settings = get_settings()
    root = settings.project_provision_managed_root
    return ProjectSourceCapabilityOut(
        enabled=settings.project_source_workspaces_enabled
        and bool(root and Path(root).is_absolute()),
        managed_root_label=root or "未配置科研项目根目录",
        detail="Copy verified cached source bytes only into an independently bound project child directory. No network, code execution, training or Git push is authorized.",
    )


def _enabled() -> None:
    if not capability().enabled:
        raise DomainError(
            "PROJECT_SOURCES_DISABLED",
            "Project source cache placement is disabled or not configured",
            503,
        )


def _archive(db: Session, owner: uuid.UUID, project: uuid.UUID) -> ProjectArchiveBinding:
    get_project(db, owner, project)
    row = db.scalar(
        select(ProjectArchiveBinding)
        .where(ProjectArchiveBinding.user_id == owner, ProjectArchiveBinding.project_id == project)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError(
            "PROJECT_ARCHIVE_BINDING_REQUIRED",
            "Bind an independent project directory before planning source placement",
            409,
        )
    return row


def archive_identity(row: ProjectArchiveBinding) -> str:
    return digest(
        {
            key: getattr(row, key)
            for key in (
                "id",
                "user_id",
                "project_id",
                "workspace_key",
                "local_project_id",
                "github_owner",
                "github_owner_id",
                "github_repository",
                "github_repository_id",
                "managed_folder_name",
                "managed_root_fingerprint",
            )
        }
    )


def get_plan(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> ProjectSourcePlan:
    get_project(db, owner, project)
    query = select(ProjectSourcePlan).where(
        ProjectSourcePlan.id == identity,
        ProjectSourcePlan.project_id == project,
        ProjectSourcePlan.user_id == owner,
    )
    row = db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned project source plan not found", 404)
    return row


def get_binding(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> ProjectPathBinding:
    get_project(db, owner, project)
    query = select(ProjectPathBinding).where(
        ProjectPathBinding.id == identity,
        ProjectPathBinding.project_id == project,
        ProjectPathBinding.user_id == owner,
    )
    row = db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned source path binding not found", 404)
    return row


def get_job(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> ProjectSourceJob:
    get_project(db, owner, project)
    query = select(ProjectSourceJob).where(
        ProjectSourceJob.id == identity,
        ProjectSourceJob.project_id == project,
        ProjectSourceJob.user_id == owner,
    )
    row = db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned source copy job not found", 404)
    return row


def plan_files(db: Session, plan: ProjectSourcePlan) -> list[ProjectSourcePlanFile]:
    return list(
        db.scalars(
            select(ProjectSourcePlanFile)
            .where(
                ProjectSourcePlanFile.plan_id == plan.id,
                ProjectSourcePlanFile.project_id == plan.project_id,
                ProjectSourcePlanFile.user_id == plan.user_id,
            )
            .order_by(ProjectSourcePlanFile.path)
            .execution_options(populate_existing=True)
        )
    )


def policy_files(db: Session, plan: ProjectSourcePlan) -> tuple[SourceFile, ...]:
    return tuple(SourceFile(row.path, row.sha256, row.size_bytes) for row in plan_files(db, plan))


def _asset(
    db: Session, owner: uuid.UUID, identity: uuid.UUID
) -> tuple[
    RepositoryAssetSnapshot,
    RepositoryAssetPlan,
    list[RepositoryAssetFile],
    dict[str, RepositoryAssetPlanFile],
]:
    snapshot = db.scalar(
        select(RepositoryAssetSnapshot)
        .where(RepositoryAssetSnapshot.id == identity, RepositoryAssetSnapshot.user_id == owner)
        .execution_options(populate_existing=True)
    )
    if snapshot is None:
        raise DomainError("NOT_FOUND", "Owned verified asset snapshot not found", 404)
    job = repository_assets.get_job(db, owner, snapshot.job_id)
    asset_plan = repository_assets.get_plan(db, owner, snapshot.plan_id)
    repository_assets._validate_plan(db, asset_plan)
    manifest = repository_assets.snapshot_manifest(db, job)
    if (
        job.status != "COMPLETED"
        or asset_plan.state != "APPROVED"
        or asset_plan.approved_hash != asset_plan.plan_sha256
        or asset_plan.approved_by != owner
        or asset_plan.approved_at is None
        or snapshot.status not in {"MATERIALIZED", "PARTIAL"}
        or digest(manifest) != snapshot.manifest_sha256
    ):
        raise DomainError(
            "PROJECT_SOURCE_SNAPSHOT_CHANGED",
            "A completed measured asset snapshot and its exact members are required",
            409,
        )
    rows = list(
        db.scalars(
            select(RepositoryAssetFile)
            .where(
                RepositoryAssetFile.snapshot_id == snapshot.id,
                RepositoryAssetFile.job_id == job.id,
                RepositoryAssetFile.plan_id == asset_plan.id,
                RepositoryAssetFile.user_id == owner,
                RepositoryAssetFile.status == "STORED",
            )
            .execution_options(populate_existing=True)
        )
    )
    if (
        len(rows) != snapshot.stored_files
        or sum(row.actual_size_bytes or 0 for row in rows) != snapshot.stored_bytes
        or not rows
    ):
        raise DomainError(
            "PROJECT_SOURCE_SNAPSHOT_CHANGED",
            "Snapshot member counts differ from measured source receipts",
            409,
        )
    planned = {row.file_key_sha256: row for row in repository_assets.plan_files(db, asset_plan)}
    return snapshot, asset_plan, rows, planned


def binding_hash(binding: ProjectPathBinding, plan: ProjectSourcePlan) -> str:
    return digest(
        {
            **{
                key: getattr(binding, key)
                for key in (
                    "id",
                    "user_id",
                    "project_id",
                    "archive_binding_id",
                    "root_fingerprint",
                    "source_root_fingerprint",
                    "relative_path",
                    "purpose",
                    "no_execution",
                )
            },
            "resource_snapshot_id": str(plan.asset_snapshot_id),
            "resource_manifest_sha256": plan.asset_manifest_sha256,
            "plan_id": str(plan.id),
            "archive_identity_sha256": plan.archive_identity_sha256,
        }
    )


def plan_hash(
    plan: ProjectSourcePlan, binding: ProjectPathBinding, files: list[ProjectSourcePlanFile]
) -> str:
    values = {
        key: getattr(plan, key)
        for key in (
            "id",
            "user_id",
            "project_id",
            "path_binding_id",
            "asset_snapshot_id",
            "asset_manifest_sha256",
            "archive_identity_sha256",
            "source_snapshot_id",
            "provider_key",
            "repo_kind",
            "repo_id",
            "provider_id",
            "commit_sha",
            "source_status",
            "gaps_text",
            "file_count",
            "total_bytes",
        )
    }
    return digest(
        {
            **values,
            "binding_scope_sha256": binding.scope_sha256,
            "files": [
                {
                    "key": row.file_key_sha256,
                    "asset_file_id": str(row.asset_file_id),
                    "attachment_id": str(row.attachment_id),
                    "path": row.path,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                }
                for row in sorted(files, key=lambda row: row.path)
            ],
        }
    )


def policy_scope(db: Session, plan: ProjectSourcePlan) -> ProjectSourceScope:
    binding = get_binding(db, plan.user_id, plan.project_id, plan.path_binding_id)
    archive = _archive(db, plan.user_id, plan.project_id)
    return ProjectSourceScope(
        owner_id=plan.user_id,
        project_id=plan.project_id,
        plan_id=plan.id,
        asset_snapshot_id=plan.asset_snapshot_id,
        asset_manifest_sha256=plan.asset_manifest_sha256,
        plan_sha256=plan.plan_sha256,
        archive_binding_id=archive.id,
        workspace_key=archive.workspace_key,
        root_fingerprint=binding.root_fingerprint,
        source_root_fingerprint=binding.source_root_fingerprint,
        relative_path=binding.relative_path,
        local_project_id=archive.local_project_id,
        repository=GitHubPrivateRepository(
            archive.github_repository_id,
            archive.github_owner,
            archive.github_owner_id,
            archive.github_repository,
            "main",
            False,
        ),
        managed_folder_name=archive.managed_folder_name,
        managed_root_fingerprint=archive.managed_root_fingerprint,
    )


def _validate(db: Session, plan: ProjectSourcePlan) -> ProjectPathBinding:
    binding = get_binding(db, plan.user_id, plan.project_id, plan.path_binding_id)
    archive = _archive(db, plan.user_id, plan.project_id)
    snapshot, asset_plan, rows, planned = _asset(db, plan.user_id, plan.asset_snapshot_id)
    files = plan_files(db, plan)
    if (
        binding.archive_binding_id != archive.id
        or plan.archive_identity_sha256 != archive_identity(archive)
        or binding.root_fingerprint != archive_jobs.binding_fingerprint(archive)
        or binding.source_root_fingerprint
        != managed_root_fingerprint(Path(get_settings().project_provision_managed_root))
        or binding.relative_path != ".researchos/cache/sources/" + str(plan.id)
        or binding.purpose != "REPOSITORY_SOURCE"
        or not binding.no_execution
    ):
        raise DomainError(
            "PROJECT_SOURCE_PATH_CHANGED",
            "The approved independent project root or cache-only destination changed",
            409,
        )
    if (
        binding_hash(binding, plan) != binding.scope_sha256
        or plan_hash(plan, binding, files) != plan.plan_sha256
        or (
            snapshot.manifest_sha256,
            snapshot.status,
            asset_plan.commit_sha,
            asset_plan.source_snapshot_id,
            asset_plan.provider_key,
            asset_plan.repo_kind,
            asset_plan.repo_id,
            asset_plan.provider_id,
        )
        != (
            plan.asset_manifest_sha256,
            plan.source_status,
            plan.commit_sha,
            plan.source_snapshot_id,
            plan.provider_key,
            plan.repo_kind,
            plan.repo_id,
            plan.provider_id,
        )
    ):
        raise DomainError(
            "PROJECT_SOURCE_PLAN_CHANGED", "Frozen cache input or placement hash changed", 409
        )
    if (
        len(files) != plan.file_count
        or sum(row.size_bytes for row in files) != plan.total_bytes
        or {row.asset_file_id for row in files} != {row.id for row in rows}
    ):
        raise DomainError(
            "PROJECT_SOURCE_MEMBERS_CHANGED",
            "Only original stored snapshot members may be copied",
            409,
        )
    source_by_id = {row.id: row for row in rows}
    for row in files:
        source = source_by_id[row.asset_file_id]
        original = planned[source.file_key_sha256]
        attachment = db.scalar(
            select(Attachment)
            .where(
                Attachment.id == row.attachment_id,
                Attachment.user_id == plan.user_id,
                Attachment.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if (
            attachment is None
            or (row.path, row.sha256, row.size_bytes, row.attachment_id)
            != (original.path, source.actual_sha256, source.actual_size_bytes, source.attachment_id)
            or (attachment.sha256, attachment.size_bytes) != (row.sha256, row.size_bytes)
            or row.file_key_sha256 != digest({"path": row.path})
        ):
            raise DomainError(
                "PROJECT_SOURCE_ATTACHMENT_CHANGED",
                "Source attachment identity or measured bytes changed",
                409,
            )
    return binding


def validate_plan(db: Session, job: ProjectSourceJob) -> ProjectSourcePlan:
    _enabled()
    plan = get_plan(db, job.user_id, job.project_id, job.plan_id)
    binding = _validate(db, plan)
    if (
        binding.id != job.path_binding_id
        or binding.state != "ACTIVE"
        or binding.approved_hash != binding.scope_sha256
        or plan.state != "APPROVED"
        or plan.approved_hash != plan.plan_sha256
        or binding.approved_by != job.user_id
        or plan.approved_by != job.user_id
    ):
        raise DomainError(
            "PROJECT_SOURCE_APPROVAL_INACTIVE", "The exact owner copy approval is not active", 409
        )
    settings = get_settings()
    if (
        plan.file_count > settings.repository_asset_max_files
        or plan.total_bytes > settings.repository_asset_max_bytes
    ):
        raise DomainError(
            "PROJECT_SOURCE_LIMIT_CHANGED",
            "Current host copy limits do not permit this source set",
            409,
        )
    return plan


def copy_fence_sha256(plan: ProjectSourcePlan, binding: ProjectPathBinding) -> str:
    """Freeze scalar scope separately from enumerating thousands of source members."""
    return digest(
        {
            "plan": {column.name: getattr(plan, column.name) for column in plan.__table__.columns},
            "binding": {
                column.name: getattr(binding, column.name) for column in binding.__table__.columns
            },
        }
    )


def validate_copy_fence(
    db: Session,
    job: ProjectSourceJob,
    expected_scope: ProjectSourceScope,
    expected_fence_sha256: str,
) -> ProjectSourcePlan:
    _enabled()
    plan = get_plan(db, job.user_id, job.project_id, job.plan_id)
    binding = get_binding(db, job.user_id, job.project_id, job.path_binding_id)
    archive = _archive(db, job.user_id, job.project_id)
    snapshot = db.scalar(
        select(RepositoryAssetSnapshot)
        .where(
            RepositoryAssetSnapshot.id == plan.asset_snapshot_id,
            RepositoryAssetSnapshot.user_id == job.user_id,
        )
        .execution_options(populate_existing=True)
    )
    asset_plan = repository_assets.get_plan(db, job.user_id, snapshot.plan_id) if snapshot else None
    source, source_reference, _ = repository_assets._source(
        db, job.user_id, plan.source_snapshot_id
    )
    asset_job = repository_assets.get_job(db, job.user_id, snapshot.job_id) if snapshot else None
    if (
        copy_fence_sha256(plan, binding) != expected_fence_sha256
        or policy_scope(db, plan) != expected_scope
        or binding.state != "ACTIVE"
        or binding.approved_hash != binding.scope_sha256
        or plan.state != "APPROVED"
        or plan.approved_hash != plan.plan_sha256
        or archive_identity(archive) != plan.archive_identity_sha256
        or archive_jobs.binding_fingerprint(archive) != binding.root_fingerprint
        or managed_root_fingerprint(Path(get_settings().project_provision_managed_root))
        != binding.source_root_fingerprint
        or snapshot is None
        or asset_plan is None
        or (
            snapshot.manifest_sha256,
            snapshot.status,
            snapshot.stored_files,
            snapshot.stored_bytes,
            snapshot.source_snapshot_id,
        )
        != (
            plan.asset_manifest_sha256,
            plan.source_status,
            plan.file_count,
            plan.total_bytes,
            plan.source_snapshot_id,
        )
        or (
            asset_plan.provider_key,
            asset_plan.repo_kind,
            asset_plan.repo_id,
            asset_plan.provider_id,
            asset_plan.commit_sha,
            asset_plan.source_snapshot_id,
        )
        != (
            plan.provider_key,
            plan.repo_kind,
            plan.repo_id,
            plan.provider_id,
            plan.commit_sha,
            plan.source_snapshot_id,
        )
        or asset_plan.state != "APPROVED"
        or asset_plan.approved_hash != asset_plan.plan_sha256
        or asset_plan.approved_by != job.user_id
        or asset_job is None
        or asset_job.status != "COMPLETED"
        or source.snapshot_sha256 != asset_plan.source_snapshot_sha256
        or source_reference != repository_assets.plan_reference(asset_plan)
        or plan.file_count > get_settings().repository_asset_max_files
        or plan.total_bytes > get_settings().repository_asset_max_bytes
    ):
        raise DomainError(
            "PROJECT_SOURCE_COPY_FENCE_CHANGED",
            "Frozen copy scope or original source approval changed",
            409,
        )
    return plan


def current_file(
    db: Session,
    plan: ProjectSourcePlan,
    file_key_sha256: str,
    expected: SourceFile,
    expected_attachment_id: uuid.UUID,
    expected_asset_file_id: uuid.UUID,
) -> ProjectSourcePlanFile:
    row = db.scalar(
        select(ProjectSourcePlanFile)
        .where(
            ProjectSourcePlanFile.plan_id == plan.id,
            ProjectSourcePlanFile.project_id == plan.project_id,
            ProjectSourcePlanFile.user_id == plan.user_id,
            ProjectSourcePlanFile.file_key_sha256 == file_key_sha256,
        )
        .execution_options(populate_existing=True)
    )
    source = db.scalar(
        select(RepositoryAssetFile)
        .where(
            RepositoryAssetFile.id == expected_asset_file_id,
            RepositoryAssetFile.user_id == plan.user_id,
            RepositoryAssetFile.snapshot_id == plan.asset_snapshot_id,
        )
        .execution_options(populate_existing=True)
    )
    attachment = db.scalar(
        select(Attachment)
        .where(
            Attachment.id == expected_attachment_id,
            Attachment.user_id == plan.user_id,
            Attachment.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    original = (
        db.scalar(
            select(RepositoryAssetPlanFile)
            .where(
                RepositoryAssetPlanFile.plan_id == source.plan_id,
                RepositoryAssetPlanFile.file_key_sha256 == source.file_key_sha256,
                RepositoryAssetPlanFile.user_id == plan.user_id,
            )
            .execution_options(populate_existing=True)
        )
        if source
        else None
    )
    if (
        row is None
        or source is None
        or attachment is None
        or original is None
        or (
            row.path,
            row.sha256,
            row.size_bytes,
            row.attachment_id,
            row.asset_file_id,
            row.asset_snapshot_id,
        )
        != (
            expected.path,
            expected.sha256,
            expected.size_bytes,
            expected_attachment_id,
            expected_asset_file_id,
            plan.asset_snapshot_id,
        )
        or (
            source.status,
            source.actual_sha256,
            source.actual_size_bytes,
            source.attachment_id,
            source.remote_verified,
        )
        != ("STORED", expected.sha256, expected.size_bytes, expected_attachment_id, True)
        or (attachment.sha256, attachment.size_bytes) != (expected.sha256, expected.size_bytes)
        or (original.path, original.size_bytes, original.selected, original.supported)
        != (expected.path, expected.size_bytes, True, True)
    ):
        raise DomainError(
            "PROJECT_SOURCE_CURRENT_FILE_CHANGED",
            "Current source member or attachment differs from frozen approval",
            409,
        )
    return row


async def create_plan(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    body: ProjectSourcePlanCreate,
    *,
    provider: ProjectSourceWorkspaceProvider | None = None,
) -> ProjectSourcePlan:
    _enabled()
    archive = _archive(db, owner, project)
    snapshot, asset_plan, source_files, planned = _asset(db, owner, body.asset_snapshot_id)
    if (
        len(source_files) > get_settings().repository_asset_max_files
        or snapshot.stored_bytes > get_settings().repository_asset_max_bytes
    ):
        raise DomainError(
            "PROJECT_SOURCE_LIMIT_EXCEEDED",
            "Measured source members exceed the host copy limits",
            422,
        )
    identity = uuid.uuid4()
    binding = ProjectPathBinding(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project,
        archive_binding_id=archive.id,
        root_fingerprint=archive_jobs.binding_fingerprint(archive),
        source_root_fingerprint=managed_root_fingerprint(
            Path(get_settings().project_provision_managed_root)
        ),
        relative_path=".researchos/cache/sources/" + str(identity),
        purpose="REPOSITORY_SOURCE",
        no_execution=True,
        scope_sha256="0" * 64,
        state="PROPOSED",
        created_at=now(),
    )
    plan = ProjectSourcePlan(
        id=identity,
        user_id=owner,
        project_id=project,
        path_binding_id=binding.id,
        asset_snapshot_id=snapshot.id,
        asset_manifest_sha256=snapshot.manifest_sha256,
        archive_identity_sha256=archive_identity(archive),
        source_snapshot_id=asset_plan.source_snapshot_id,
        provider_key=asset_plan.provider_key,
        repo_kind=asset_plan.repo_kind,
        repo_id=asset_plan.repo_id,
        provider_id=asset_plan.provider_id,
        commit_sha=asset_plan.commit_sha,
        source_status=snapshot.status,
        gaps_text=snapshot.gaps_text,
        file_count=len(source_files),
        total_bytes=snapshot.stored_bytes,
        plan_sha256="0" * 64,
        state="DRAFT",
        created_at=now(),
    )
    files = [
        ProjectSourcePlanFile(
            plan_id=identity,
            user_id=owner,
            project_id=project,
            asset_snapshot_id=snapshot.id,
            asset_file_id=row.id,
            attachment_id=row.attachment_id,
            file_key_sha256=digest({"path": planned[row.file_key_sha256].path}),
            path=planned[row.file_key_sha256].path,
            sha256=row.actual_sha256,
            size_bytes=row.actual_size_bytes,
        )
        for row in source_files
    ]
    binding.scope_sha256 = binding_hash(binding, plan)
    plan.plan_sha256 = plan_hash(plan, binding, files)
    try:
        db.add(binding)
        db.flush()
        db.add(plan)
        db.flush()
        db.add_all(files)
        db.flush()
        _validate(db, plan)
        scope = policy_scope(db, plan)
        adapter = provider or project_source_workspace_provider(scope, readonly=True)
        await asyncio.to_thread(adapter.readiness, scope, policy_files(db, plan))
        db.commit()
    except DomainError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "PROJECT_SOURCE_PLAN_CONFLICT",
            "Source placement identity violates the exact project scope",
            409,
        ) from None
    db.refresh(plan)
    return plan


def event(db: Session, job: ProjectSourceJob, kind: str, code: str | None = None) -> None:
    db.add(
        ResearchEvent(
            event_id=uuid.uuid4(),
            user_id=job.user_id,
            event_type="project.source." + kind.lower(),
            occurred_at=now(),
            source="project-source-worker",
            correlation_id=job.id,
            payload={
                "job_id": str(job.id),
                "plan_id": str(job.plan_id),
                "project_id": str(job.project_id),
                "status": job.status,
                "code": code,
            },
        )
    )


async def approve_plan(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    identity: uuid.UUID,
    body: ProjectSourcePlanApprove,
    *,
    provider: ProjectSourceWorkspaceProvider | None = None,
) -> ProjectSourcePlan:
    plan = get_plan(db, owner, project, identity, lock=True)
    if plan.plan_sha256 != body.expected_sha256:
        raise DomainError(
            "PROJECT_SOURCE_APPROVAL_CHANGED",
            "Review the exact measured copy scope before approval",
            409,
        )
    if plan.state == "APPROVED":
        return plan
    _enabled()
    locked_binding = get_binding(db, owner, project, plan.path_binding_id, lock=True)
    if locked_binding.state != "PROPOSED":
        raise DomainError(
            "PROJECT_SOURCE_BINDING_INACTIVE", "A revoked destination cannot be approved", 409
        )
    binding = _validate(db, plan)
    scope = policy_scope(db, plan)
    adapter = provider or project_source_workspace_provider(scope)
    await asyncio.to_thread(adapter.readiness, scope, policy_files(db, plan))
    try:
        plan.state, plan.approved_hash, plan.approved_by, plan.approved_at = (
            "APPROVED",
            plan.plan_sha256,
            owner,
            now(),
        )
        binding.state, binding.approved_hash, binding.approved_by, binding.approved_at = (
            "ACTIVE",
            binding.scope_sha256,
            owner,
            now(),
        )
        job = ProjectSourceJob(
            id=uuid.uuid4(),
            user_id=owner,
            project_id=project,
            plan_id=plan.id,
            path_binding_id=binding.id,
            active_binding_id=binding.id,
            status="QUEUED",
            created_at=now(),
        )
        db.add(job)
        db.flush()
        event(db, job, "QUEUED")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "PROJECT_SOURCE_APPROVAL_CONFLICT",
            "Another exact scope approval already created its copy job",
            409,
        ) from None
    db.refresh(plan)
    return plan


def cancel_job(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ProjectSourceJob:
    job = get_job(db, owner, project, identity, lock=True)
    if job.status == "QUEUED":
        job.status, job.active_binding_id, job.finished_at = "CANCELLED", None, now()
    elif job.status == "COPYING":
        job.status = "CANCEL_REQUESTED"
    event(db, job, "CANCEL_REQUESTED" if job.status == "CANCEL_REQUESTED" else "CANCEL_OBSERVED")
    db.commit()
    db.refresh(job)
    return job


def revoke_binding(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ProjectPathBinding:
    binding = get_binding(db, owner, project, identity, lock=True)
    binding.state = "REVOKED"
    rows = list(
        db.scalars(
            select(ProjectSourceJob)
            .where(
                ProjectSourceJob.path_binding_id == binding.id,
                ProjectSourceJob.project_id == project,
                ProjectSourceJob.user_id == owner,
                ProjectSourceJob.status.in_(["QUEUED", "COPYING"]),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for job in rows:
        if job.status == "QUEUED":
            job.status, job.active_binding_id, job.finished_at = "CANCELLED", None, now()
        else:
            job.status = "CANCEL_REQUESTED"
        event(db, job, "BINDING_REVOKED")
    db.commit()
    db.refresh(binding)
    return binding


def resume_job(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ProjectSourceJob:
    job = get_job(db, owner, project, identity, lock=True)
    validate_plan(db, job)
    if job.status not in {"FAILED", "CANCELLED"} or job.lease_token is not None:
        raise DomainError(
            "PROJECT_SOURCE_RESUME_UNAVAILABLE",
            "Only confirmed stopped jobs without a live copy lease may resume",
            409,
        )
    job.status, job.active_binding_id, job.error_code, job.error_message, job.finished_at = (
        "QUEUED",
        job.path_binding_id,
        None,
        None,
        None,
    )
    try:
        event(db, job, "RESUMED")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "PROJECT_SOURCE_JOB_ACTIVE", "Another current copy owns this path binding", 409
        ) from None
    db.refresh(job)
    return job


def plan_out(db: Session, plan: ProjectSourcePlan) -> ProjectSourcePlanOut:
    binding = get_binding(db, plan.user_id, plan.project_id, plan.path_binding_id)
    valid = True
    try:
        _validate(db, plan)
    except (DomainError, ValueError, TypeError):
        valid = False
    initial = db.scalar(
        select(ProjectSourceJob.id)
        .where(
            ProjectSourceJob.user_id == plan.user_id,
            ProjectSourceJob.project_id == plan.project_id,
            ProjectSourceJob.plan_id == plan.id,
        )
        .order_by(ProjectSourceJob.created_at)
        .limit(1)
    )
    fields = {
        key: getattr(plan, key)
        for key in ProjectSourcePlanOut.model_fields
        if key
        not in {
            "gaps",
            "root_label",
            "binding",
            "can_approve",
            "initial_job_id",
            "execution_authorized",
        }
    }
    return ProjectSourcePlanOut(
        **fields,
        gaps=json.loads(plan.gaps_text)
        + ["SOURCE_CACHE_NOT_EXECUTABLE_WORKSPACE", "NO_BASELINE_QUALIFICATION"],
        root_label=(
            _archive(db, plan.user_id, plan.project_id).managed_folder_name
            or _archive(db, plan.user_id, plan.project_id).workspace_key
        )
        + "/"
        + binding.relative_path,
        binding=ProjectPathBindingOut.model_validate(binding),
        can_approve=valid
        and capability().enabled
        and binding.state == "PROPOSED"
        and plan.state == "DRAFT",
        initial_job_id=initial,
    )


def job_out(db: Session, job: ProjectSourceJob) -> ProjectSourceJobOut:
    plan = get_plan(db, job.user_id, job.project_id, job.plan_id)
    binding = get_binding(db, job.user_id, job.project_id, plan.path_binding_id)
    valid = True
    try:
        _validate(db, plan)
    except (DomainError, ValueError, TypeError):
        valid = False
    active = valid and binding.state == "ACTIVE" and capability().enabled
    fields = {
        key: getattr(job, key)
        for key in (
            "id",
            "project_id",
            "plan_id",
            "path_binding_id",
            "status",
            "copied_files",
            "copied_bytes",
            "receipt_sha256",
            "receipt_path",
            "verified_at",
            "error_code",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
        )
    }
    return ProjectSourceJobOut(
        **fields,
        can_cancel=job.status in {"QUEUED", "COPYING", "CANCEL_REQUESTED"},
        can_resume=active and job.status in {"FAILED", "CANCELLED"} and job.lease_token is None,
        can_verify=valid and plan.state == "APPROVED",
        can_reconcile=valid and plan.state == "APPROVED" and job.status == "NEEDS_ATTENTION",
        source_status=plan.source_status,
        gaps=json.loads(plan.gaps_text)
        + ["RECORDED_COPY_NOT_CURRENT_FILESYSTEM_CHECK", "NO_EXECUTION_OR_BASELINE_PERMISSION"],
        root_label=plan_out(db, plan).root_label,
        binding_state=binding.state,
    )


async def verify_job(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    identity: uuid.UUID,
    *,
    provider: ProjectSourceWorkspaceProvider | None = None,
) -> ProjectSourceVerifyOut:
    job = get_job(db, owner, project, identity)
    plan = get_plan(db, owner, project, job.plan_id)
    _validate(db, plan)
    if plan.state != "APPROVED":
        raise DomainError(
            "PROJECT_SOURCE_NOT_APPROVED",
            "An original owner copy approval is required for destination verification",
            409,
        )
    scope = policy_scope(db, plan)
    adapter = provider or project_source_workspace_provider(scope, readonly=True)
    with adapter.exclusive(scope):
        checks = []
        for file in policy_files(db, plan):
            try:
                receipt = await asyncio.to_thread(adapter.inspect, scope, file)
                checks.append(
                    ProjectSourceCheckOut(
                        path=file.path,
                        status="MISSING"
                        if receipt is None
                        else "VERIFIED"
                        if (receipt.path, receipt.sha256, receipt.size_bytes)
                        == (file.path, file.sha256, file.size_bytes)
                        else "CHANGED",
                        actual_sha256=receipt.sha256 if receipt else None,
                        actual_size_bytes=receipt.size_bytes if receipt else None,
                    )
                )
            except DomainError as error:
                checks.append(
                    ProjectSourceCheckOut(
                        path=file.path,
                        status="UNSAFE"
                        if "PATH" in error.code or "SCOPE" in error.code
                        else "UNAVAILABLE",
                    )
                )
            except (OSError, ValueError):
                checks.append(ProjectSourceCheckOut(path=file.path, status="UNAVAILABLE"))
        manifest_valid = False
        manifest_gaps: list[str] = []
        try:
            manifest = await asyncio.to_thread(
                adapter.inspect_manifest, scope, policy_files(db, plan)
            )
            manifest_valid = manifest is not None and (
                manifest.manifest_sha256,
                manifest.relative_path,
            ) == (job.receipt_sha256, job.receipt_path)
            if not manifest_valid:
                manifest_gaps.append("DESTINATION_MANIFEST_MISSING_OR_CHANGED")
        except (DomainError, OSError, ValueError):
            manifest_gaps.append("DESTINATION_MANIFEST_UNAVAILABLE_OR_UNSAFE")
    return ProjectSourceVerifyOut(
        job_id=job.id,
        checked_at=now(),
        verified=bool(checks)
        and all(row.status == "VERIFIED" for row in checks)
        and manifest_valid,
        files=checks,
        gaps=manifest_gaps
        + (
            [
                "CURRENT_READONLY_OBSERVATION_NOT_EXPORT_OR_SCIENTIFIC_REVIEW",
                "PARTIAL_SOURCE_REMAINS_PARTIAL",
            ]
            if plan.source_status == "PARTIAL"
            else ["CURRENT_READONLY_OBSERVATION_NOT_EXECUTION_AUTHORITY"]
        ),
    )


def reconcile_job(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    identity: uuid.UUID,
    *,
    provider: ProjectSourceWorkspaceProvider | None = None,
) -> ProjectSourceJob:
    """Confirm an uncertain local copy has stopped, without creating or altering any file."""
    job = get_job(db, owner, project, identity, lock=True)
    if job.status != "NEEDS_ATTENTION":
        raise DomainError(
            "PROJECT_SOURCE_RECONCILE_UNAVAILABLE",
            "Only an uncertain local copy requires reconciliation",
            409,
        )
    plan = get_plan(db, owner, project, job.plan_id)
    _validate(db, plan)
    if plan.state != "APPROVED" or plan.approved_hash != plan.plan_sha256:
        raise DomainError("PROJECT_SOURCE_NOT_APPROVED", "Original exact approval is required", 409)
    scope = policy_scope(db, plan)
    adapter = provider or project_source_workspace_provider(scope, readonly=True)
    try:
        with adapter.exclusive(scope):
            files = policy_files(db, plan)
            for file in files:
                receipt = adapter.inspect(scope, file)
                if receipt is not None and (receipt.path, receipt.sha256, receipt.size_bytes) != (
                    file.path,
                    file.sha256,
                    file.size_bytes,
                ):
                    raise DomainError(
                        "PROJECT_SOURCE_DESTINATION_CHANGED",
                        "Destination bytes differ from the approved source",
                        409,
                    )
            adapter.inspect_manifest(scope, files)
            job.status = "FAILED"
            job.active_binding_id = None
            job.lease_token = None
            job.lease_expires_at = None
            job.finished_at = now()
            job.error_code = "PROJECT_SOURCE_COPY_STOP_CONFIRMED"
            job.error_message = "Local copy lock is free and destination files are absent or exact; explicitly resume to continue."
            event(db, job, "STOP_CONFIRMED", job.error_code)
            db.commit()
    except (DomainError, OSError, ValueError):
        db.rollback()
        raise DomainError(
            "PROJECT_SOURCE_RECONCILE_UNCERTAIN",
            "The copy lock or destination cannot yet prove a safe stopped state",
            409,
        ) from None
    db.refresh(job)
    return job


def list_plans(
    db: Session, owner: uuid.UUID, project: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[ProjectSourcePlan], str | None]:
    get_project(db, owner, project)
    rows = list(
        db.scalars(
            select(ProjectSourcePlan)
            .where(
                ProjectSourcePlan.user_id == owner,
                ProjectSourcePlan.project_id == project,
                cursor_filter(ProjectSourcePlan, cursor),
            )
            .order_by(ProjectSourcePlan.created_at.desc(), ProjectSourcePlan.id.desc())
            .limit(limit + 1)
        )
    )
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None


def list_jobs(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    plan_id: uuid.UUID,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[ProjectSourceJob], str | None]:
    get_plan(db, owner, project, plan_id)
    rows = list(
        db.scalars(
            select(ProjectSourceJob)
            .where(
                ProjectSourceJob.user_id == owner,
                ProjectSourceJob.project_id == project,
                ProjectSourceJob.plan_id == plan_id,
                cursor_filter(ProjectSourceJob, cursor),
            )
            .order_by(ProjectSourceJob.created_at.desc(), ProjectSourceJob.id.desc())
            .limit(limit + 1)
        )
    )
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None


def files_out(
    db: Session, job: ProjectSourceJob, limit: int = 20, cursor: str | None = None
) -> tuple[list[ProjectSourceFileOut], str | None]:
    rows = list(
        db.execute(
            select(ProjectSourceFile, ProjectSourcePlanFile.path)
            .join(
                ProjectSourcePlanFile,
                (ProjectSourcePlanFile.plan_id == ProjectSourceFile.plan_id)
                & (ProjectSourcePlanFile.file_key_sha256 == ProjectSourceFile.file_key_sha256)
                & (ProjectSourcePlanFile.project_id == ProjectSourceFile.project_id)
                & (ProjectSourcePlanFile.user_id == ProjectSourceFile.user_id),
            )
            .where(
                ProjectSourceFile.job_id == job.id,
                ProjectSourceFile.project_id == job.project_id,
                ProjectSourceFile.user_id == job.user_id,
                cursor_filter(ProjectSourceFile, cursor),
            )
            .order_by(ProjectSourceFile.created_at.desc(), ProjectSourceFile.id.desc())
            .limit(limit + 1)
        )
    )
    result = [
        ProjectSourceFileOut(
            **{
                key: getattr(row, key)
                for key in (
                    "id",
                    "file_key_sha256",
                    "status",
                    "actual_sha256",
                    "actual_size_bytes",
                    "relative_path",
                    "verified_at",
                    "error_code",
                    "created_at",
                )
            },
            path=path,
        )
        for row, path in rows[:limit]
    ]
    return result, encode_cursor(rows[limit - 1][0].created_at, rows[limit - 1][0].id) if len(
        rows
    ) > limit else None


def events_out(db: Session, job: ProjectSourceJob) -> list[ProjectSourceEventOut]:
    rows = list(
        db.scalars(
            select(ResearchEvent)
            .where(
                ResearchEvent.user_id == job.user_id,
                ResearchEvent.correlation_id == job.id,
                ResearchEvent.event_type.like("project.source.%"),
            )
            .order_by(ResearchEvent.occurred_at, ResearchEvent.id)
        )
    )
    return [
        ProjectSourceEventOut(
            id=row.event_id,
            event_type=row.event_type,
            occurred_at=row.occurred_at,
            status=row.payload.get("status")
            if isinstance(row.payload.get("status"), str)
            else None,
            code=row.payload.get("code") if isinstance(row.payload.get("code"), str) else None,
            receipt_sha256=row.payload.get("receipt_sha256")
            if isinstance(row.payload.get("receipt_sha256"), str)
            else None,
            receipt_path=row.payload.get("receipt_path")
            if isinstance(row.payload.get("receipt_path"), str)
            else None,
            disposition="QUARANTINED" if row.payload.get("disposition") == "QUARANTINED" else None,
        )
        for row in rows
    ]
