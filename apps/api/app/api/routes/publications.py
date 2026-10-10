"""Owner-scoped human manuscript workspace; no AI or research execution."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.models_evidence_bundles import EvidenceBundle
from app.models_publications import Publication, PublicationReview, PublicationRevision
from app.schemas import PageMeta
from app.schemas_evidence_bundles import EvidenceBundlePage, EvidenceBundleSummary
from app.schemas_publications import (
    PublicationCreate,
    PublicationFields,
    PublicationOperationReceipt,
    PublicationOut,
    PublicationPage,
    PublicationPreview,
    PublicationReviewOut,
    PublicationReviewRequest,
    PublicationRevise,
    PublicationRevisionOut,
    PublicationRevisionPage,
    PublicationSummary,
)
from app.services import publications as service
from app.services.common import cursor_filter, encode_cursor
from app.services.projects import get_project

router = APIRouter(prefix="/projects/{project_id}/publications", tags=["publications"])


def page(rows: list[Any], limit: int) -> PageMeta:
    return PageMeta(
        limit=limit,
        next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
        if len(rows) > limit
        else None,
    )


@router.get("", response_model=PublicationPage)
def list_publications(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PublicationPage:
    get_project(db, context.user.id, project_id)
    rows = list(
        db.scalars(
            select(Publication)
            .where(
                Publication.project_id == project_id,
                Publication.user_id == context.user.id,
                cursor_filter(Publication, cursor),
            )
            .order_by(Publication.created_at.desc(), Publication.id.desc())
            .limit(limit + 1)
        )
    )
    return PublicationPage(
        items=[PublicationSummary.model_validate(r) for r in rows[:limit]], page=page(rows, limit)
    )


@router.get("/source-options", response_model=EvidenceBundlePage)
def source_options(
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
                EvidenceBundle.project_id == project_id,
                EvidenceBundle.user_id == context.user.id,
                EvidenceBundle.status == "READY",
                cursor_filter(EvidenceBundle, cursor),
            )
            .order_by(EvidenceBundle.created_at.desc(), EvidenceBundle.id.desc())
            .limit(limit + 1)
        )
    )
    return EvidenceBundlePage(
        items=[
            EvidenceBundleSummary.model_validate(r)
            for r in rows[:limit]
            if service.source_available(db, context.user.id, r)
        ],
        page=page(rows, limit),
    )


@router.post("/preview", response_model=PublicationPreview)
def preview(
    project_id: uuid.UUID,
    body: PublicationFields,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PublicationPreview:
    return service.preview(db, context.user.id, project_id, body)


@router.post("", response_model=PublicationOut, status_code=201)
def create(
    project_id: uuid.UUID,
    body: PublicationCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PublicationOut:
    return service.out(db, service.create(db, context.user.id, project_id, body))


@router.get("/lookup", response_model=PublicationOut)
def lookup(
    project_id: uuid.UUID,
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PublicationOut:
    row = service.lookup(db, context.user.id, project_id, key)
    result = service.out(db, row)
    original = db.scalar(
        select(PublicationRevision).where(
            PublicationRevision.publication_id == row.id,
            PublicationRevision.revision == 1,
            PublicationRevision.user_id == context.user.id,
        )
    )
    if original is None:
        raise service.fail("PUBLICATION_REVISION_INVALID", "Original capture receipt missing")
    result.operation_receipt = PublicationOperationReceipt(
        kind="create",
        request_sha256=row.create_sha256,
        revision_id=original.id,
        idempotency_key=key,
    )
    return result


@router.get("/{identity}", response_model=PublicationOut)
def get(
    project_id: uuid.UUID,
    identity: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PublicationOut:
    return service.out(db, service.get(db, context.user.id, project_id, identity))


@router.post("/{identity}/revisions", response_model=PublicationOut, status_code=201)
def revise(
    project_id: uuid.UUID,
    identity: uuid.UUID,
    body: PublicationRevise,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PublicationOut:
    return service.out(db, service.revise(db, context.user.id, project_id, identity, body))


@router.get("/{identity}/revisions", response_model=PublicationRevisionPage)
def revisions(
    project_id: uuid.UUID,
    identity: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PublicationRevisionPage:
    service.get(db, context.user.id, project_id, identity)
    rows = list(
        db.scalars(
            select(PublicationRevision)
            .where(
                PublicationRevision.publication_id == identity,
                PublicationRevision.user_id == context.user.id,
                cursor_filter(PublicationRevision, cursor),
            )
            .order_by(PublicationRevision.created_at.desc(), PublicationRevision.id.desc())
            .limit(limit + 1)
        )
    )
    return PublicationRevisionPage(
        items=[service.revision_out(db, r) for r in rows[:limit]], page=page(rows, limit)
    )


@router.get("/{identity}/revisions/{revision_id}", response_model=PublicationRevisionOut)
def revision(
    project_id: uuid.UUID,
    identity: uuid.UUID,
    revision_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PublicationRevisionOut:
    return service.revision_out(
        db,
        service.revision(db, service.get(db, context.user.id, project_id, identity), revision_id),
    )


@router.post("/{identity}/reviews", response_model=PublicationReviewOut, status_code=201)
def review(
    project_id: uuid.UUID,
    identity: uuid.UUID,
    body: PublicationReviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PublicationReviewOut:
    return PublicationReviewOut.model_validate(
        service.review(db, context.user.id, project_id, identity, body)
    )


@router.get("/{identity}/operations/lookup", response_model=PublicationOut)
def operation_lookup(
    project_id: uuid.UUID,
    identity: uuid.UUID,
    key: str = Query(min_length=1, max_length=120),
    kind: Literal["revision", "review"] = Query(...),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PublicationOut:
    row = service.get(db, context.user.id, project_id, identity)
    found: PublicationRevision | PublicationReview | None
    if kind == "revision":
        found = db.scalar(
            select(PublicationRevision).where(
                PublicationRevision.publication_id == identity,
                PublicationRevision.user_id == context.user.id,
                PublicationRevision.idempotency_key == key,
            )
        )
    else:
        found = db.scalar(
            select(PublicationReview).where(
                PublicationReview.publication_id == identity,
                PublicationReview.user_id == context.user.id,
                PublicationReview.idempotency_key == key,
            )
        )
    if found is None:
        raise service.fail("NOT_FOUND", "Owned publication operation not found", 404)
    result = service.out(db, row)
    result.operation_receipt = PublicationOperationReceipt(
        kind=kind,
        request_sha256=found.request_sha256,
        revision_id=found.id if isinstance(found, PublicationRevision) else found.revision_id,
        idempotency_key=key,
    )
    return result
