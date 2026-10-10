"""Owner-selected archive queue and continuous policy; no Git I/O in API routes."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.errors import DomainError
from app.models_archive_jobs import ProjectArchiveJob, ProjectArchiveJobEvent
from app.models_project_archives import ProjectArchiveBinding, ProjectArchiveVersion
from app.providers.registry import archive_workspace_fingerprint
from app.schemas_archive_jobs import ArchivePolicyPatch
from app.services.projects import get_project


def binding_for(db: Session, owner: uuid.UUID, project: uuid.UUID) -> ProjectArchiveBinding:
    get_project(db, owner, project)
    binding = db.scalar(
        select(ProjectArchiveBinding).where(
            ProjectArchiveBinding.user_id == owner, ProjectArchiveBinding.project_id == project
        )
    )
    if binding is None:
        raise DomainError(
            "ARCHIVE_BINDING_REQUIRED",
            "Select and register this project's existing private archive first",
            404,
        )
    return binding


def event(db: Session, job: ProjectArchiveJob, kind: str, message: str) -> None:
    db.add(
        ProjectArchiveJobEvent(
            user_id=job.user_id, job_id=job.id, event_kind=kind, message=message[:2000]
        )
    )


def get_job(
    db: Session, owner: uuid.UUID, project: uuid.UUID, job_id: uuid.UUID
) -> ProjectArchiveJob:
    binding = binding_for(db, owner, project)
    job = db.scalar(
        select(ProjectArchiveJob).where(
            ProjectArchiveJob.id == job_id,
            ProjectArchiveJob.user_id == owner,
            ProjectArchiveJob.binding_id == binding.id,
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Archive job not found in this project", 404)
    return job


def binding_fingerprint(binding: ProjectArchiveBinding) -> str:
    if binding.managed_folder_name is None:
        return archive_workspace_fingerprint(binding.workspace_key)
    return archive_workspace_fingerprint(binding.workspace_key, managed_folder_name=binding.managed_folder_name, managed_root_fingerprint=binding.managed_root_fingerprint)


def list_jobs(
    db: Session, owner: uuid.UUID, project: uuid.UUID, limit: int = 100
) -> list[ProjectArchiveJob]:
    binding = binding_for(db, owner, project)
    return list(
        db.scalars(
            select(ProjectArchiveJob)
            .where(ProjectArchiveJob.user_id == owner, ProjectArchiveJob.binding_id == binding.id)
            .order_by(ProjectArchiveJob.created_at.desc(), ProjectArchiveJob.id.desc())
            .limit(limit)
        )
    )


def job_events(
    db: Session, owner: uuid.UUID, project: uuid.UUID, job_id: uuid.UUID
) -> list[ProjectArchiveJobEvent]:
    job = get_job(db, owner, project, job_id)
    return list(
        db.scalars(
            select(ProjectArchiveJobEvent)
            .where(ProjectArchiveJobEvent.user_id == owner, ProjectArchiveJobEvent.job_id == job.id)
            .order_by(ProjectArchiveJobEvent.created_at, ProjectArchiveJobEvent.id)
        )
    )


def enqueue(
    db: Session,
    binding: ProjectArchiveBinding,
    tag: str | None = None,
    *,
    trigger: str = "MANUAL",
    now: datetime | None = None,
    commit: bool = True,
) -> ProjectArchiveJob:
    if not get_settings().project_archive_write_enabled:
        raise DomainError("ARCHIVE_WRITE_DISABLED", "Host archive writes are disabled", 503)
    from app.services.code_changes import require_archive_clear
    require_archive_clear(db, binding)
    active = db.scalar(
        select(ProjectArchiveJob).where(
            ProjectArchiveJob.user_id == binding.user_id,
            ProjectArchiveJob.active_binding_id == binding.id,
        )
    )
    if active is not None:
        raise DomainError(
            "ARCHIVE_JOB_ACTIVE", "This project has an active or unconfirmed archive job", 409
        )
    fingerprint = binding_fingerprint(binding)
    if binding.workspace_fingerprint is not None and binding.workspace_fingerprint != fingerprint:
        raise DomainError(
            "ARCHIVE_SCOPE_CHANGED",
            "Configured root changed; renew the project scope before running",
            409,
        )
    created = now or datetime.now(UTC)
    identity = uuid.uuid4()
    version = tag or f"v0.0.0-auto.{created.strftime('%Y%m%d%H%M%S')}.{identity.hex[:12]}"
    if (
        db.scalar(
            select(ProjectArchiveVersion.id).where(
                ProjectArchiveVersion.binding_id == binding.id,
                ProjectArchiveVersion.user_id == binding.user_id,
                ProjectArchiveVersion.tag == version,
            )
        )
        is not None
    ):
        raise DomainError("ARCHIVE_VERSION_EXISTS", "Existing version tags cannot be reused", 409)
    job = ProjectArchiveJob(
        id=identity,
        user_id=binding.user_id,
        binding_id=binding.id,
        active_binding_id=binding.id,
        tag=version,
        trigger_kind=trigger,
        status="QUEUED",
        workspace_fingerprint=fingerprint,
    )
    try:
        binding.workspace_fingerprint = fingerprint
        db.add(job)
        db.flush()
        event(db, job, "QUEUED", "Private code archive queued in the bound project scope")
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "ARCHIVE_JOB_CONFLICT", "Another active job or immutable tag already exists", 409
        ) from None
    db.refresh(job)
    return job


def cancel_queued(
    db: Session, owner: uuid.UUID, project: uuid.UUID, job_id: uuid.UUID
) -> ProjectArchiveJob:
    job = get_job(db, owner, project, job_id)
    if job.status != "QUEUED":
        raise DomainError(
            "ARCHIVE_CANCEL_NOT_QUEUED", "Only an unstarted archive job can be cancelled", 409
        )
    cancelled = db.execute(
        update(ProjectArchiveJob)
        .where(
            ProjectArchiveJob.id == job.id,
            ProjectArchiveJob.user_id == owner,
            ProjectArchiveJob.status == "QUEUED",
        )
        .values(status="CANCELLED", active_binding_id=None, finished_at=datetime.now(UTC))
        .returning(ProjectArchiveJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if cancelled != job.id:
        db.rollback()
        raise DomainError(
            "ARCHIVE_CANCEL_NOT_QUEUED",
            "Archive started before cancellation; execution fence retained",
            409,
        )
    event(db, job, "CANCELLED", "Owner cancelled the queued archive before execution")
    db.commit()
    db.refresh(job)
    return job


def update_policy(
    db: Session, owner: uuid.UUID, project: uuid.UUID, body: ArchivePolicyPatch
) -> ProjectArchiveBinding:
    binding = binding_for(db, owner, project)
    if body.auto_enabled:
        if not get_settings().project_archive_write_enabled:
            raise DomainError("ARCHIVE_WRITE_DISABLED", "Host archive writes are disabled", 503)
        fingerprint = binding_fingerprint(binding)
        if binding.auto_enabled and binding.workspace_fingerprint != fingerprint:
            raise DomainError(
                "ARCHIVE_SCOPE_CHANGED", "Disable and explicitly renew changed automatic scope", 409
            )
        binding.workspace_fingerprint = fingerprint
    binding.auto_enabled = body.auto_enabled
    binding.interval_minutes = body.interval_minutes
    binding.next_archive_at = datetime.now(UTC) if body.auto_enabled else None
    if not body.auto_enabled:
        queued = db.scalars(
            select(ProjectArchiveJob).where(
                ProjectArchiveJob.user_id == owner,
                ProjectArchiveJob.binding_id == binding.id,
                ProjectArchiveJob.trigger_kind == "SCHEDULED",
                ProjectArchiveJob.status == "QUEUED",
            )
        )
        for job in queued:
            cancelled = db.execute(
                update(ProjectArchiveJob)
                .where(
                    ProjectArchiveJob.id == job.id,
                    ProjectArchiveJob.user_id == owner,
                    ProjectArchiveJob.status == "QUEUED",
                )
                .values(status="CANCELLED", active_binding_id=None, finished_at=datetime.now(UTC))
                .returning(ProjectArchiveJob.id)
                .execution_options(synchronize_session=False)
            ).scalar_one_or_none()
            if cancelled == job.id:
                event(
                    db,
                    job,
                    "CANCELLED",
                    "Automatic policy disabled before the scheduled archive started",
                )
    db.commit()
    db.refresh(binding)
    return binding


def schedule_due(
    db: Session, owner: uuid.UUID, *, now: datetime | None = None
) -> ProjectArchiveJob | None:
    if not get_settings().project_archive_write_enabled:
        return None
    moment = now or datetime.now(UTC)
    binding = db.scalar(
        select(ProjectArchiveBinding)
        .where(
            ProjectArchiveBinding.user_id == owner,
            ProjectArchiveBinding.auto_enabled.is_(True),
            ProjectArchiveBinding.next_archive_at <= moment,
        )
        .order_by(ProjectArchiveBinding.next_archive_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if binding is None:
        return None
    binding.next_archive_at = moment + timedelta(minutes=binding.interval_minutes)
    db.commit()
    if (
        db.scalar(
            select(ProjectArchiveJob.id).where(
                ProjectArchiveJob.active_binding_id == binding.id,
                ProjectArchiveJob.user_id == owner,
            )
        )
        is not None
    ):
        return None
    try:
        return enqueue(db, binding, trigger="SCHEDULED", now=moment)
    except DomainError as error:
        if error.code == "ARCHIVE_SCOPE_CHANGED":
            binding.auto_enabled = False
            binding.next_archive_at = None
            db.commit()
        elif error.code not in {"ARCHIVE_JOB_ACTIVE", "ARCHIVE_JOB_CONFLICT"}:
            raise
        return None
