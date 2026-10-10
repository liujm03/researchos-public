import uuid

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.models import (
    Author,
    EntityTag,
    Paper,
    PaperAuthor,
    PaperNote,
    PaperReading,
    PaperSource,
    ProjectPaper,
    Tag,
    Venue,
)
from app.schemas import (
    AuthorOut,
    NoteCreate,
    NoteOut,
    NotePatch,
    PageMeta,
    PaperCreate,
    PaperOut,
    PaperPage,
    PaperPatch,
    PaperSourceOut,
    ReadingOut,
    ReadingUpdate,
    VenueOut,
)
from app.schemas_literature_context import PaperLiteratureContextOut
from app.schemas_venue_ratings import VenueAssessmentCreate, VenueAssessmentOut
from app.services import papers as service
from app.services import venue_ratings
from app.services.literature_context import project_literature_contexts
from app.services.paper_projects import replace_projects
from app.services.zotero_venue_fields import refresh_fields

router = APIRouter(prefix="/papers", tags=["papers"])
notes_router = APIRouter(prefix="/paper-notes", tags=["paper-notes"])


def paper_response(
    db: Session,
    user_id: uuid.UUID,
    paper: Paper,
    literature_context: PaperLiteratureContextOut | None = None,
) -> PaperOut:
    venue = db.get(Venue, paper.venue_id) if paper.venue_id else None
    author_rows = db.execute(
        select(Author, PaperAuthor.position)
        .join(PaperAuthor, PaperAuthor.author_id == Author.id)
        .where(PaperAuthor.paper_id == paper.id)
        .order_by(PaperAuthor.position)
    ).all()
    reading = db.scalar(
        select(PaperReading).where(
            PaperReading.paper_id == paper.id, PaperReading.user_id == user_id
        )
    )
    if reading is None:
        raise DomainError("DATA_INTEGRITY", "Paper reading state is missing", 500)
    tags = list(
        db.scalars(
            select(Tag.name)
            .join(EntityTag, EntityTag.tag_id == Tag.id)
            .where(EntityTag.entity_id == paper.id)
            .order_by(Tag.name)
        )
    )
    project_ids = list(
        db.scalars(select(ProjectPaper.project_id).where(ProjectPaper.paper_id == paper.id))
    )
    sources = list(
        db.scalars(
            select(PaperSource)
            .where(PaperSource.paper_id == paper.id)
            .order_by(PaperSource.fetched_at.desc())
        )
    )
    return PaperOut(
        id=paper.id,
        title=paper.title,
        year=paper.year,
        venue=VenueOut(id=venue.id, name=venue.name, type=venue.type) if venue else None,
        venue_assessments=venue_ratings.assessments_for_paper(db, user_id, paper),
        authors=[
            AuthorOut(id=author.id, display_name=author.display_name, position=position)
            for author, position in author_rows
        ],
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        abstract=paper.abstract,
        url=paper.url,
        pdf_url=paper.pdf_url,
        reading=ReadingOut(
            status=reading.reading_status,
            importance=reading.importance,
            relevance=reading.relevance,
            last_read_at=reading.last_read_at,
            completed_at=reading.completed_at,
        ),
        tags=tags,
        project_ids=project_ids,
        literature_context=literature_context
        or project_literature_contexts(db, user_id, [paper.id]).get(
            paper.id, PaperLiteratureContextOut()
        ),
        sources=[
            PaperSourceOut.model_validate(
                {
                    "provider_key": source.provider_key,
                    "provider_id": source.provider_id,
                    "source_version": source.source_version,
                    "source_url": source.source_url,
                    "fetched_at": source.fetched_at,
                }
            )
            for source in sources
        ],
        version=paper.version,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


@router.get("", response_model=PaperPage)
def list_papers(
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    project_id: uuid.UUID | None = None,
    unclassified: bool = False,
    collection_id: uuid.UUID | None = None,
    include_subcollections: bool = False,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PaperPage:
    rows, next_cursor = service.list_papers(
        db,
        context.user.id,
        limit,
        cursor,
        status,
        q,
        project_id,
        unclassified,
        collection_id,
        include_subcollections,
    )
    contexts = project_literature_contexts(db, context.user.id, [row.id for row in rows])
    return PaperPage(
        items=[paper_response(db, context.user.id, row, contexts[row.id]) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


class PaperProjectsReplace(BaseModel):
    project_ids: list[uuid.UUID] = Field(max_length=100)
    expected_version: int = Field(ge=1)


@router.put("/{paper_id}/projects", response_model=PaperOut)
def classify_paper(
    paper_id: uuid.UUID,
    body: PaperProjectsReplace,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PaperOut:
    paper = replace_projects(db, context.user.id, paper_id, body.project_ids, body.expected_version)
    return paper_response(db, context.user.id, paper)


@router.post("", response_model=PaperOut, status_code=201)
def create_paper(
    body: PaperCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PaperOut:
    paper = service.create_paper(db, context.user.id, body)
    return paper_response(db, context.user.id, paper)


@router.get("/{paper_id}", response_model=PaperOut)
def get_paper(
    paper_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PaperOut:
    return paper_response(db, context.user.id, service.get_paper(db, context.user.id, paper_id))


@router.patch("/{paper_id}", response_model=PaperOut)
def patch_paper(
    paper_id: uuid.UUID,
    body: PaperPatch,
    if_match: str | None = Header(default=None),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PaperOut:
    paper = service.update_paper(db, context.user.id, paper_id, body, if_match)
    return paper_response(db, context.user.id, paper)


@router.get("/{paper_id}/venue-assessments", response_model=list[VenueAssessmentOut])
def get_venue_assessments(
    paper_id: uuid.UUID,
    request_key: str | None = Query(default=None, max_length=64),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[VenueAssessmentOut]:
    paper = service.get_paper(db, context.user.id, paper_id)
    return venue_ratings.assessments_for_paper(db, context.user.id, paper, request_key=request_key)


@router.post("/{paper_id}/venue-assessments", response_model=VenueAssessmentOut, status_code=201)
def add_venue_assessment(
    paper_id: uuid.UUID,
    body: VenueAssessmentCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> VenueAssessmentOut:
    return VenueAssessmentOut.model_validate(
        venue_ratings.append_assessment(db, context.user.id, paper_id, body)
    )


@router.post(
    "/{paper_id}/venue-assessments/refresh-zotero", response_model=list[VenueAssessmentOut]
)
async def refresh_zotero_venue_fields(
    paper_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> list[VenueAssessmentOut]:
    paper = await refresh_fields(db, context.user.id, paper_id)
    return venue_ratings.assessments_for_paper(db, context.user.id, paper)


@router.delete("/{paper_id}", status_code=204)
def archive_paper(
    paper_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    service.update_reading(db, context.user.id, paper_id, ReadingUpdate(status="archived"))


@router.put("/{paper_id}/reading", response_model=ReadingOut)
def update_reading(
    paper_id: uuid.UUID,
    body: ReadingUpdate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ReadingOut:
    reading = service.update_reading(db, context.user.id, paper_id, body)
    return ReadingOut(
        status=reading.reading_status,
        importance=reading.importance,
        relevance=reading.relevance,
        last_read_at=reading.last_read_at,
        completed_at=reading.completed_at,
    )


@router.get("/{paper_id}/notes", response_model=list[NoteOut])
def list_notes(
    paper_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[NoteOut]:
    service.get_paper(db, context.user.id, paper_id)
    rows = db.scalars(
        select(PaperNote)
        .where(PaperNote.paper_id == paper_id, PaperNote.user_id == context.user.id)
        .order_by(PaperNote.created_at.desc())
    )
    return [NoteOut.model_validate(row) for row in rows]


@router.post("/{paper_id}/notes", response_model=NoteOut, status_code=201)
def create_note(
    paper_id: uuid.UUID,
    body: NoteCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteOut:
    return NoteOut.model_validate(service.create_note(db, context.user.id, paper_id, body))


@notes_router.get("/{note_id}", response_model=NoteOut)
def get_note(
    note_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> NoteOut:
    return NoteOut.model_validate(service.get_note(db, context.user.id, note_id))


@notes_router.patch("/{note_id}", response_model=NoteOut)
def patch_note(
    note_id: uuid.UUID,
    body: NotePatch,
    if_match: str | None = Header(default=None),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> NoteOut:
    return NoteOut.model_validate(service.update_note(db, context.user.id, note_id, body, if_match))
