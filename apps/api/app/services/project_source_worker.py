"""Owner-fenced local source copies from frozen Storage objects, never network/code."""

import asyncio
import re
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.project_sources import (
    PROJECT_SOURCE_MANIFEST_NAME,
    ProjectSourceFileReceipt,
    ProjectSourceManifestReceipt,
    ProjectSourceScope,
    ProjectSourceWorkspaceProvider,
)
from app.domain.project_sources import (
    ProjectSourceFile as SourceFile,
)
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import Attachment, ResearchEvent
from app.models_project_sources import ProjectSourceFile, ProjectSourceJob, ProjectSourcePlan
from app.services import project_sources as policy

LEASE_SECONDS = 300
POLL_SECONDS = 1.0


@dataclass(frozen=True)
class _CopyFence:
    scope: ProjectSourceScope
    sha256: str


def now() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _error(code: str = "PROJECT_SOURCE_SCOPE_CHANGED") -> DomainError:
    return DomainError(
        code, "Source copy stopped; original bytes and previous receipts are retained", 409
    )


def _job(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> ProjectSourceJob | None:
    query = select(ProjectSourceJob).where(
        ProjectSourceJob.id == identity, ProjectSourceJob.user_id == owner
    )
    return db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )


def _terminal(job: ProjectSourceJob, status: str, code: str | None = None) -> None:
    job.status, job.error_code = status, code
    job.error_message = "Source copy stopped; previous receipts are retained" if code else None
    job.finished_at = now()
    if status != "NEEDS_ATTENTION":
        job.active_binding_id = None
        job.lease_token = job.lease_expires_at = None


def recover_stale(db: Session, owner: uuid.UUID) -> ProjectSourceJob | None:
    row = db.scalar(
        select(ProjectSourceJob)
        .where(
            ProjectSourceJob.user_id == owner,
            ProjectSourceJob.status.in_(("COPYING", "CANCEL_REQUESTED")),
            or_(ProjectSourceJob.lease_token.is_(None), ProjectSourceJob.lease_expires_at <= now()),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if row is None:
        db.rollback()
        return None
    _terminal(row, "NEEDS_ATTENTION", "PROJECT_SOURCE_LEASE_EXPIRED")
    policy.event(db, row, "NEEDS_ATTENTION", "PROJECT_SOURCE_LEASE_EXPIRED")
    db.commit()
    return row


def _claim(db: Session, owner: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    row = db.scalar(
        select(ProjectSourceJob)
        .where(ProjectSourceJob.user_id == owner, ProjectSourceJob.status == "QUEUED")
        .order_by(ProjectSourceJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if row is None:
        db.rollback()
        return None
    try:
        policy.validate_plan(db, row)
        token = uuid.uuid4()
        row.status, row.lease_token = "COPYING", token
        row.lease_expires_at, row.started_at = now() + timedelta(seconds=LEASE_SECONDS), now()
        row.copied_files, row.copied_bytes = 0, 0
        identity = row.id
        policy.event(db, row, "COPYING")
        db.commit()
        return identity, token
    except DomainError as error:
        _terminal(row, "FAILED", error.code)
        policy.event(db, row, "FAILED", error.code)
        db.commit()
        return None


def _check(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
    *,
    renew: bool = False,
    fence: _CopyFence | None = None,
) -> tuple[ProjectSourceJob, ProjectSourcePlan]:
    row = _job(db, owner, identity, lock=renew)
    if (
        row is None
        or row.lease_token != token
        or row.status != "COPYING"
        or row.lease_expires_at is None
        or utc(row.lease_expires_at) <= now()
    ):
        raise _error()
    plan = (
        policy.validate_plan(db, row)
        if fence is None
        else policy.validate_copy_fence(db, row, fence.scope, fence.sha256)
    )
    if renew:
        row.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        db.commit()
    return row, plan


async def _await_copy(
    operation: Coroutine[Any, Any, ProjectSourceFileReceipt],
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
    provider: ProjectSourceWorkspaceProvider,
    scope: ProjectSourceScope,
    file: SourceFile,
    fence: _CopyFence,
) -> ProjectSourceFileReceipt:
    task = asyncio.create_task(operation)
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=POLL_SECONDS)
            if not task.done():
                with Session(db.get_bind()) as watch:
                    try:
                        _check(watch, owner, identity, token, renew=True, fence=fence)
                    except DomainError:
                        task.cancel()
                        break
        return await task
    except asyncio.CancelledError:
        task.cancel()
        try:
            return await task
        except asyncio.CancelledError:
            try:
                located = provider.inspect(scope, file)
            except Exception:
                raise _error("PROJECT_SOURCE_COPY_OUTCOME_UNKNOWN") from None
            if located is not None:
                return located
            raise _error("PROJECT_SOURCE_COPY_INTERRUPTED") from None


def _checkpoint(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
    scope: ProjectSourceScope,
    key: str,
    file: SourceFile,
    receipt: ProjectSourceFileReceipt,
    fence: _CopyFence,
    attachment_id: uuid.UUID,
    asset_file_id: uuid.UUID,
) -> ProjectSourceFile:
    row = _job(db, owner, identity, lock=True)
    if row is None or row.plan_id != scope.plan_id or row.project_id != scope.project_id:
        raise _error()
    valid = (
        row.lease_token == token
        and row.status == "COPYING"
        and row.lease_expires_at is not None
        and utc(row.lease_expires_at) > now()
    )
    if valid:
        try:
            plan = policy.validate_copy_fence(db, row, fence.scope, fence.sha256)
            policy.current_file(db, plan, key, file, attachment_id, asset_file_id)
        except DomainError:
            valid = False
    if (receipt.path, receipt.sha256, receipt.size_bytes) != (
        file.path,
        file.sha256,
        file.size_bytes,
    ):
        raise _error("PROJECT_SOURCE_RECEIPT_INVALID")
    checkpoint = ProjectSourceFile(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=scope.project_id,
        job_id=identity,
        plan_id=scope.plan_id,
        file_key_sha256=key,
        status="QUARANTINED" if not valid else "REUSED" if receipt.reused else "COPIED",
        actual_sha256=receipt.sha256,
        actual_size_bytes=receipt.size_bytes,
        relative_path=scope.relative_path + "/" + file.path,
        verified_at=now(),
    )
    db.add(checkpoint)
    policy.event(db, row, "FILE_" + checkpoint.status)
    db.commit()
    return checkpoint


async def process_next(
    db: Session,
    owner: uuid.UUID,
    provider: ProjectSourceWorkspaceProvider | None = None,
    storage: StorageProvider | None = None,
) -> ProjectSourceJob | None:
    stale = recover_stale(db, owner)
    if stale is not None:
        return stale
    if not get_settings().project_source_workspaces_enabled:
        return None
    claimed = _claim(db, owner)
    if claimed is None:
        return None
    identity, token = claimed
    file_attempt: tuple[SourceFile, str, ProjectSourceScope] | None = None
    observed_manifest: ProjectSourceManifestReceipt | None = None
    try:
        from app.providers.registry import project_source_workspace_provider, storage_provider

        current, plan = _check(db, owner, identity, token)
        scope, files = policy.policy_scope(db, plan), policy.policy_files(db, plan)
        planned = list(policy.plan_files(db, plan))
        references = tuple(
            (file.file_key_sha256, file.attachment_id, file.asset_file_id) for file in planned
        )
        binding = policy.get_binding(db, owner, scope.project_id, plan.path_binding_id)
        fence = _CopyFence(scope, policy.copy_fence_sha256(plan, binding))
        selected_provider = (
            provider if provider is not None else project_source_workspace_provider(scope)
        )
        selected_storage = storage if storage is not None else storage_provider()
        db.rollback()
        with selected_provider.exclusive(scope):
            _check(db, owner, identity, token, renew=True, fence=fence)
            selected_provider.prepare(scope, files)
            copied_count, copied_bytes = 0, 0
            for reference, file in zip(references, files, strict=True):
                _, current_plan = _check(db, owner, identity, token, renew=True, fence=fence)
                key, attachment_id, asset_file_id = reference
                planned_file = policy.current_file(
                    db, current_plan, key, file, attachment_id, asset_file_id
                )
                file_attempt = file, key, scope
                receipt = selected_provider.inspect(scope, file)
                if receipt is None:
                    attachment = db.scalar(
                        select(Attachment)
                        .where(
                            Attachment.id == planned_file.attachment_id,
                            Attachment.user_id == owner,
                            Attachment.deleted_at.is_(None),
                        )
                        .execution_options(populate_existing=True)
                    )
                    if (
                        attachment is None
                        or attachment.storage_provider != selected_storage.provider_key
                        or (attachment.sha256, attachment.size_bytes)
                        != (file.sha256, file.size_bytes)
                    ):
                        raise _error("PROJECT_SOURCE_STORAGE_CHANGED")
                    reader = await selected_storage.open(attachment.object_key)
                    try:
                        if reader.size_bytes != file.size_bytes:
                            raise _error("PROJECT_SOURCE_STORAGE_CHANGED")
                        _check(db, owner, identity, token, renew=True, fence=fence)
                        db.rollback()
                        receipt = await _await_copy(
                            selected_provider.copy(scope, file, reader.iter_bytes()),
                            db,
                            owner,
                            identity,
                            token,
                            selected_provider,
                            scope,
                            file,
                            fence,
                        )
                    finally:
                        await reader.close()
                checkpoint = _checkpoint(
                    db,
                    owner,
                    identity,
                    token,
                    scope,
                    key,
                    file,
                    receipt,
                    fence,
                    attachment_id,
                    asset_file_id,
                )
                file_attempt = None
                if checkpoint.status == "QUARANTINED":
                    raise _error()
                copied_count += 1
                copied_bytes += receipt.size_bytes
                current, _ = _check(db, owner, identity, token, fence=fence)
                current.copied_files, current.copied_bytes = copied_count, copied_bytes
                db.commit()
            _check(db, owner, identity, token, renew=True)
            manifest = selected_provider.finalize(scope, files)
            if tuple((row.path, row.sha256, row.size_bytes) for row in manifest.files) != tuple(
                (file.path, file.sha256, file.size_bytes)
                for file in sorted(files, key=lambda file: file.path)
            ):
                raise _error("PROJECT_SOURCE_RECEIPT_INVALID")
            if (
                manifest.relative_path != scope.relative_path + "/" + PROJECT_SOURCE_MANIFEST_NAME
                or not re.fullmatch(r"[a-f0-9]{64}", manifest.manifest_sha256)
            ):
                raise _error("PROJECT_SOURCE_RECEIPT_INVALID")
            observed_manifest = manifest
            current, _ = _check(db, owner, identity, token)
            current.receipt_sha256, current.receipt_path, current.verified_at = (
                manifest.manifest_sha256,
                manifest.relative_path,
                now(),
            )
            _terminal(current, "COMPLETED")
            policy.event(db, current, "COMPLETED")
            db.commit()
    except Exception as error:
        db.rollback()
        failed_job = _job(db, owner, identity, lock=True)
        if failed_job is not None and observed_manifest is not None:
            db.add(
                ResearchEvent(
                    event_id=uuid.uuid4(),
                    user_id=owner,
                    event_type="project.source.manifest_quarantined",
                    occurred_at=now(),
                    source="project-source-worker",
                    correlation_id=identity,
                    payload={
                        "job_id": str(identity),
                        "plan_id": str(failed_job.plan_id),
                        "project_id": str(failed_job.project_id),
                        "status": failed_job.status,
                        "receipt_sha256": observed_manifest.manifest_sha256,
                        "receipt_path": observed_manifest.relative_path,
                        "disposition": "QUARANTINED",
                    },
                )
            )
        if failed_job is not None and failed_job.lease_token == token:
            if (
                file_attempt is not None
                and isinstance(error, DomainError)
                and error.code != "PROJECT_SOURCE_COPY_OUTCOME_UNKNOWN"
            ):
                attempted_file, attempted_key, attempted_scope = file_attempt
                db.add(
                    ProjectSourceFile(
                        id=uuid.uuid4(),
                        user_id=owner,
                        project_id=attempted_scope.project_id,
                        job_id=identity,
                        plan_id=attempted_scope.plan_id,
                        file_key_sha256=attempted_key,
                        status="FAILED",
                        relative_path=attempted_scope.relative_path + "/" + attempted_file.path,
                        error_code=error.code,
                    )
                )
            _terminal(
                failed_job,
                "NEEDS_ATTENTION"
                if not isinstance(error, DomainError)
                or error.code == "PROJECT_SOURCE_COPY_OUTCOME_UNKNOWN"
                else "CANCELLED"
                if failed_job.status == "CANCEL_REQUESTED"
                else "FAILED",
                error.code if isinstance(error, DomainError) else "PROJECT_SOURCE_COPY_FAILED",
            )
            policy.event(db, failed_job, failed_job.status, failed_job.error_code)
            db.commit()
        else:
            if observed_manifest is not None and failed_job is not None:
                db.commit()  # Keep actual late receipt without changing a foreign claim.
            else:
                db.rollback()
    return _job(db, owner, identity)
