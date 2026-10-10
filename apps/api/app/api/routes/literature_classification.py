"""Local owner classification and explicit metadata-only collection refresh."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.providers.registry import reference_manager
from app.schemas_literature_context import (
    LiteratureClassificationOptionsOut,
    ZoteroCollectionsRefreshOut,
)
from app.schemas_note_projects import NoteProjectContextOut, NoteProjectReplace
from app.services.literature_context import classification_options
from app.services.note_projects import get_context, replace
from app.services.zotero_collection_refresh import refresh_zotero_collections

router = APIRouter(tags=["literature-classification"])


@router.get("/literature-classification-options", response_model=LiteratureClassificationOptionsOut)
def options(
    context: AuthContext = Depends(current_context), db: Session = Depends(get_db)
) -> LiteratureClassificationOptionsOut:
    return classification_options(db, context.user.id)


@router.get("/research-notes/{note_id}/classification", response_model=NoteProjectContextOut)
def note_classification(
    note_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> NoteProjectContextOut:
    return get_context(db, context.user.id, note_id)


@router.put("/research-notes/{note_id}/classification", response_model=NoteProjectContextOut)
def classify_note(
    note_id: uuid.UUID,
    body: NoteProjectReplace,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteProjectContextOut:
    return replace(db, context.user.id, note_id, body)


@router.post(
    "/reference-managers/zotero/collections/refresh", response_model=ZoteroCollectionsRefreshOut
)
async def refresh_collections(
    context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> ZoteroCollectionsRefreshOut:
    return await refresh_zotero_collections(db, context.user.id, reference_manager())
