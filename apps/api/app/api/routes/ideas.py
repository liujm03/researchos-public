import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.models_ideas import IdeaRevision
from app.schemas import PageMeta
from app.schemas_ideas import (
    IdeaBriefCreate,
    IdeaBriefPreviewCreate,
    IdeaBriefPreviewOut,
    IdeaBriefReceipt,
    IdeaCreate,
    IdeaOut,
    IdeaPage,
    IdeaRevise,
    IdeaRevisionPage,
    IdeaStatus,
    IdeaSummary,
    IdeaTaskCreate,
    IdeaTaskReceipt,
)
from app.schemas_paper_reproduction import ReproductionSourceContentOut, ReproductionSourcePage
from app.services import canonical_reproduction
from app.services import ideas as service
from app.services.common import cursor_filter, encode_cursor

router = APIRouter(prefix="/ideas", tags=["ideas"])


@router.get("", response_model=IdeaPage)
def list_ideas(
    project_id: uuid.UUID | None = None,
    status: IdeaStatus | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> IdeaPage:
    rows, next_cursor = service.list_ideas(db, context.user.id, project_id, status, limit, cursor)
    return IdeaPage(
        items=[
            IdeaSummary(
                id=x.id,
                project_id=x.project_id,
                title=x.title,
                status=x.status,
                revision=x.revision,
                created_at=x.created_at,
            )
            for x in rows
        ],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post("", response_model=IdeaOut, status_code=201)
def create(
    body: IdeaCreate, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> IdeaOut:
    return service.out(db, service.create(db, context.user.id, body))


@router.get("/sources", response_model=ReproductionSourcePage)
def source_list(
    paper_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ReproductionSourcePage:
    return service.list_sources(db, context.user.id, paper_id, limit, cursor)


@router.get("/sources/{note_id}", response_model=ReproductionSourceContentOut)
def source_content(
    note_id: uuid.UUID,
    paper_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ReproductionSourceContentOut:
    return canonical_reproduction.source_content(db, context.user.id, paper_id, note_id)


@router.get("/lookup", response_model=IdeaOut)
def lookup(
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> IdeaOut:
    return service.out(db, service.lookup(db, context.user.id, key))


@router.get("/{identity}", response_model=IdeaOut)
def get(
    identity: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> IdeaOut:
    return service.out(db, service.get(db, context.user.id, identity))


@router.patch("/{identity}", response_model=IdeaOut)
def revise(
    identity: uuid.UUID,
    body: IdeaRevise,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> IdeaOut:
    return service.out(db, service.revise(db, context.user.id, identity, body))


@router.get("/{identity}/revisions", response_model=IdeaRevisionPage)
def revisions(
    identity: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> IdeaRevisionPage:
    service.get(db, context.user.id, identity)
    found = list(
        db.scalars(
            select(IdeaRevision)
            .where(
                IdeaRevision.idea_id == identity,
                IdeaRevision.user_id == context.user.id,
                cursor_filter(IdeaRevision, cursor),
            )
            .order_by(IdeaRevision.created_at.desc(), IdeaRevision.id.desc())
            .limit(limit + 1)
        )
    )
    return IdeaRevisionPage(
        items=[service.revision_out(db, x) for x in found[:limit]],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(found[limit - 1].created_at, found[limit - 1].id)
            if len(found) > limit
            else None,
        ),
    )


@router.post("/{identity}/tasks", response_model=IdeaTaskReceipt, status_code=201)
def create_task(
    identity: uuid.UUID,
    body: IdeaTaskCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> IdeaTaskReceipt:
    return IdeaTaskReceipt.model_validate(service.task(db, context.user.id, identity, body))


@router.post("/{identity}/brief-preview", response_model=IdeaBriefPreviewOut)
def preview(
    identity: uuid.UUID,
    body: IdeaBriefPreviewCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> IdeaBriefPreviewOut:
    return service.brief_preview(db, context.user.id, identity, body)


@router.post("/{identity}/briefs", response_model=IdeaBriefReceipt, status_code=201)
def create_brief(
    identity: uuid.UUID,
    body: IdeaBriefCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> IdeaBriefReceipt:
    return IdeaBriefReceipt.model_validate(
        service.brief_create(db, context.user.id, identity, body)
    )
