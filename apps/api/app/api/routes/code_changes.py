import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas import PageMeta
from app.schemas_code_changes import (
    CodeChangeAbandon,
    CodeChangeApply,
    CodeChangeCreate,
    CodeChangeImport,
    CodeChangeOptions,
    CodeChangeOut,
    CodeChangePage,
    CodeChangePreview,
    CodeChangeReconciliation,
    CodeChangeSelection,
)
from app.services import code_changes as service

router = APIRouter(prefix="/projects/{project_id}/code-changes", tags=["code-changes"])


@router.get("/options", response_model=CodeChangeOptions)
def options(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> CodeChangeOptions:
    return service.options(db, context.user.id, project_id)


@router.post("/preview", response_model=CodeChangePreview)
def preview(
    project_id: uuid.UUID,
    body: CodeChangeSelection,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodeChangePreview:
    return service.preview(db, context.user.id, project_id, body)


@router.post("/plans", response_model=CodeChangeOut, status_code=201)
def create(
    project_id: uuid.UUID,
    body: CodeChangeCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodeChangeOut:
    return service.detail(db, service.create(db, context.user.id, project_id, body))


@router.get("/plans", response_model=CodeChangePage)
def list_plans(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> CodeChangePage:
    rows, next_cursor = service.list_plans(db, context.user.id, project_id, limit, cursor)
    return CodeChangePage(
        items=[service.summary(x) for x in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.get("/plans/lookup", response_model=CodeChangeOut)
def lookup(
    project_id: uuid.UUID,
    idempotency_key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> CodeChangeOut:
    return service.detail(db, service.lookup(db, context.user.id, project_id, idempotency_key))


@router.get("/plans/{plan_id}", response_model=CodeChangeOut)
def detail(
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> CodeChangeOut:
    return service.detail(db, service.get_plan(db, context.user.id, project_id, plan_id))


@router.post("/plans/{plan_id}/import-result", response_model=CodeChangeOut)
def import_result(
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: CodeChangeImport,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodeChangeOut:
    return service.detail(db, service.import_result(db, context.user.id, project_id, plan_id, body))


@router.post("/plans/{plan_id}/apply", response_model=CodeChangeOut)
def apply(
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: CodeChangeApply,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodeChangeOut:
    return service.detail(db, service.apply(db, context.user.id, project_id, plan_id, body))


@router.post("/plans/{plan_id}/inspect-application", response_model=CodeChangeReconciliation)
def inspect_application(
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodeChangeReconciliation:
    return service.reconciliation(db, context.user.id, project_id, plan_id)


@router.post("/plans/{plan_id}/abandon", response_model=CodeChangeOut)
def abandon(
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: CodeChangeAbandon,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodeChangeOut:
    return service.detail(db, service.abandon(db, context.user.id, project_id, plan_id, body))
