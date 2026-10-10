"""Zotero incremental sync endpoints; no Zotero write operation is exposed."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.core.config import get_settings
from app.db import get_db
from app.domain.reference_manager import IncrementalReferenceManagerProvider
from app.errors import DomainError
from app.models import (
    ZoteroManualSyncCandidate,
    ZoteroManualSyncItem,
    ZoteroManualSyncJob,
    ZoteroSyncCursor,
)
from app.providers.registry import reference_manager
from app.services.zotero_manual_sync import (
    cancel_manual_sync,
    enqueue_manual_sync,
    get_job,
    retry_manual_sync,
)

router = APIRouter(prefix="/reference-managers/zotero/sync", tags=["reference-managers"])


class SyncRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    full_library: bool = False


class SyncJobOut(BaseModel):
    job_id: uuid.UUID
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"]
    job_type: Literal["SINGLE_ITEM", "INCREMENTAL", "FULL_LIBRARY"]
    provider_key: str
    server_id: str
    library_type: str
    library_id: str
    item_key: str | None
    cursor_before: str | None
    cursor_after: str | None
    scanned: int
    created: int
    updated: int
    skipped: int
    failed: int
    total_items: int
    attempt_count: int
    error_code: str | None
    error_message: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    heartbeat_at: datetime | None


class SyncItemOut(BaseModel):
    id: uuid.UUID
    item_key: str
    item_version: int
    status: Literal["PENDING", "CREATED", "UPDATED", "SKIPPED", "FAILED"]
    paper_id: uuid.UUID | None
    content_changed: bool
    content_change_unknown: bool
    error_code: str | None
    error_message: str | None
    candidate_paper_ids: list[uuid.UUID]


class SyncJobPage(BaseModel):
    items: list[SyncJobOut]
    total: int
    limit: int
    offset: int


class SyncItemPage(BaseModel):
    items: list[SyncItemOut]
    total: int
    limit: int
    offset: int


def _out(job: ZoteroManualSyncJob) -> SyncJobOut:
    return SyncJobOut.model_validate(
        {
            "job_id": job.id,
            "status": job.status,
            "job_type": job.job_type,
            "provider_key": job.provider_key,
            "server_id": job.server_id,
            "library_type": job.library_type,
            "library_id": job.library_id,
            "item_key": job.item_key,
            "cursor_before": job.cursor_before,
            "cursor_after": job.cursor_after,
            "scanned": job.scanned_count,
            "created": job.created_count,
            "updated": job.updated_count,
            "skipped": job.skipped_count,
            "failed": job.failed_count,
            "total_items": job.total_items,
            "attempt_count": job.attempt_count,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "queued_at": job.queued_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "heartbeat_at": job.heartbeat_at,
        }
    )


@router.get("/capabilities")
async def capabilities(
    context: AuthContext = Depends(current_context),
) -> dict[str, str | bool | None]:
    if get_settings().zotero_mode == "disabled":
        return {
            "connected": False,
            "mode": "disabled",
            "provider_key": "zotero_local",
            "can_read": False,
            "can_download_attachments": False,
            "can_write": False,
            "incremental_sync": False,
        }
    try:
        provider = reference_manager()
        status = await provider.status()
        return {
            **status,
            "can_read": True,
            "can_download_attachments": bool(status.get("can_download_attachments", True)),
            "can_write": False,
            "incremental_sync": isinstance(provider, IncrementalReferenceManagerProvider),
        }
    except DomainError as exc:
        return {
            "connected": False,
            "mode": get_settings().zotero_mode,
            "provider_key": "zotero_local"
            if get_settings().zotero_mode == "local"
            else "zotero_web",
            "can_read": False,
            "can_download_attachments": False,
            "can_write": False,
            "incremental_sync": False,
            "error": exc.message,
        }


@router.get("/cursor")
async def cursor(
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dict[str, str | None]:
    if get_settings().zotero_mode == "disabled":
        return {"cursor": None, "last_success_at": None, "last_error": None}
    status = await reference_manager().status()
    server_id = status.get("server_id")
    library_type = status.get("library_type") or "user"
    library_id = status.get("library_id") or "0"
    if not isinstance(server_id, str) or not server_id:
        raise DomainError("PROVIDER_UNAVAILABLE", "Zotero instance ID is unavailable", 503)
    record = db.scalar(
        select(ZoteroSyncCursor).where(
            ZoteroSyncCursor.user_id == context.user.id,
            ZoteroSyncCursor.server_id == server_id,
            ZoteroSyncCursor.library_type == library_type,
            ZoteroSyncCursor.library_id == library_id,
        )
    )
    if record is None:
        return {"cursor": None, "last_success_at": None, "last_error": None}
    return {
        "cursor": record.cursor,
        "last_success_at": record.last_success_at.isoformat() if record.last_success_at else None,
        "last_error": record.last_error,
    }


@router.get("/jobs", response_model=SyncJobPage)
def jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> SyncJobPage:
    scope = ZoteroManualSyncJob.user_id == context.user.id
    records = db.scalars(
        select(ZoteroManualSyncJob)
        .where(scope)
        .order_by(
            ZoteroManualSyncJob.queued_at.desc(),
            ZoteroManualSyncJob.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    total = db.scalar(select(func.count()).select_from(ZoteroManualSyncJob).where(scope)) or 0
    return SyncJobPage(
        items=[_out(record) for record in records], total=total, limit=limit, offset=offset
    )


@router.get("/jobs/{job_id}", response_model=SyncJobOut)
def job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> SyncJobOut:
    return _out(get_job(db, context.user.id, job_id))


@router.get("/jobs/{job_id}/items", response_model=SyncItemPage)
def job_items(
    job_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Literal["PENDING", "CREATED", "UPDATED", "SKIPPED", "FAILED"] | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> SyncItemPage:
    get_job(db, context.user.id, job_id)
    scope = [ZoteroManualSyncItem.job_id == job_id, ZoteroManualSyncItem.user_id == context.user.id]
    if status is not None:
        scope.append(ZoteroManualSyncItem.status == status)
    records = list(
        db.scalars(
            select(ZoteroManualSyncItem)
            .where(*scope)
            .order_by(
                ZoteroManualSyncItem.item_key,
                ZoteroManualSyncItem.id,
            )
            .limit(limit)
            .offset(offset)
        )
    )
    candidates: dict[uuid.UUID, list[uuid.UUID]] = {}
    if records:
        for item_id, paper_id in db.execute(
            select(ZoteroManualSyncCandidate.item_id, ZoteroManualSyncCandidate.paper_id)
            .where(
                ZoteroManualSyncCandidate.user_id == context.user.id,
                ZoteroManualSyncCandidate.item_id.in_([record.id for record in records]),
            )
            .order_by(ZoteroManualSyncCandidate.paper_id)
        ):
            candidates.setdefault(item_id, []).append(paper_id)
    total = db.scalar(select(func.count()).select_from(ZoteroManualSyncItem).where(*scope)) or 0
    return SyncItemPage(
        items=[
            SyncItemOut.model_validate(
                {
                    "id": record.id,
                    "item_key": record.item_key,
                    "item_version": record.item_version,
                    "status": record.status,
                    "paper_id": record.paper_id,
                    "content_changed": record.content_changed,
                    "content_change_unknown": record.content_change_unknown,
                    "error_code": record.error_code,
                    "error_message": record.error_message,
                    "candidate_paper_ids": candidates.get(record.id, []),
                }
            )
            for record in records
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/jobs/{job_id}/retry", response_model=SyncJobOut)
def retry_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> SyncJobOut:
    return _out(retry_manual_sync(db, context.user.id, job_id))


@router.post("/jobs/{job_id}/cancel", response_model=SyncJobOut)
def cancel_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> SyncJobOut:
    return _out(cancel_manual_sync(db, context.user.id, job_id))


@router.post("", response_model=SyncJobOut, status_code=202)
async def sync_all(
    body: SyncRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> SyncJobOut:
    return _out(
        await enqueue_manual_sync(
            db,
            context.user.id,
            reference_manager(),
            idempotency_key=body.idempotency_key,
            full_library=body.full_library,
        )
    )


@router.post("/items/{item_key}", response_model=SyncJobOut, status_code=202)
async def sync_item(
    item_key: str,
    body: SyncRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> SyncJobOut:
    return _out(
        await enqueue_manual_sync(
            db,
            context.user.id,
            reference_manager(),
            item_key=item_key,
            idempotency_key=body.idempotency_key,
            full_library=body.full_library,
        )
    )
