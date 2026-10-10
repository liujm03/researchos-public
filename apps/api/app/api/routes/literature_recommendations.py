"""Project-scoped candidate metadata, with explicit approval for network reads."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.providers import registry
from app.schemas_literature_recommendations import (
    LiteratureCandidateAdoptOut,
    LiteratureCandidateAdoptRequest,
    LiteratureRecommendationOptions,
    LiteratureResearchLinks,
    LiteratureSearchBatchOut,
    LiteratureSearchBatchPage,
    LiteratureSearchNextRequest,
    LiteratureSearchPreviewOut,
    LiteratureSearchSelection,
    LiteratureSearchStartRequest,
)
from app.services import literature_recommendations as service

router = APIRouter(tags=["literature-recommendations"])
_PATH = "/projects/{project_id}/literature-recommendations"


@router.get(_PATH + "/links", response_model=LiteratureResearchLinks)
def discovery_links(
    project_id: uuid.UUID,
    query: str | None = Query(None, min_length=1, max_length=500),
    question_id: uuid.UUID | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> LiteratureResearchLinks:
    return service.discovery_links(db, context.user.id, project_id, query, question_id)


@router.get(_PATH + "/options", response_model=LiteratureRecommendationOptions)
def options(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> LiteratureRecommendationOptions:
    return service.options(db, context.user.id, project_id)


@router.post(_PATH + "/preview", response_model=LiteratureSearchPreviewOut)
def preview(
    project_id: uuid.UUID,
    body: LiteratureSearchSelection,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> LiteratureSearchPreviewOut:
    return service.preview(db, context.user.id, project_id, body)


@router.get(_PATH, response_model=LiteratureSearchBatchPage)
def list_batches(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> LiteratureSearchBatchPage:
    return service.list_batches(db, context.user.id, project_id, limit, cursor)


@router.get(_PATH + "/{batch_id}", response_model=LiteratureSearchBatchOut)
def detail(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> LiteratureSearchBatchOut:
    return service.batch_out(db, service.get_batch(db, context.user.id, project_id, batch_id))


@router.post(_PATH, response_model=LiteratureSearchBatchOut, status_code=201)
async def search(
    project_id: uuid.UUID,
    body: LiteratureSearchStartRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> LiteratureSearchBatchOut:
    row = await service.search(
        db,
        context.user.id,
        project_id,
        body,
        registry.literature_search_provider(body.selection.provider_key),
    )
    return service.batch_out(db, row)


@router.post(_PATH + "/{batch_id}/next", response_model=LiteratureSearchBatchOut, status_code=201)
async def next_page(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    body: LiteratureSearchNextRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> LiteratureSearchBatchOut:
    saved = service.get_batch(db, context.user.id, project_id, batch_id)
    row = await service.next_page(
        db,
        context.user.id,
        project_id,
        batch_id,
        body,
        registry.literature_search_provider(saved.provider_key),
    )
    return service.batch_out(db, row)


@router.post(
    _PATH + "/{batch_id}/candidates/{candidate_id}/adopt",
    response_model=LiteratureCandidateAdoptOut,
)
def adopt(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: LiteratureCandidateAdoptRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> LiteratureCandidateAdoptOut:
    return service.adopt(db, context.user.id, project_id, batch_id, candidate_id, body)
