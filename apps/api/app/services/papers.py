import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.domain.literature_identity import normalize_doi as normalize_doi
from app.domain.literature_identity import normalized_arxiv_id
from app.errors import DomainError
from app.models import (
    Author,
    EntityTag,
    Paper,
    PaperAuthor,
    PaperNote,
    PaperReading,
    ProjectPaper,
    ResearchEntity,
    ResearchProject,
    Tag,
    Venue,
)
from app.schemas import NoteCreate, NotePatch, PaperCreate, PaperPatch, ReadingUpdate
from app.services.common import assert_version, cursor_filter, encode_cursor, register_entity
from app.services.literature_context import collection_family_ids, zotero_collection_paper_filter
from app.services.projects import get_project


def get_paper(db: Session, user_id: uuid.UUID, paper_id: uuid.UUID) -> Paper:
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.user_id == user_id))
    if paper is None:
        raise DomainError("NOT_FOUND", "Paper not found", 404)
    return paper


def _get_or_create_venue(db: Session, name: str, venue_type: str) -> Venue:
    venue = db.scalar(select(Venue).where(func.lower(Venue.name) == name.strip().lower()))
    if venue is None:
        venue = Venue(id=uuid.uuid4(), name=name.strip(), type=venue_type)
        db.add(venue)
        db.flush()
    return venue


def create_paper(
    db: Session, user_id: uuid.UUID, data: PaperCreate, *, commit: bool = True
) -> Paper:
    normalized_doi = normalize_doi(data.doi)
    if normalized_doi and db.scalar(
        select(Paper.id).where(Paper.user_id == user_id, Paper.normalized_doi == normalized_doi)
    ):
        raise DomainError("CONFLICT", "Paper with this DOI already exists", 409)
    for project_id in data.project_ids:
        get_project(db, user_id, project_id)
    item_id = register_entity(db, user_id, "paper")
    venue_id = (
        _get_or_create_venue(db, data.venue_name, data.venue_type).id if data.venue_name else None
    )
    paper = Paper(
        id=item_id,
        user_id=user_id,
        title=data.title.strip(),
        normalized_title=" ".join(data.title.lower().split()),
        year=data.year,
        venue_id=venue_id,
        doi=data.doi.strip() if data.doi else None,
        normalized_doi=normalized_doi,
        arxiv_id=data.arxiv_id.strip() if data.arxiv_id else None,
        normalized_arxiv_id=normalized_arxiv_id(data.arxiv_id),
        abstract=data.abstract,
        url=data.url,
        pdf_url=data.pdf_url,
    )
    db.add(paper)
    db.add(PaperReading(paper_id=item_id, user_id=user_id, reading_status="unread"))
    for position, name in enumerate(data.authors, start=1):
        clean_name = name.strip()
        if not clean_name:
            continue
        # A name alone cannot establish author identity; later ORCID/manual merge may reconcile.
        author_id = register_entity(db, user_id, "author")
        author = Author(id=author_id, user_id=user_id, display_name=clean_name)
        db.add(author)
        db.flush()
        db.add(PaperAuthor(paper_id=item_id, author_id=author.id, position=position))
    for project_id in dict.fromkeys(data.project_ids):
        db.add(ProjectPaper(project_id=project_id, paper_id=item_id, role="related"))
    for name in dict.fromkeys(data.tags):
        clean_name = name.strip().lstrip("#")
        if not clean_name:
            continue
        normalized = clean_name.casefold()
        tag = db.scalar(
            select(Tag).where(Tag.user_id == user_id, Tag.normalized_name == normalized)
        )
        if tag is None:
            tag = Tag(id=uuid.uuid4(), user_id=user_id, name=clean_name, normalized_name=normalized)
            db.add(tag)
            db.flush()
        db.add(EntityTag(entity_id=item_id, tag_id=tag.id))
    try:
        if commit:
            db.commit()
            db.refresh(paper)
        else:
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError(
            "CONFLICT", "Paper metadata conflicts with an existing record", 409
        ) from exc
    return paper


def list_papers(
    db: Session,
    user_id: uuid.UUID,
    limit: int,
    cursor: str | None,
    status: str | None,
    q: str | None,
    project_id: uuid.UUID | None = None,
    unclassified: bool = False,
    collection_id: uuid.UUID | None = None,
    include_subcollections: bool = False,
) -> tuple[list[Paper], str | None]:
    query = (
        select(Paper)
        .join(ResearchEntity, ResearchEntity.id == Paper.id)
        .where(
            Paper.user_id == user_id,
            ResearchEntity.user_id == user_id,
            ResearchEntity.deleted_at.is_(None),
            cursor_filter(Paper, cursor),
        )
    )
    project_entity = aliased(ResearchEntity)
    linked_projects = (
        select(ProjectPaper.paper_id)
        .join(ResearchProject, ResearchProject.id == ProjectPaper.project_id)
        .join(project_entity, project_entity.id == ResearchProject.id)
        .where(
            ProjectPaper.paper_id == Paper.id,
            ResearchProject.user_id == user_id,
            project_entity.user_id == user_id,
            project_entity.deleted_at.is_(None),
        )
    )
    if project_id is not None:
        query = query.where(exists(linked_projects.where(ResearchProject.id == project_id)))
    if unclassified:
        query = query.where(~exists(linked_projects))
    if collection_id is not None:
        family = (
            collection_family_ids(db, user_id, collection_id) if include_subcollections else None
        )
        query = query.where(zotero_collection_paper_filter(user_id, collection_id, family))
    if status:
        query = query.join(PaperReading, PaperReading.paper_id == Paper.id).where(
            PaperReading.reading_status == status, PaperReading.user_id == user_id
        )
    if q:
        query = query.where(Paper.normalized_title.ilike(f"%{q.strip()}%"))
    rows = list(
        db.scalars(query.order_by(Paper.created_at.desc(), Paper.id.desc()).limit(limit + 1))
    )
    next_cursor = (
        encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    )
    return rows[:limit], next_cursor


def update_paper(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    data: PaperPatch,
    if_match: str | None,
) -> Paper:
    paper = get_paper(db, user_id, paper_id)
    assert_version(paper.version, if_match)
    changes = data.model_dump(exclude_unset=True)
    if "title" in changes:
        if changes["title"] is None:
            raise DomainError("VALIDATION_ERROR", "title cannot be null", 422)
        changes["normalized_title"] = " ".join(changes["title"].lower().split())
    if "doi" in changes:
        changes["normalized_doi"] = normalize_doi(changes["doi"])
    if "arxiv_id" in changes:
        changes["normalized_arxiv_id"] = normalized_arxiv_id(changes["arxiv_id"])
    for key, value in changes.items():
        setattr(paper, key, value)
    paper.version += 1
    paper.updated_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("CONFLICT", "Paper identifier already exists", 409) from exc
    db.refresh(paper)
    return paper


def update_reading(
    db: Session, user_id: uuid.UUID, paper_id: uuid.UUID, data: ReadingUpdate
) -> PaperReading:
    get_paper(db, user_id, paper_id)
    reading = db.scalar(
        select(PaperReading).where(
            PaperReading.paper_id == paper_id, PaperReading.user_id == user_id
        )
    )
    if reading is None:
        reading = PaperReading(paper_id=paper_id, user_id=user_id)
        db.add(reading)
    reading.reading_status = data.status
    reading.importance = data.importance
    reading.relevance = data.relevance
    reading.last_read_at = datetime.now(UTC)
    if data.status == "completed":
        reading.completed_at = reading.last_read_at
    db.commit()
    db.refresh(reading)
    return reading


def create_note(
    db: Session, user_id: uuid.UUID, paper_id: uuid.UUID, data: NoteCreate
) -> PaperNote:
    get_paper(db, user_id, paper_id)
    item_id = register_entity(db, user_id, "note")
    note = PaperNote(id=item_id, paper_id=paper_id, user_id=user_id, **data.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def get_note(db: Session, user_id: uuid.UUID, note_id: uuid.UUID) -> PaperNote:
    note = db.scalar(select(PaperNote).where(PaperNote.id == note_id, PaperNote.user_id == user_id))
    if note is None:
        raise DomainError("NOT_FOUND", "Paper note not found", 404)
    return note


def update_note(
    db: Session,
    user_id: uuid.UUID,
    note_id: uuid.UUID,
    data: NotePatch,
    if_match: str | None,
) -> PaperNote:
    note = get_note(db, user_id, note_id)
    assert_version(note.version, if_match)
    changes = data.model_dump(exclude_unset=True)
    if "body_markdown" in changes and changes["body_markdown"] is None:
        raise DomainError("VALIDATION_ERROR", "body_markdown cannot be null", 422)
    for key, value in changes.items():
        setattr(note, key, value)
    note.version += 1
    note.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(note)
    return note
