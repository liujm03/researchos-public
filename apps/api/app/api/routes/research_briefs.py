import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas import PageMeta
from app.schemas_research_briefs import (
    ResearchBriefCanonicalSourcePage,
    ResearchBriefCreate,
    ResearchBriefDetailOut,
    ResearchBriefPage,
    ResearchBriefReviewCreate,
    ResearchBriefSummaryOut,
)
from app.services import research_briefs as service

router = APIRouter(prefix="/projects/{project_id}/research-briefs", tags=["research-briefs"])


@router.get("", response_model=ResearchBriefPage)
def list_briefs(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ResearchBriefPage:
    rows, next_cursor = service.list_briefs(db, context.user.id, project_id, limit, cursor)
    return ResearchBriefPage(
        items=[
            ResearchBriefSummaryOut.model_validate(service.detail_out(db, row).model_dump())
            for row in rows
        ],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post("", response_model=ResearchBriefDetailOut, status_code=201)
def create_brief(
    project_id: uuid.UUID,
    body: ResearchBriefCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ResearchBriefDetailOut:
    return service.detail_out(db, service.create_brief(db, context.user.id, project_id, body))


@router.get("/canonical-sources", response_model=ResearchBriefCanonicalSourcePage)
def list_canonical_sources(
    project_id: uuid.UUID,
    paper_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ResearchBriefCanonicalSourcePage:
    from app.services import brief_canonical_sources

    return brief_canonical_sources.list_sources(
        db, context.user.id, project_id, paper_id, limit, cursor
    )


@router.get("/{brief_id}", response_model=ResearchBriefDetailOut)
def get_brief(
    project_id: uuid.UUID,
    brief_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ResearchBriefDetailOut:
    return service.detail_out(db, service.get_brief(db, context.user.id, project_id, brief_id))


@router.post("/{brief_id}/review", response_model=ResearchBriefDetailOut)
def review_brief(
    project_id: uuid.UUID,
    brief_id: uuid.UUID,
    body: ResearchBriefReviewCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ResearchBriefDetailOut:
    return service.detail_out(
        db, service.review_brief(db, context.user.id, project_id, brief_id, body)
    )
