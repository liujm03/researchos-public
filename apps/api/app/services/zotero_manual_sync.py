"""Owner-triggered metadata synchronization with durable, fenced progress."""

import hashlib
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import cast

from pydantic import TypeAdapter
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.reference_manager import (
    IncrementalReferenceManagerProvider,
    ReferenceCollection,
    ReferenceItem,
    ReferenceManagerProvider,
)
from app.errors import DomainError
from app.models import (
    Paper,
    ZoteroCollection,
    ZoteroManualSyncCandidate,
    ZoteroManualSyncItem,
    ZoteroManualSyncJob,
    ZoteroSyncCursor,
)
from app.services.literature_ingest import _identity
from app.services.zotero_sync import (
    CHILD_TYPES,
    MAX_CHANGED_ROWS,
    PAGE_SIZE,
    _job_key,
    _sync_one,
    advance_cursor,
    safe_sync_error,
)

LEASE_DURATION = timedelta(minutes=2)
TERMINAL = {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}
ITEM_ADAPTER = TypeAdapter(ReferenceItem)
FULL_LIBRARY_MAX_ROWS = 50_000


class LeaseLost(Exception):
    """Another worker or an owner cancellation invalidated this execution."""


def get_job(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> ZoteroManualSyncJob:
    job = db.scalar(
        select(ZoteroManualSyncJob).where(
            ZoteroManualSyncJob.id == job_id,
            ZoteroManualSyncJob.user_id == user_id,
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Zotero sync job not found", 404)
    return job


async def enqueue_manual_sync(
    db: Session,
    user_id: uuid.UUID,
    provider: ReferenceManagerProvider,
    *,
    item_key: str | None = None,
    idempotency_key: str | None = None,
    full_library: bool = False,
) -> ZoteroManualSyncJob:
    if item_key is not None and full_library:
        raise DomainError("VALIDATION_ERROR", "Full-library scope cannot select a single item", 422)
    if provider.provider_key not in {"zotero_local", "zotero_web"}:
        raise DomainError("CAPABILITY_UNAVAILABLE", "Unsupported Zotero provider", 501)
    if item_key is None and not isinstance(provider, IncrementalReferenceManagerProvider):
        raise DomainError("CAPABILITY_UNAVAILABLE", "Zotero incremental sync is unavailable", 501)
    server_id, library_type, library_id = await _identity(provider)
    key = _job_key(
        idempotency_key, item_key, provider.provider_key, server_id, library_type, library_id
    )
    if key is not None and full_library:
        # Preserve historical incremental keys, while keeping full reconciliation
        # distinct even when a browser reuses the same client request key.
        key = hashlib.sha256(f"full-library:{key}".encode()).hexdigest()
    if key:
        previous = db.scalar(
            select(ZoteroManualSyncJob).where(
                ZoteroManualSyncJob.user_id == user_id,
                ZoteroManualSyncJob.idempotency_key == key,
            )
        )
        if previous is not None:
            return previous
    job = ZoteroManualSyncJob(
        user_id=user_id,
        provider_key=provider.provider_key,
        server_id=server_id,
        library_type=library_type,
        library_id=library_id,
        item_key=item_key,
        job_type="SINGLE_ITEM" if item_key else "FULL_LIBRARY" if full_library else "INCREMENTAL",
        status="QUEUED",
        idempotency_key=key,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if key is None:
            raise
        previous = db.scalar(
            select(ZoteroManualSyncJob).where(
                ZoteroManualSyncJob.user_id == user_id,
                ZoteroManualSyncJob.idempotency_key == key,
            )
        )
        if previous is None:
            raise
        return previous
    return job


def recover_stale_manual_sync_jobs(db: Session) -> int:
    now = datetime.now(UTC)
    recovered = list(
        db.scalars(
            update(ZoteroManualSyncJob)
            .where(
                ZoteroManualSyncJob.status == "RUNNING",
                ZoteroManualSyncJob.lease_expires_at <= now,
            )
            .values(
                status="QUEUED",
                lease_token=None,
                lease_expires_at=None,
                error_code="LEASE_EXPIRED",
                error_message="Previous worker lease expired; resuming durable results",
            )
            .returning(ZoteroManualSyncJob.id)
            .execution_options(synchronize_session=False)
        )
    )
    db.commit()
    return len(recovered)


def claim_next_manual_sync_job(db: Session) -> ZoteroManualSyncJob | None:
    candidate = db.scalar(
        select(ZoteroManualSyncJob)
        .where(
            ZoteroManualSyncJob.status == "QUEUED",
        )
        .order_by(ZoteroManualSyncJob.queued_at, ZoteroManualSyncJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if candidate is None:
        db.rollback()
        return None
    now = datetime.now(UTC)
    claimed = db.scalar(
        update(ZoteroManualSyncJob)
        .where(
            ZoteroManualSyncJob.id == candidate.id,
            ZoteroManualSyncJob.status == "QUEUED",
        )
        .values(
            status="RUNNING",
            lease_token=str(uuid.uuid4()),
            lease_expires_at=now + LEASE_DURATION,
            heartbeat_at=now,
            started_at=now,
            completed_at=None,
            attempt_count=ZoteroManualSyncJob.attempt_count + 1,
            error_code=None,
            error_message=None,
        )
        .returning(ZoteroManualSyncJob.id)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if claimed is None:
        return None
    db.refresh(candidate)
    return candidate


def _fence(db: Session, job_id: uuid.UUID, token: str) -> ZoteroManualSyncJob:
    now = datetime.now(UTC)
    retained = db.scalar(
        update(ZoteroManualSyncJob)
        .where(
            ZoteroManualSyncJob.id == job_id,
            ZoteroManualSyncJob.status == "RUNNING",
            ZoteroManualSyncJob.lease_token == token,
            ZoteroManualSyncJob.lease_expires_at > now,
        )
        .values(heartbeat_at=now, lease_expires_at=now + LEASE_DURATION)
        .returning(ZoteroManualSyncJob.id)
        .execution_options(synchronize_session=False)
    )
    if retained is None:
        db.rollback()
        raise LeaseLost
    # The runtime disables autoflush. Preserve pending progress only after the
    # lease update has locked and verified the job, before refresh discards it.
    db.flush()
    job = db.get(ZoteroManualSyncJob, job_id)
    assert job is not None
    db.refresh(job)
    return job


async def _call[T](db: Session, job_id: uuid.UUID, token: str, operation: Awaitable[T]) -> T:
    try:
        _fence(db, job_id, token)
        db.commit()
    except Exception:
        # Do not leave an unawaited provider coroutine on a lost lease.
        if hasattr(operation, "close"):
            operation.close()
        raise
    result = await operation
    _fence(db, job_id, token)
    db.commit()
    return result


async def _check_identity(
    db: Session,
    job: ZoteroManualSyncJob,
    token: str,
    provider: ReferenceManagerProvider,
) -> None:
    identity = await _call(db, job.id, token, _identity(provider))
    if provider.provider_key != job.provider_key or identity != (
        job.server_id,
        job.library_type,
        job.library_id,
    ):
        raise DomainError(
            "SOURCE_CHANGED",
            "Configured Zotero provider or library differs from this queued job",
            409,
        )


def _recount(db: Session, job: ZoteroManualSyncJob) -> None:
    db.flush()
    counts = dict(
        db.execute(
            select(ZoteroManualSyncItem.status, func.count())
            .where(
                ZoteroManualSyncItem.job_id == job.id,
                ZoteroManualSyncItem.user_id == job.user_id,
            )
            .group_by(ZoteroManualSyncItem.status)
        ).all()
    )
    job.created_count = counts.get("CREATED", 0)
    job.updated_count = counts.get("UPDATED", 0)
    job.skipped_count = counts.get("SKIPPED", 0)
    job.failed_count = counts.get("FAILED", 0)
    job.scanned_count = job.created_count + job.updated_count + job.skipped_count + job.failed_count
    job.total_items = sum(counts.values())


async def _discover(
    db: Session,
    job: ZoteroManualSyncJob,
    token: str,
    provider: ReferenceManagerProvider,
) -> None:
    cursor = db.scalar(
        select(ZoteroSyncCursor).where(
            ZoteroSyncCursor.user_id == job.user_id,
            ZoteroSyncCursor.server_id == job.server_id,
            ZoteroSyncCursor.library_type == job.library_type,
            ZoteroSyncCursor.library_id == job.library_id,
        )
    )
    before = job.cursor_before if job.attempt_count > 1 else cursor.cursor if cursor else None
    since = None if job.job_type == "FULL_LIBRARY" else int(before) if before else None
    max_rows = FULL_LIBRARY_MAX_ROWS if job.job_type == "FULL_LIBRARY" else MAX_CHANGED_ROWS
    job = _fence(db, job.id, token)
    job.cursor_before = before
    db.commit()
    items: dict[str, ReferenceItem] = {}
    parents: set[str] = set()
    collections: list[ReferenceCollection] = []
    snapshot = None
    if job.item_key:
        item = await _call(db, job.id, token, provider.get_item(job.item_key))
        if item is None or item.item_type in CHILD_TYPES:
            raise DomainError("NOT_FOUND", "Zotero paper item not found", 404)
        items[item.key] = item
    else:
        if not isinstance(provider, IncrementalReferenceManagerProvider):
            raise DomainError(
                "CAPABILITY_UNAVAILABLE", "Zotero incremental sync is unavailable", 501
            )
        start = 0
        while True:
            page = await _call(
                db, job.id, token, provider.list_updated_items(since, PAGE_SIZE, start)
            )
            if page.library_version is None:
                raise DomainError(
                    "PROVIDER_UNAVAILABLE", "Zotero library version is unavailable", 503
                )
            if snapshot is not None and snapshot != page.library_version:
                raise DomainError(
                    "LIBRARY_CHANGED", "Zotero changed during pagination; retry this job", 409
                )
            snapshot = page.library_version
            items.update(
                (item.key, item)
                for item in page.items
                if item.version <= snapshot and item.item_type not in CHILD_TYPES
            )
            parents.update(page.changed_parent_keys)
            start += page.raw_count
            if start > max_rows:
                raise DomainError(
                    "SYNC_LIMIT",
                    f"Zotero scan exceeds {max_rows} source rows; library is not fully synchronized",
                    409,
                )
            if page.raw_count < PAGE_SIZE:
                break
        for parent_key in sorted(parents - items.keys()):
            parent = await _call(db, job.id, token, provider.get_item(parent_key))
            if parent is not None and parent.item_type not in CHILD_TYPES:
                items[parent.key] = parent
        start = 0
        while True:
            page_collections = await _call(
                db, job.id, token, provider.list_collections(PAGE_SIZE, start)
            )
            collections.extend(page_collections)
            start += len(page_collections)
            if start > max_rows:
                raise DomainError(
                    "SYNC_LIMIT",
                    f"Zotero scan exceeds {max_rows} collections; library is not fully synchronized",
                    409,
                )
            if len(page_collections) < PAGE_SIZE:
                break
    await _check_identity(db, job, token, provider)
    job = _fence(db, job.id, token)
    for item in items.values():
        row = db.scalar(
            select(ZoteroManualSyncItem).where(
                ZoteroManualSyncItem.job_id == job.id,
                ZoteroManualSyncItem.item_key == item.key,
            )
        )
        if row is None:
            row = ZoteroManualSyncItem(
                user_id=job.user_id,
                job_id=job.id,
                item_key=item.key,
                item_version=item.version,
                status="PENDING",
                source_payload={},
            )
            db.add(row)
        elif row.item_version != item.version:
            row.status = "PENDING"
            row.paper_id = None
            row.error_code = row.error_message = None
            row.content_changed = row.content_change_unknown = False
            db.execute(
                delete(ZoteroManualSyncCandidate).where(ZoteroManualSyncCandidate.item_id == row.id)
            )
        row.item_version = item.version
        row.source_payload = cast(dict[str, object], ITEM_ADAPTER.dump_python(item, mode="json"))
        row.attachment_changed = item.key in parents
    for record in collections:
        collection = db.scalar(
            select(ZoteroCollection).where(
                ZoteroCollection.user_id == job.user_id,
                ZoteroCollection.server_id == job.server_id,
                ZoteroCollection.library_type == job.library_type,
                ZoteroCollection.library_id == job.library_id,
                ZoteroCollection.collection_key == record.key,
            )
        )
        if collection is None:
            collection = ZoteroCollection(
                user_id=job.user_id,
                server_id=job.server_id,
                library_type=job.library_type,
                library_id=job.library_id,
                collection_key=record.key,
                name=record.name,
            )
            db.add(collection)
        collection.name = record.name
        collection.parent_collection_key = record.parent_key
        collection.last_synced_at = datetime.now(UTC)
    job.cursor_before = before
    job.snapshot_version = snapshot
    job.discovery_complete = True
    db.flush()
    _recount(db, job)
    _fence(db, job.id, token)
    db.commit()


def _store_item_failure(
    db: Session, job: ZoteroManualSyncJob, row: ZoteroManualSyncItem, exc: Exception
) -> None:
    row.status = "FAILED"
    row.error_code = exc.code if isinstance(exc, DomainError) else "ITEM_SYNC_FAILED"
    row.error_message = safe_sync_error(exc)[:4000]
    row.completed_at = datetime.now(UTC)
    if isinstance(exc, DomainError) and isinstance(exc.details, dict):
        candidates = exc.details.get("candidate_paper_ids") or [
            exc.details.get("candidate_paper_id")
        ]
        if isinstance(candidates, list):
            for value in candidates:
                try:
                    paper_id = uuid.UUID(str(value))
                except ValueError:
                    continue
                if db.scalar(
                    select(Paper.id).where(Paper.id == paper_id, Paper.user_id == job.user_id)
                ):
                    db.add(
                        ZoteroManualSyncCandidate(
                            item_id=row.id, user_id=job.user_id, paper_id=paper_id
                        )
                    )
    job.failed_count += 1
    job.scanned_count += 1


async def process_manual_sync_job(
    db: Session,
    job_id: uuid.UUID,
    token: str,
    provider: ReferenceManagerProvider | None,
) -> ZoteroManualSyncJob:
    job = db.get(ZoteroManualSyncJob, job_id)
    assert job is not None
    try:
        if provider is None:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Zotero provider is disabled or unavailable", 503
            )
        await _check_identity(db, job, token, provider)
        if not job.discovery_complete:
            await _discover(db, job, token, provider)
        pending_ids = list(
            db.scalars(
                select(ZoteroManualSyncItem.id)
                .where(
                    ZoteroManualSyncItem.job_id == job.id,
                    ZoteroManualSyncItem.status == "PENDING",
                )
                .order_by(ZoteroManualSyncItem.item_key)
            )
        )
        db.commit()
        for row_id in pending_ids:
            row = db.get(ZoteroManualSyncItem, row_id)
            assert row is not None
            item = ITEM_ADAPTER.validate_python(row.source_payload)
            db.commit()
            try:
                await _check_identity(db, job, token, provider)
                attachments = await _call(db, job.id, token, provider.list_attachments(item.key))
                await _check_identity(db, job, token, provider)
                job = _fence(db, job.id, token)
                with db.begin_nested():
                    outcome, paper_id, changed, unknown = await _sync_one(
                        db,
                        job.user_id,
                        job.server_id,
                        job.library_type,
                        job.library_id,
                        item,
                        provider,
                        check_attachment=True,
                        indexed_attachments=attachments,
                        attachment_changed_hint=row.attachment_changed,
                    )
                    row.status = outcome.upper()
                    row.paper_id = paper_id
                    row.content_changed = changed
                    row.content_change_unknown = unknown
                    row.completed_at = datetime.now(UTC)
                job.scanned_count += 1
                if outcome == "created":
                    job.created_count += 1
                elif outcome == "updated":
                    job.updated_count += 1
                else:
                    job.skipped_count += 1
                _fence(db, job.id, token)
                db.commit()
            except LeaseLost:
                raise
            except Exception as exc:
                db.rollback()
                job = _fence(db, job.id, token)
                row = db.get(ZoteroManualSyncItem, row_id)
                assert row is not None
                _store_item_failure(db, job, row, exc)
                _fence(db, job.id, token)
                db.commit()
                if isinstance(exc, DomainError) and exc.code == "SOURCE_CHANGED":
                    raise
        if not job.failed_count and job.snapshot_version is not None:
            assert isinstance(provider, IncrementalReferenceManagerProvider)
            await _check_identity(db, job, token, provider)
            observed = await _call(
                db, job.id, token, provider.list_updated_items(job.snapshot_version, 1, 0)
            )
            if observed.library_version != job.snapshot_version:
                raise DomainError(
                    "LIBRARY_CHANGED", "Zotero changed during sync; retry this job", 409
                )
        job = _fence(db, job.id, token)
        if job.failed_count:
            job.error_code = "ITEM_SYNC_FAILED"
            job.error_message = f"{job.failed_count} Zotero item(s) failed; cursor retained"
        elif job.snapshot_version is not None:
            job.cursor_after = advance_cursor(
                db,
                job.user_id,
                job.server_id,
                job.library_type,
                job.library_id,
                job.snapshot_version,
            )
        job = _fence(db, job.id, token)
        job.status = "PARTIAL" if job.failed_count else "COMPLETED"
        job.completed_at = datetime.now(UTC)
        job.lease_token = None
        job.lease_expires_at = None
        db.commit()
    except LeaseLost:
        db.rollback()
        db.expire_all()
    except Exception as exc:
        db.rollback()
        try:
            job = _fence(db, job.id, token)
            job.status = "FAILED"
            job.error_code = exc.code if isinstance(exc, DomainError) else "SYNC_FAILED"
            job.error_message = safe_sync_error(exc)[:4000]
            job.completed_at = datetime.now(UTC)
            job.lease_token = None
            job.lease_expires_at = None
            db.commit()
        except LeaseLost:
            db.rollback()
    db.refresh(job)
    return job


async def process_next_manual_sync_job(
    db: Session, provider: ReferenceManagerProvider | None
) -> ZoteroManualSyncJob | None:
    recover_stale_manual_sync_jobs(db)
    job = claim_next_manual_sync_job(db)
    if job is None:
        return None
    assert job.lease_token is not None
    return await process_manual_sync_job(db, job.id, job.lease_token, provider)


def cancel_manual_sync(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> ZoteroManualSyncJob:
    job = get_job(db, user_id, job_id)
    db.execute(
        update(ZoteroManualSyncJob)
        .where(
            ZoteroManualSyncJob.id == job.id,
            ZoteroManualSyncJob.user_id == user_id,
            ZoteroManualSyncJob.status.in_(["QUEUED", "RUNNING"]),
        )
        .values(
            status="CANCELLED",
            lease_token=None,
            lease_expires_at=None,
            completed_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(job)
    return job


def retry_manual_sync(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> ZoteroManualSyncJob:
    get_job(db, user_id, job_id)
    job = db.scalar(
        select(ZoteroManualSyncJob)
        .where(
            ZoteroManualSyncJob.id == job_id,
            ZoteroManualSyncJob.user_id == user_id,
        )
        .with_for_update()
    )
    assert job is not None
    db.refresh(job)
    if job.status not in {"PARTIAL", "FAILED", "CANCELLED"}:
        raise DomainError(
            "INVALID_STATE", "Only failed, partial or cancelled sync jobs can retry", 409
        )
    db.execute(
        delete(ZoteroManualSyncCandidate).where(
            ZoteroManualSyncCandidate.item_id.in_(
                select(ZoteroManualSyncItem.id).where(
                    ZoteroManualSyncItem.job_id == job.id, ZoteroManualSyncItem.status == "FAILED"
                )
            ),
        )
    )
    db.execute(
        update(ZoteroManualSyncItem)
        .where(
            ZoteroManualSyncItem.job_id == job.id,
            ZoteroManualSyncItem.status == "FAILED",
        )
        .values(status="PENDING", error_code=None, error_message=None, completed_at=None)
    )
    if job.error_code == "LIBRARY_CHANGED":
        job.discovery_complete = False
        job.snapshot_version = None
    job.status = "QUEUED"
    job.error_code = job.error_message = None
    job.completed_at = None
    job.lease_token = None
    job.lease_expires_at = None
    _recount(db, job)
    db.commit()
    return job
