"""Explicit professional writing approval and immutable candidate adoption."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.models_writing import WritingOperation, WritingPlan
from app.schemas import PageMeta
from app.schemas_publications import PublicationPreview
from app.schemas_writing import (
    WritingAdopt,
    WritingAdoptionSelection,
    WritingCreate,
    WritingImport,
    WritingIssueCreate,
    WritingOperationReceipt,
    WritingOptions,
    WritingPlanOut,
    WritingPlanPage,
    WritingPlanSummary,
    WritingPreview,
    WritingSelection,
    WritingStart,
)
from app.services import publications
from app.services import writing as service
from app.services.common import cursor_filter, encode_cursor

router = APIRouter(
    prefix="/projects/{project_id}/publications/{publication_id}/writing-plans", tags=["writing"]
)


def receipt_out(
    db: Session,
    row: WritingPlan,
    kind: Literal["create", "start", "import", "adopt", "issue"],
    key: str,
) -> WritingPlanOut:
    result = service.detail(db, row)
    if kind == "create":
        result.operation_receipt = WritingOperationReceipt(
            kind=kind, request_sha256=row.create_sha256, idempotency_key=key
        )
    else:
        receipt = db.scalar(
            select(WritingOperation).where(
                WritingOperation.plan_id == row.id,
                WritingOperation.user_id == row.user_id,
                WritingOperation.kind == kind,
                WritingOperation.idempotency_key == key,
            )
        )
        if receipt is None:
            raise service.fail(
                "WRITING_RECEIPT_UNAVAILABLE", "Committed writing operation receipt missing"
            )
        result.operation_receipt = WritingOperationReceipt(
            kind=kind, request_sha256=receipt.request_sha256, idempotency_key=key
        )
    return result


@router.get("/options", response_model=WritingOptions)
def options(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> WritingOptions:
    publications.get(db, context.user.id, project_id, publication_id)
    return service.options()


@router.post("/preview", response_model=WritingPreview)
def preview(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    body: WritingSelection,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> WritingPreview:
    return service.prepare(db, context.user.id, project_id, publication_id, body)[0]


@router.post("", response_model=WritingPlanOut, status_code=201)
def create(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    body: WritingCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> WritingPlanOut:
    return receipt_out(
        db,
        service.create(db, context.user.id, project_id, publication_id, body),
        "create",
        body.idempotency_key,
    )


@router.get("", response_model=WritingPlanPage)
def list_plans(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> WritingPlanPage:
    publications.get(db, context.user.id, project_id, publication_id)
    rows = list(
        db.scalars(
            select(WritingPlan)
            .where(
                WritingPlan.user_id == context.user.id,
                WritingPlan.publication_id == publication_id,
                cursor_filter(WritingPlan, cursor),
            )
            .order_by(WritingPlan.created_at.desc(), WritingPlan.id.desc())
            .limit(limit + 1)
        )
    )
    return WritingPlanPage(
        items=[WritingPlanSummary.model_validate(r) for r in rows[:limit]],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None,
        ),
    )


@router.get("/lookup", response_model=WritingPlanOut)
def lookup(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> WritingPlanOut:
    row = service.lookup(db, context.user.id, project_id, publication_id, key)
    result = service.detail(db, row)
    result.operation_receipt = WritingOperationReceipt(
        kind="create", request_sha256=row.create_sha256, idempotency_key=key
    )
    return result


@router.get("/{plan_id}", response_model=WritingPlanOut)
def get(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    plan_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> WritingPlanOut:
    return service.detail(db, service.get(db, context.user.id, project_id, publication_id, plan_id))


@router.post("/{plan_id}/start", response_model=WritingPlanOut)
def start(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: WritingStart,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> WritingPlanOut:
    return receipt_out(
        db,
        service.start(
            db, service.get(db, context.user.id, project_id, publication_id, plan_id), body
        ),
        "start",
        body.idempotency_key,
    )


@router.post("/{plan_id}/import-result", response_model=WritingPlanOut)
def import_result(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: WritingImport,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> WritingPlanOut:
    return receipt_out(
        db,
        service.import_result(
            db, service.get(db, context.user.id, project_id, publication_id, plan_id), body
        ),
        "import",
        body.idempotency_key,
    )


@router.post("/{plan_id}/adopt-preview", response_model=PublicationPreview)
def adopt_preview(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: WritingAdoptionSelection,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PublicationPreview:
    return service.adoption_preview(
        db, service.get(db, context.user.id, project_id, publication_id, plan_id), body
    )


@router.post("/{plan_id}/adopt", response_model=WritingPlanOut)
def adopt(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: WritingAdopt,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> WritingPlanOut:
    return receipt_out(
        db,
        service.adopt(
            db, service.get(db, context.user.id, project_id, publication_id, plan_id), body
        ),
        "adopt",
        body.idempotency_key,
    )


@router.get("/{plan_id}/operations/lookup", response_model=WritingPlanOut)
def operation_lookup(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    plan_id: uuid.UUID,
    kind: Literal["start", "import", "adopt", "issue"],
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> WritingPlanOut:
    row = service.get(db, context.user.id, project_id, publication_id, plan_id)
    receipt = db.scalar(
        select(WritingOperation).where(
            WritingOperation.plan_id == row.id,
            WritingOperation.user_id == context.user.id,
            WritingOperation.kind == kind,
            WritingOperation.idempotency_key == key,
        )
    )
    if receipt is None:
        raise service.fail("NOT_FOUND", "Owned writing operation not found", 404)
    result = service.detail(db, row)
    result.operation_receipt = WritingOperationReceipt(
        kind=kind, request_sha256=receipt.request_sha256, idempotency_key=key
    )
    return result


@router.post("/{plan_id}/issues", response_model=WritingPlanOut, status_code=201)
def create_issue(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: WritingIssueCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> WritingPlanOut:
    return receipt_out(
        db,
        service.create_issue(
            db, service.get(db, context.user.id, project_id, publication_id, plan_id), body
        ),
        "issue",
        body.idempotency_key,
    )
