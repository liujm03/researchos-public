import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.models_note_trash import NoteTrashEntry
from app.schemas_note_trash import (
    GeneratedFileSettingsOut,
    GeneratedFileSettingsPatch,
    NoteTrashEntryOut,
    NoteTrashPreviewOut,
    NoteTrashPreviewRequest,
    NoteTrashRequest,
    NoteTrashRestoreRequest,
)
from app.services import note_trash as service

router = APIRouter(tags=["generated-files"])


@router.get("/settings/generated-files", response_model=GeneratedFileSettingsOut)
def generated_settings(
    context: AuthContext = Depends(current_context), db: Session = Depends(get_db)
) -> GeneratedFileSettingsOut:
    return service.settings_out(db, context.user.id)


@router.patch("/settings/generated-files", response_model=GeneratedFileSettingsOut)
def update_generated_settings(
    body: GeneratedFileSettingsPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> GeneratedFileSettingsOut:
    return service.patch_settings(db, context.user.id, body)


@router.post("/research-notes/{note_id}/trash-preview", response_model=NoteTrashPreviewOut)
def trash_preview(
    note_id: uuid.UUID,
    body: NoteTrashPreviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteTrashPreviewOut:
    return service.preview(db, context.user.id, note_id, body.scope)


@router.post("/research-notes/{note_id}/trash", response_model=NoteTrashEntryOut)
def trash_note(
    note_id: uuid.UUID,
    body: NoteTrashRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteTrashEntryOut:
    raise DomainError("NOTE_RECYCLING_RETIRED", "删除现为永久删除，请重新核对范围后确认。", 410)


@router.get("/note-trash", response_model=list[NoteTrashEntryOut])
def list_trash(
    state: Literal["TRASHED", "RESTORED"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[NoteTrashEntryOut]:
    query = select(NoteTrashEntry).where(NoteTrashEntry.user_id == context.user.id)
    if state:
        query = query.where(NoteTrashEntry.state == state)
    return [
        service.entry_out(e)
        for e in db.scalars(
            query.order_by(NoteTrashEntry.created_at.desc(), NoteTrashEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ]


@router.get("/note-trash/by-operation", response_model=NoteTrashEntryOut)
def lookup_trash(
    idempotency_key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> NoteTrashEntryOut:
    return service.entry_out(service.lookup(db, context.user.id, idempotency_key))


@router.get("/note-trash/{entry_id}", response_model=NoteTrashEntryOut)
def get_trash(
    entry_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> NoteTrashEntryOut:
    return service.entry_out(service.get_entry(db, context.user.id, entry_id))


@router.post("/note-trash/{entry_id}/restore", response_model=NoteTrashEntryOut)
def restore_trash(
    entry_id: uuid.UUID,
    body: NoteTrashRestoreRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteTrashEntryOut:
    raise DomainError("NOTE_RECYCLING_RETIRED", "回收恢复接口已停用；历史记录不会自动清空。", 410)
