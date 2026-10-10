"""Authenticated internal evidence materials; preview does not save or run AI."""

import hashlib
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.attachment_download import _byte_range
from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.models import Attachment
from app.models_evidence_bundles import EvidenceBundle
from app.providers import registry
from app.schemas import PageMeta
from app.schemas_evidence_bundles import (
    EvidenceBundleCreate,
    EvidenceBundleOut,
    EvidenceBundlePage,
    EvidenceBundlePreview,
    EvidenceBundleRetry,
    EvidenceBundleSelection,
    EvidenceBundleSummary,
)
from app.services import evidence_bundles as service
from app.services.common import cursor_filter, encode_cursor
from app.services.projects import get_project

router = APIRouter(prefix="/projects/{project_id}/evidence-bundles", tags=["evidence-bundles"])


@router.post("/preview", response_model=EvidenceBundlePreview)
def preview(
    project_id: uuid.UUID,
    body: EvidenceBundleSelection,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> EvidenceBundlePreview:
    return service.preview(db, context.user.id, project_id, body)[0]


@router.post("", response_model=EvidenceBundleOut, status_code=201)
async def create(
    project_id: uuid.UUID,
    body: EvidenceBundleCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> EvidenceBundleOut:
    return service.out(db, await service.create(db, context.user.id, project_id, body))


@router.get("", response_model=EvidenceBundlePage)
def list_bundles(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> EvidenceBundlePage:
    get_project(db, context.user.id, project_id)
    rows = list(
        db.scalars(
            select(EvidenceBundle)
            .where(
                EvidenceBundle.user_id == context.user.id,
                EvidenceBundle.project_id == project_id,
                cursor_filter(EvidenceBundle, cursor),
            )
            .order_by(EvidenceBundle.created_at.desc(), EvidenceBundle.id.desc())
            .limit(limit + 1)
        )
    )
    return EvidenceBundlePage(
        items=[EvidenceBundleSummary.model_validate(row) for row in rows[:limit]],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None,
        ),
    )


@router.get("/lookup", response_model=EvidenceBundleOut)
def lookup(
    project_id: uuid.UUID,
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> EvidenceBundleOut:
    get_project(db, context.user.id, project_id)
    row = db.scalar(
        select(EvidenceBundle).where(
            EvidenceBundle.user_id == context.user.id,
            EvidenceBundle.project_id == project_id,
            EvidenceBundle.idempotency_key == key,
        )
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Evidence creation not found", 404)
    return service.out(db, row)


@router.get("/{bundle_id}", response_model=EvidenceBundleOut)
def detail(
    project_id: uuid.UUID,
    bundle_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> EvidenceBundleOut:
    return service.out(db, service.get(db, context.user.id, project_id, bundle_id))


@router.post("/{bundle_id}/retry-save", response_model=EvidenceBundleOut)
async def retry(
    project_id: uuid.UUID,
    bundle_id: uuid.UUID,
    body: EvidenceBundleRetry,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> EvidenceBundleOut:
    return service.out(db, await service.retry(db, context.user.id, project_id, bundle_id, body))


@router.get("/{bundle_id}/download", response_class=Response)
async def download(
    project_id: uuid.UUID,
    bundle_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> Response:
    row = service.get(db, context.user.id, project_id, bundle_id)
    if row.status != "READY" or row.attachment_id is None or not service.intact(db, row):
        raise DomainError("EVIDENCE_NOT_READY", "A verified stored ZIP is required", 409)
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == row.attachment_id,
            Attachment.user_id == context.user.id,
            Attachment.deleted_at.is_(None),
            Attachment.sha256 == row.bundle_sha256,
            Attachment.size_bytes == row.bundle_size_bytes,
            Attachment.mime_type == "application/zip",
        )
    )
    if attachment is None:
        raise DomainError("EVIDENCE_NOT_READY", "Actual evidence attachment is unavailable", 409)
    provider = registry.storage_provider(attachment.storage_provider)
    db.rollback()
    reader = await provider.open(attachment.object_key)
    try:
        raw = bytearray()
        async for part in reader.iter_bytes():
            if len(raw) + len(part) > attachment.size_bytes:
                raise DomainError(
                    "EVIDENCE_BYTES_CHANGED", "Evidence ZIP exceeds its original byte count", 409
                )
            raw.extend(part)
    finally:
        await reader.close()
    if len(raw) != attachment.size_bytes or hashlib.sha256(raw).hexdigest() != attachment.sha256:
        raise DomainError("EVIDENCE_BYTES_CHANGED", "Original evidence ZIP hash changed", 409)
    etag = '"' + attachment.sha256 + '"'
    headers = {
        "ETag": etag,
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'attachment; filename="evidence-{bundle_id}.zip"',
    }
    requested = (
        request.headers.get("range") if request.headers.get("if-range") in {None, etag} else None
    )
    byte_range = _byte_range(requested, len(raw))
    if byte_range:
        start, end = byte_range
        headers["Content-Range"] = f"bytes {start}-{end - 1}/{len(raw)}"
        return Response(
            bytes(raw[start:end]), status_code=206, media_type="application/zip", headers=headers
        )
    return Response(bytes(raw), media_type="application/zip", headers=headers)
