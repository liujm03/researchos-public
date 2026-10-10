import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas_note_deletion import (
    NoteDeletionOut,
    NoteDeletionPreviewOut,
    NoteDeletionPreviewRequest,
    NoteDeletionRequest,
    NoteDeletionRetryRequest,
)
from app.services import note_deletion as service
from app.services.note_deletion_plan import build_plan

router = APIRouter(tags=["generated-files"])


@router.post("/research-notes/{note_id}/deletion-preview", response_model=NoteDeletionPreviewOut)
async def preview(
    note_id: uuid.UUID,
    body: NoteDeletionPreviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteDeletionPreviewOut:
    return (await build_plan(db, context.user.id, note_id)).preview


@router.post("/research-notes/{note_id}/delete-permanently", response_model=NoteDeletionOut)
async def permanently_delete(
    note_id: uuid.UUID,
    body: NoteDeletionRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteDeletionOut:
    return service.out(db, await service.start(db, context.user.id, note_id, body))


@router.get("/note-deletions/by-operation", response_model=NoteDeletionOut)
def lookup(
    idempotency_key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> NoteDeletionOut:
    return service.out(db, service.by_key(db, context.user.id, idempotency_key))


@router.get("/note-deletions/{operation_id}", response_model=NoteDeletionOut)
def detail(
    operation_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> NoteDeletionOut:
    return service.out(db, service.get_operation(db, context.user.id, operation_id))


@router.post("/note-deletions/{operation_id}/retry", response_model=NoteDeletionOut)
async def retry(
    operation_id: uuid.UUID,
    body: NoteDeletionRetryRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteDeletionOut:
    return service.out(db, await service.retry(db, context.user.id, operation_id))
