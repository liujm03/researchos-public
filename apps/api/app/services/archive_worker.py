"""Fenced, one-project-at-a-time archive execution and source-proven recovery."""

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.archive_catalog import ArchiveCatalogVersion
from app.domain.archive_execution import ArchiveExecutionProvider, ArchiveExecutionScope
from app.domain.github_archive import GitHubPrivateRepository, GitHubPublicationReceipt
from app.domain.project_archive import ProjectVersionManifest
from app.errors import DomainError
from app.models_archive_jobs import ProjectArchiveJob
from app.models_project_archives import (
    ProjectArchiveBinding,
    ProjectArchiveFile,
    ProjectArchiveVersion,
)
from app.providers.registry import archive_execution_provider
from app.services.archive_jobs import event

LEASE_SECONDS = 600


def _reload(db: Session, identity: uuid.UUID) -> ProjectArchiveJob:
    job = db.get(ProjectArchiveJob, identity)
    if job is None:
        raise DomainError("NOT_FOUND", "Archive job no longer exists", 404)
    return job


def _scope(binding: ProjectArchiveBinding, fingerprint: str) -> ArchiveExecutionScope:
    return ArchiveExecutionScope(
        binding.workspace_key,
        fingerprint,
        binding.local_project_id,
        GitHubPrivateRepository(
            binding.github_repository_id,
            binding.github_owner,
            binding.github_owner_id,
            binding.github_repository,
            "researchos-archive",
            True,
        ),
        binding.managed_folder_name,
        binding.managed_root_fingerprint,
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _checkpoint(
    db: Session,
    job: ProjectArchiveJob,
    lease: uuid.UUID,
    expected: str,
    status: str,
    **values: object,
) -> ProjectArchiveJob:
    moment = _now()
    result = db.execute(
        update(ProjectArchiveJob)
        .where(
            ProjectArchiveJob.id == job.id,
            ProjectArchiveJob.user_id == job.user_id,
            ProjectArchiveJob.lease_token == lease,
            ProjectArchiveJob.status == expected,
            ProjectArchiveJob.lease_expires_at > moment,
        )
        .values(status=status, updated_at=moment, **values)
        .returning(ProjectArchiveJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if result != job.id:
        db.rollback()
        raise DomainError(
            "ARCHIVE_LEASE_LOST", "Archive execution fence changed; retain external receipts", 409
        )
    event(db, job, status, "Archive stage: " + status)
    db.commit()
    db.expire_all()
    return _reload(db, job.id)


def quarantine_expired(db: Session, owner: uuid.UUID) -> int:
    rows = list(
        db.scalars(
            select(ProjectArchiveJob).where(
                ProjectArchiveJob.user_id == owner,
                ProjectArchiveJob.status.in_(["PREPARING", "COMMITTING", "PUBLISHING"]),
                ProjectArchiveJob.lease_expires_at <= _now(),
            )
        )
    )
    for job in rows:
        # Never free an uncertain side-effect slot merely because time passed.
        quarantined = db.execute(
            update(ProjectArchiveJob)
            .where(
                ProjectArchiveJob.id == job.id,
                ProjectArchiveJob.user_id == owner,
                ProjectArchiveJob.status.in_(["PREPARING", "COMMITTING", "PUBLISHING"]),
                ProjectArchiveJob.lease_expires_at <= _now(),
            )
            .values(
                status="NEEDS_ATTENTION",
                lease_token=None,
                lease_expires_at=None,
                error_code="ARCHIVE_EXECUTION_EXPIRED",
                error_message="Host execution expired; inspect frozen local and remote receipts before another run",
            )
            .returning(ProjectArchiveJob.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if quarantined == job.id:
            event(
                db,
                job,
                "NEEDS_ATTENTION",
                "Host lease expired; retained source and execution slot need verification",
            )
    db.commit()
    return len(rows)


def _complete(
    db: Session,
    job: ProjectArchiveJob,
    lease: uuid.UUID,
    expected: str,
    source: ArchiveCatalogVersion,
    remote: GitHubPublicationReceipt,
) -> ProjectArchiveJob:
    binding = db.get(ProjectArchiveBinding, job.binding_id)
    receipt, manifest = source.receipt, source.manifest
    if (
        binding is None
        or binding.user_id != job.user_id
        or remote.private is not True
        or remote.repository_id != binding.github_repository_id
        or remote.repository_full_name.casefold()
        != f"{binding.github_owner}/{binding.github_repository}".casefold()
        or remote.tag_commit != receipt.commit_sha
        or remote.version != job.tag
        or receipt.tag != job.tag
        or manifest.sha256 != job.manifest_sha256
        or receipt.manifest_sha256 != remote.manifest_sha256
        or receipt.manifest_sha256 != manifest.sha256
        or receipt.owner_id != manifest.owner_id
        or receipt.owner_id != f"github:{binding.github_owner_id}"
        or receipt.project_id != manifest.project_id
        or receipt.project_id != binding.local_project_id
        or receipt.version != manifest.version
        or receipt.version != job.tag
        or (job.commit_sha is not None and job.commit_sha != receipt.commit_sha)
    ):
        raise DomainError(
            "ARCHIVE_RESULT_CONFLICT",
            "Execution result does not prove the frozen private project version",
            409,
        )
    version = db.scalar(
        select(ProjectArchiveVersion).where(
            ProjectArchiveVersion.user_id == job.user_id,
            ProjectArchiveVersion.binding_id == job.binding_id,
            ProjectArchiveVersion.tag == job.tag,
        )
    )
    files = {(row.path, row.sha256, row.size_bytes) for row in manifest.files}
    if version is None:
        version = ProjectArchiveVersion(
            user_id=job.user_id,
            binding_id=job.binding_id,
            tag=job.tag,
            commit_sha=receipt.commit_sha,
            manifest_sha256=manifest.sha256,
            parent_commit=manifest.parent_commit,
            file_count=len(files),
            total_bytes=sum(row.size_bytes for row in manifest.files),
        )
        db.add(version)
        db.flush()
        db.add_all(
            [
                ProjectArchiveFile(
                    version_id=version.id,
                    user_id=job.user_id,
                    path=row.path,
                    sha256=row.sha256,
                    size_bytes=row.size_bytes,
                )
                for row in manifest.files
            ]
        )
    else:
        retained = {
            (row.path, row.sha256, row.size_bytes)
            for row in db.scalars(
                select(ProjectArchiveFile).where(
                    ProjectArchiveFile.user_id == job.user_id,
                    ProjectArchiveFile.version_id == version.id,
                )
            )
        }
        if (
            version.commit_sha,
            version.manifest_sha256,
            version.parent_commit,
            version.file_count,
            version.total_bytes,
        ) != (
            receipt.commit_sha,
            manifest.sha256,
            manifest.parent_commit,
            len(files),
            sum(row.size_bytes for row in manifest.files),
        ) or retained != files:
            raise DomainError(
                "ARCHIVE_RESULT_CONFLICT",
                "Existing immutable inventory differs from the recovered result",
                409,
            )
    version.remote_tag_commit = receipt.commit_sha
    version.remote_verified_at = _now()
    return _checkpoint(
        db,
        job,
        lease,
        expected,
        "COMPLETED",
        active_binding_id=None,
        lease_token=None,
        lease_expires_at=None,
        version_id=version.id,
        commit_sha=receipt.commit_sha,
        finished_at=_now(),
        error_code=None,
        error_message=None,
    )


async def reconcile(
    db: Session, job: ProjectArchiveJob, *, executor: ArchiveExecutionProvider | None = None
) -> ProjectArchiveJob:
    if job.status != "NEEDS_ATTENTION":
        raise DomainError(
            "ARCHIVE_RECONCILE_NOT_ATTENTION",
            "Only an unconfirmed archive execution can be reconciled",
            409,
        )
    lease = uuid.uuid4()
    now = _now()
    claimed = db.execute(
        update(ProjectArchiveJob)
        .where(
            ProjectArchiveJob.id == job.id,
            ProjectArchiveJob.user_id == job.user_id,
            ProjectArchiveJob.status == "NEEDS_ATTENTION",
            (ProjectArchiveJob.lease_expires_at.is_(None))
            | (ProjectArchiveJob.lease_expires_at <= now),
        )
        .values(lease_token=lease, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS))
        .returning(ProjectArchiveJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if claimed != job.id:
        db.rollback()
        raise DomainError("ARCHIVE_RECONCILE_BUSY", "Another verification is active", 409)
    db.commit()
    db.expire_all()
    job = _reload(db, job.id)
    try:
        binding = db.get(ProjectArchiveBinding, job.binding_id)
        if binding is None or binding.user_id != job.user_id:
            raise DomainError("NOT_FOUND", "Archive binding is unavailable", 404)
        provider = (
            executor
            if executor is not None
            else await asyncio.to_thread(
                archive_execution_provider,
                _scope(binding, job.workspace_fingerprint),
                readonly=True,
            )
        )
        with provider.exclusive():
            if job.manifest_sha256 is None:
                return _checkpoint(
                    db,
                    job,
                    lease,
                    "NEEDS_ATTENTION",
                    "FAILED",
                    active_binding_id=None,
                    lease_token=None,
                    lease_expires_at=None,
                    finished_at=_now(),
                    error_code="ARCHIVE_NO_FROZEN_SOURCE",
                    error_message="No commit stage was recorded; no frozen code version was executed",
                )
            source = await asyncio.to_thread(provider.inspect_local, job.tag, job.manifest_sha256)
            if source is None:
                raise DomainError(
                    "ARCHIVE_LOCAL_UNCONFIRMED",
                    "Frozen local tag has not been proven; no commit or push was repeated",
                    409,
                )
            remote = await provider.inspect_remote(source.receipt)
            if remote is None:
                raise DomainError(
                    "ARCHIVE_REMOTE_UNCONFIRMED",
                    "Exact remote tag is not present; local version is retained without another push",
                    409,
                )
            return _complete(db, job, lease, "NEEDS_ATTENTION", source, remote)
    except Exception as failure:
        db.rollback()
        job = _reload(db, job.id)
        error_code = (
            failure.code[:80] if isinstance(failure, DomainError) else "ARCHIVE_RECONCILE_FAILURE"
        )
        error_message = (
            failure.message[:2000]
            if isinstance(failure, DomainError)
            else "Host verification was not confirmed; no code commit or push repeated"
        )
        cleared = db.execute(
            update(ProjectArchiveJob)
            .where(
                ProjectArchiveJob.id == job.id,
                ProjectArchiveJob.user_id == job.user_id,
                ProjectArchiveJob.status == "NEEDS_ATTENTION",
                ProjectArchiveJob.lease_token == lease,
            )
            .values(
                lease_token=None,
                lease_expires_at=None,
                error_code=error_code,
                error_message=error_message,
            )
            .returning(ProjectArchiveJob.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if cleared == job.id:
            event(db, job, "RECONCILE_UNCONFIRMED", error_message)
            db.commit()
        else:
            db.rollback()
        db.expire_all()
        return _reload(db, job.id)


async def process_next(
    db: Session, owner: uuid.UUID, *, executor: ArchiveExecutionProvider | None = None
) -> ProjectArchiveJob | None:
    quarantine_expired(db, owner)
    if not get_settings().project_archive_write_enabled:
        return None
    job = db.scalar(
        select(ProjectArchiveJob)
        .where(ProjectArchiveJob.user_id == owner, ProjectArchiveJob.status == "QUEUED")
        .order_by(ProjectArchiveJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    lease = uuid.uuid4()
    started = _now()
    claimed = db.execute(
        update(ProjectArchiveJob)
        .where(
            ProjectArchiveJob.id == job.id,
            ProjectArchiveJob.user_id == owner,
            ProjectArchiveJob.status == "QUEUED",
        )
        .values(
            status="PREPARING",
            lease_token=lease,
            lease_expires_at=started + timedelta(seconds=LEASE_SECONDS),
            started_at=started,
        )
        .returning(ProjectArchiveJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if claimed != job.id:
        db.rollback()
        return None
    event(db, job, "PREPARING", "Host is checking the existing project scope and source files")
    db.commit()
    db.expire_all()
    job = _reload(db, job.id)
    try:
        binding = db.get(ProjectArchiveBinding, job.binding_id)
        if binding is None or binding.user_id != owner:
            raise DomainError("NOT_FOUND", "Archive binding is unavailable", 404)
        if job.trigger_kind == "SCHEDULED" and not binding.auto_enabled:
            return _checkpoint(
                db,
                job,
                lease,
                "PREPARING",
                "CANCELLED",
                active_binding_id=None,
                lease_token=None,
                lease_expires_at=None,
                finished_at=_now(),
            )
        provider = (
            executor
            if executor is not None
            else await asyncio.to_thread(
                archive_execution_provider, _scope(binding, job.workspace_fingerprint)
            )
        )
        with provider.exclusive():
            from app.services.code_changes import require_archive_clear
            db.expire_all()
            binding = db.get(ProjectArchiveBinding, job.binding_id)
            if binding is None:
                raise DomainError("NOT_FOUND", "Archive binding is unavailable", 404)
            require_archive_clear(db, binding)
            manifest = await asyncio.to_thread(provider.preflight, job.tag)
            payload = json.loads(json.dumps(asdict(manifest)))
            if (
                len(json.dumps(payload, ensure_ascii=False).encode()) > 2 * 1024 * 1024
                or len(manifest.files) > 2000
                or any(len(row.path) > 1024 for row in manifest.files)
                or manifest.version != job.tag
                or (manifest.owner_id, manifest.project_id)
                != (f"github:{binding.github_owner_id}", binding.local_project_id)
            ):
                raise DomainError(
                    "ARCHIVE_MANIFEST_INVALID",
                    "Frozen execution manifest exceeds its scope or size bounds",
                    409,
                )
            if await asyncio.to_thread(provider.is_unchanged, manifest):
                return _checkpoint(
                    db,
                    job,
                    lease,
                    "PREPARING",
                    "UNCHANGED",
                    active_binding_id=None,
                    lease_token=None,
                    lease_expires_at=None,
                    finished_at=_now(),
                )
            job = _checkpoint(
                db,
                job,
                lease,
                "PREPARING",
                "COMMITTING",
                manifest_payload=payload,
                manifest_sha256=manifest.sha256,
                lease_expires_at=_now() + timedelta(seconds=LEASE_SECONDS),
            )
            receipt = await asyncio.to_thread(provider.commit, manifest)
            if (
                receipt.tag != job.tag
                or receipt.manifest_sha256 != job.manifest_sha256
                or (receipt.owner_id, receipt.project_id, receipt.version)
                != (manifest.owner_id, manifest.project_id, manifest.version)
            ):
                raise DomainError(
                    "ARCHIVE_COMMIT_UNCONFIRMED",
                    "Local receipt differs from the frozen execution",
                    409,
                )
            job = _checkpoint(
                db,
                job,
                lease,
                "COMMITTING",
                "PUBLISHING",
                commit_sha=receipt.commit_sha,
                lease_expires_at=_now() + timedelta(seconds=LEASE_SECONDS),
            )
            remote = await provider.publish(receipt)
            return _complete(
                db,
                job,
                lease,
                "PUBLISHING",
                ArchiveCatalogVersion(
                    receipt,
                    TypeAdapter(ProjectVersionManifest).validate_python(job.manifest_payload),
                ),
                remote,
            )
    except Exception as failure:
        db.rollback()
        job = _reload(db, job.id)
        if job.lease_token != lease or job.status not in {"PREPARING", "COMMITTING", "PUBLISHING"}:
            return job
        uncertain = job.status in {"COMMITTING", "PUBLISHING"}
        final_status = "NEEDS_ATTENTION" if uncertain else "FAILED"
        error_code = (
            failure.code[:80] if isinstance(failure, DomainError) else "ARCHIVE_HOST_FAILURE"
        )
        error_message = (
            failure.message[:2000]
            if isinstance(failure, DomainError)
            else "Host archive operation was not confirmed; retained source and external receipts need inspection"
        )
        finalized = db.execute(
            update(ProjectArchiveJob)
            .where(
                ProjectArchiveJob.id == job.id,
                ProjectArchiveJob.user_id == owner,
                ProjectArchiveJob.lease_token == lease,
                ProjectArchiveJob.status.in_(["PREPARING", "COMMITTING", "PUBLISHING"]),
            )
            .values(
                status=final_status,
                active_binding_id=job.binding_id if uncertain else None,
                finished_at=None if uncertain else _now(),
                lease_token=None,
                lease_expires_at=None,
                error_code=error_code,
                error_message=error_message,
            )
            .returning(ProjectArchiveJob.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if finalized == job.id:
            event(db, job, final_status, error_message)
        db.commit()
        db.expire_all()
        return _reload(db, job.id)
