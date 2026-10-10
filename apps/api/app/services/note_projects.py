"""Owner-scoped classification with explicit empty overrides and optimistic writes."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import Paper, PaperResearchNote, ProjectPaper, ResearchEntity, ResearchProject, User
from app.models_note_projects import NoteProject, NoteProjectClassification
from app.schemas_literature_context import LiteratureProjectOut
from app.schemas_note_projects import NoteProjectContextOut, NoteProjectReplace


def _note(db: Session, owner: uuid.UUID, note_id: uuid.UUID) -> PaperResearchNote:
    note = db.scalar(
        select(PaperResearchNote)
        .join(ResearchEntity, ResearchEntity.id == PaperResearchNote.id)
        .where(
            PaperResearchNote.id == note_id,
            PaperResearchNote.user_id == owner,
            ResearchEntity.user_id == owner,
            ResearchEntity.deleted_at.is_(None),
        )
    )
    if note is None:
        raise DomainError("NOT_FOUND", "Research note not found", 404)
    paper = db.scalar(
        select(Paper.id)
        .join(ResearchEntity, ResearchEntity.id == Paper.id)
        .where(
            Paper.id == note.paper_id,
            Paper.user_id == owner,
            ResearchEntity.user_id == owner,
            ResearchEntity.deleted_at.is_(None),
        )
    )
    if not note or not paper:
        raise DomainError("NOT_FOUND", "Research note not found", 404)
    return note


def _labels(
    db: Session, owner: uuid.UUID, project_ids: list[uuid.UUID]
) -> list[LiteratureProjectOut]:
    projects = db.scalars(
        select(ResearchProject)
        .join(ResearchEntity, ResearchEntity.id == ResearchProject.id)
        .where(
            ResearchProject.id.in_(project_ids),
            ResearchProject.user_id == owner,
            ResearchEntity.user_id == owner,
            ResearchEntity.deleted_at.is_(None),
        )
        .order_by(ResearchProject.name, ResearchProject.id)
    )
    return [LiteratureProjectOut(id=p.id, name=p.name) for p in projects]


def get_context(db: Session, owner: uuid.UUID, note_id: uuid.UUID) -> NoteProjectContextOut:
    return get_contexts(db, owner, [note_id])[note_id]


def _contexts(db: Session, owner: uuid.UUID) -> dict[uuid.UUID, NoteProjectContextOut]:
    # Load scalar metadata only, in a fixed number of owner-scoped queries.
    # Parent revisions are historical metadata; only visible targets are returned.
    from sqlalchemy.orm import aliased

    ne, pe = aliased(ResearchEntity), aliased(ResearchEntity)
    rows = db.execute(
        select(
            PaperResearchNote.id,
            PaperResearchNote.paper_id,
            PaperResearchNote.parent_note_id,
            ne.deleted_at,
        )
        .join(ne, ne.id == PaperResearchNote.id)
        .join(Paper, Paper.id == PaperResearchNote.paper_id)
        .join(pe, pe.id == Paper.id)
        .where(
            PaperResearchNote.user_id == owner,
            ne.user_id == owner,
            Paper.user_id == owner,
            pe.user_id == owner,
            pe.deleted_at.is_(None),
        )
    ).all()
    notes = {r.id: r for r in rows}
    markers = {
        r.note_id: r.version
        for r in db.execute(
            select(NoteProjectClassification.note_id, NoteProjectClassification.version).where(
                NoteProjectClassification.user_id == owner
            )
        )
    }
    labels = {
        p.id: LiteratureProjectOut(id=p.id, name=p.name)
        for p in db.execute(
            select(ResearchProject.id, ResearchProject.name)
            .join(ResearchEntity, ResearchEntity.id == ResearchProject.id)
            .where(
                ResearchProject.user_id == owner,
                ResearchEntity.user_id == owner,
                ResearchEntity.deleted_at.is_(None),
            )
        )
    }
    explicit: dict[uuid.UUID, set[uuid.UUID]] = {}
    for nid, pid in db.execute(
        select(NoteProject.note_id, NoteProject.project_id).where(NoteProject.user_id == owner)
    ):
        explicit.setdefault(nid, set()).add(pid)
    fallback: dict[uuid.UUID, set[uuid.UUID]] = {}
    for paper_id, pid in db.execute(
        select(ProjectPaper.paper_id, ProjectPaper.project_id)
        .join(Paper, Paper.id == ProjectPaper.paper_id)
        .where(Paper.user_id == owner)
    ):
        fallback.setdefault(paper_id, set()).add(pid)
    output: dict[uuid.UUID, NoteProjectContextOut] = {}
    for target in rows:
        if target.deleted_at is not None:
            continue
        current = target
        seen: set[uuid.UUID] = set()
        chosen: uuid.UUID | None = None
        while True:
            if current.id in seen:
                raise DomainError(
                    "NOTE_CLASSIFICATION_LINEAGE_INVALID", "Note parent cycle detected", 409
                )
            seen.add(current.id)
            if chosen is None and current.id in markers:
                chosen = current.id
            if not current.parent_note_id:
                break
            parent = notes.get(current.parent_note_id)
            if parent is None or parent.paper_id != target.paper_id:
                raise DomainError(
                    "NOTE_CLASSIFICATION_LINEAGE_INVALID", "Invalid note parent scope", 409
                )
            current = parent
        ids = (
            explicit.get(chosen, set())
            if chosen is not None
            else fallback.get(target.paper_id, set())
        )
        projects = sorted(
            (labels[pid] for pid in ids if pid in labels), key=lambda p: (p.name, str(p.id))
        )
        mode = (
            "NOTE"
            if chosen == target.id
            else "INHERITED_NOTE"
            if chosen
            else "PAPER"
            if projects
            else "UNCLASSIFIED"
        )
        output[target.id] = NoteProjectContextOut(
            note_id=target.id,
            paper_id=target.paper_id,
            classification_version=markers.get(target.id, 0),
            projects=projects,
            mode=mode,
        )
    return output


def get_contexts(
    db: Session, owner: uuid.UUID, note_ids: list[uuid.UUID]
) -> dict[uuid.UUID, NoteProjectContextOut]:
    if not note_ids:
        return {}
    all_contexts = _contexts(db, owner)
    if any(nid not in all_contexts for nid in note_ids):
        raise DomainError("NOT_FOUND", "Research note not found", 404)
    return {nid: all_contexts[nid] for nid in dict.fromkeys(note_ids)}


def matching_note_ids(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID | None = None, unclassified: bool = False
) -> list[uuid.UUID]:
    if project_id is not None and unclassified:
        raise DomainError("VALIDATION_ERROR", "Choose a project or unclassified filter", 422)
    return [
        nid
        for nid, ctx in _contexts(db, owner).items()
        if (not unclassified or not ctx.projects)
        and (project_id is None or any(p.id == project_id for p in ctx.projects))
    ]


def replace(
    db: Session, owner: uuid.UUID, note_id: uuid.UUID, body: NoteProjectReplace
) -> NoteProjectContextOut:
    # Owner row serializes first creation on PostgreSQL; CAS still guards stale versions.
    db.scalar(select(User).where(User.id == owner).with_for_update())
    note = _note(db, owner, note_id)
    get_context(db, owner, note_id)  # Reject corrupt ancestry before committing any classification.
    ids = list(dict.fromkeys(body.project_ids))
    projects = _labels(db, owner, ids)
    if {p.id for p in projects} != set(ids):
        raise DomainError("PROJECT_NOT_FOUND", "One or more projects are unavailable", 404)
    marker = db.scalar(
        select(NoteProjectClassification)
        .where(
            NoteProjectClassification.note_id == note.id, NoteProjectClassification.user_id == owner
        )
        .with_for_update()
    )
    actual = marker.version if marker else 0
    if actual != body.expected_version:
        raise DomainError(
            "CLASSIFICATION_CONFLICT", "Classification changed; reload before saving", 409
        )
    try:
        with db.begin_nested():
            if marker:
                result = db.execute(
                    update(NoteProjectClassification)
                    .where(
                        NoteProjectClassification.note_id == note.id,
                        NoteProjectClassification.user_id == owner,
                        NoteProjectClassification.version == body.expected_version,
                    )
                    .values(version=actual + 1, updated_at=datetime.now(UTC))
                )
                if result.rowcount != 1:  # type: ignore[attr-defined]
                    raise DomainError("CLASSIFICATION_CONFLICT", "Classification changed", 409)
            else:
                db.add(NoteProjectClassification(note_id=note.id, user_id=owner, version=1))
                db.flush()
            db.execute(
                delete(NoteProject).where(
                    NoteProject.note_id == note.id, NoteProject.user_id == owner
                )
            )
            db.add_all([NoteProject(note_id=note.id, user_id=owner, project_id=pid) for pid in ids])
            db.flush()
    except IntegrityError as exc:
        raise DomainError(
            "CLASSIFICATION_CONFLICT", "Classification changed; reload before saving", 409
        ) from exc
    db.commit()
    return get_context(db, owner, note.id)
