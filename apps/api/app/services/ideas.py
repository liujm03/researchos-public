"""Immutable owner ideas; no model, PDF, shell or scientific execution."""

import uuid
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import EntityTag, Paper, Tag, Task
from app.models_analytical import CanonicalAnalyticalNote, PaperReadingApprovalPlan
from app.models_ideas import (
    IdeaBriefAction,
    IdeaRevision,
    IdeaRevisionTag,
    IdeaSource,
    IdeaTaskAction,
    ResearchBriefIdeaSource,
    ResearchIdea,
)
from app.models_research_briefs import ResearchBrief
from app.schemas import PageMeta
from app.schemas_ideas import (
    IdeaBriefCreate,
    IdeaBriefPreviewCreate,
    IdeaBriefPreviewOut,
    IdeaBriefReceipt,
    IdeaCreate,
    IdeaFields,
    IdeaOut,
    IdeaRevise,
    IdeaRevisionOut,
    IdeaSourceOut,
    IdeaTaskCreate,
    IdeaTaskReceipt,
)
from app.schemas_paper_reproduction import ReproductionSourcePage
from app.schemas_research_briefs import ResearchBriefCreate, ResearchBriefSectionCreate
from app.services import canonical_reproduction as canonical
from app.services import research_briefs as briefs
from app.services.common import cursor_filter, encode_cursor, register_entity
from app.services.note_trash import require_selectable_job, selectable_job_clause
from app.services.projects import get_project

FIELDS = tuple(IdeaFields.model_fields)
SOURCE_FIELDS = (
    "canonical_note_id",
    "paper_id",
    "paper_title",
    "reading_job_id",
    "reading_plan_id",
    "note_sha256",
    "source_sha256",
    "source_facts",
    "start_offset",
    "end_offset",
    "exact_quote",
)


def get(db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False) -> ResearchIdea:
    q = select(ResearchIdea).where(ResearchIdea.id == identity, ResearchIdea.user_id == owner)
    row = db.scalar((q.with_for_update() if lock else q).execution_options(populate_existing=True))
    if row is None:
        raise DomainError("NOT_FOUND", "Owned idea not found", 404)
    return row


def latest(db: Session, row: ResearchIdea) -> IdeaRevision:
    rev = db.scalar(
        select(IdeaRevision)
        .where(
            IdeaRevision.idea_id == row.id,
            IdeaRevision.user_id == row.user_id,
            IdeaRevision.revision == row.revision,
        )
        .execution_options(populate_existing=True)
    )
    if rev is None:
        raise DomainError("IDEA_REVISION_INVALID", "Current idea revision missing", 409)
    return rev


def sources(db: Session, rev: IdeaRevision) -> list[IdeaSource]:
    return list(
        db.scalars(
            select(IdeaSource)
            .where(IdeaSource.revision_id == rev.id, IdeaSource.user_id == rev.user_id)
            .order_by(IdeaSource.canonical_note_id, IdeaSource.start_offset, IdeaSource.id)
            .execution_options(populate_existing=True)
        )
    )


def source_values(source: IdeaSource) -> dict[str, Any]:
    return {key: getattr(source, key) for key in SOURCE_FIELDS}


def source_current(db: Session, source: IdeaSource) -> bool:
    try:
        m = canonical.material(db, source.user_id, source.paper_id, source.canonical_note_id)
        return (
            m.identity() == source.source_facts
            and m.note.sha256 == source.note_sha256
            and m.note.markdown[source.start_offset : source.end_offset] == source.exact_quote
        )
    except DomainError:
        return False


def source_intact(source: IdeaSource) -> bool:
    facts = source.source_facts
    return (
        facts.get("note_origin") == "AI_DERIVED"
        and facts.get("origin_reading_scope") == "FULL_TEXT"
        and facts.get("pdf_delivery") == "BOUND_NOT_SENT"
        and briefs.digest(facts) == source.source_sha256
        and source.end_offset - source.start_offset == len(source.exact_quote)
        and all(
            facts.get(k) == str(getattr(source, k))
            for k in ("canonical_note_id", "paper_id", "reading_job_id", "reading_plan_id")
        )
        and facts.get("note_sha256") == source.note_sha256
        and facts.get("paper_title") == source.paper_title
    )


def tags(db: Session, rev: IdeaRevision) -> list[str]:
    return list(
        db.scalars(
            select(IdeaRevisionTag.name)
            .where(IdeaRevisionTag.revision_id == rev.id, IdeaRevisionTag.user_id == rev.user_id)
            .order_by(IdeaRevisionTag.normalized_name)
        )
    )


def snapshot(db: Session, rev: IdeaRevision) -> dict[str, Any]:
    return {
        "idea_id": str(rev.idea_id),
        "revision_id": str(rev.id),
        "revision": rev.revision,
        "owner_id": str(rev.user_id),
        "fields": {key: getattr(rev, key) for key in FIELDS},
        "sources": [
            {
                key: (str(value) if isinstance(value, uuid.UUID) else value)
                for key, value in source_values(source).items()
            }
            for source in sources(db, rev)
        ],
        "tags": tags(db, rev),
        "scientific_state": "OWNER_REPORTED_NOT_SCIENTIFICALLY_VERIFIED",
    }


def intact(db: Session, rev: IdeaRevision) -> bool:
    return (
        all(source_intact(s) for s in sources(db, rev))
        and briefs.digest(snapshot(db, rev)) == rev.sha256
    )


def current(db: Session, rev: IdeaRevision) -> bool:
    return intact(db, rev) and all(source_current(db, s) for s in sources(db, rev))


def require_current(db: Session, row: ResearchIdea, expected: str) -> IdeaRevision:
    rev = latest(db, row)
    if rev.sha256 != expected or not current(db, rev):
        raise DomainError(
            "IDEA_SOURCE_CHANGED",
            "Idea revision or selected canonical sources changed; create a new explicit revision",
            409,
        )
    return rev


def revision_out(db: Session, rev: IdeaRevision) -> IdeaRevisionOut:
    return IdeaRevisionOut(
        **{key: getattr(rev, key) for key in FIELDS},
        id=rev.id,
        idea_id=rev.idea_id,
        revision=rev.revision,
        sha256=rev.sha256,
        created_at=rev.created_at,
        sources=[
            IdeaSourceOut(id=s.id, **source_values(s), context_current=source_current(db, s))
            for s in sources(db, rev)
        ],
        context_current=current(db, rev),
        tags=tags(db, rev),
        integrity_valid=intact(db, rev),
    )


def out(db: Session, row: ResearchIdea) -> IdeaOut:
    return IdeaOut(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        status=row.status,
        revision=row.revision,
        created_at=row.created_at,
        current=revision_out(db, latest(db, row)),
        task_actions=[
            IdeaTaskReceipt.model_validate(x)
            for x in db.scalars(
                select(IdeaTaskAction).where(
                    IdeaTaskAction.idea_id == row.id, IdeaTaskAction.user_id == row.user_id
                )
            )
        ],
        brief_actions=[
            IdeaBriefReceipt.model_validate(x)
            for x in db.scalars(
                select(IdeaBriefAction).where(
                    IdeaBriefAction.idea_id == row.id, IdeaBriefAction.user_id == row.user_id
                )
            )
        ],
    )


def list_ideas(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[ResearchIdea], str | None]:
    if project:
        get_project(db, owner, project)
    q = select(ResearchIdea).where(
        ResearchIdea.user_id == owner, cursor_filter(ResearchIdea, cursor)
    )
    if project:
        linked_briefs = select(IdeaBriefAction.idea_id).where(
            IdeaBriefAction.user_id == owner, IdeaBriefAction.project_id == project
        )
        linked_tasks = (
            select(IdeaTaskAction.idea_id)
            .join(Task, (Task.id == IdeaTaskAction.task_id) & (Task.user_id == owner))
            .where(IdeaTaskAction.user_id == owner, Task.project_id == project)
        )
        q = q.where(
            or_(
                ResearchIdea.project_id == project,
                ResearchIdea.id.in_(linked_briefs),
                ResearchIdea.id.in_(linked_tasks),
            )
        )
    if status:
        q = q.where(ResearchIdea.status == status)
    found = list(
        db.scalars(
            q.order_by(ResearchIdea.created_at.desc(), ResearchIdea.id.desc()).limit(limit + 1)
        )
    )
    return found[:limit], encode_cursor(found[limit - 1].created_at, found[limit - 1].id) if len(
        found
    ) > limit else None


def write_revision(
    db: Session, row: ResearchIdea, body: IdeaCreate | IdeaRevise, prior: IdeaRevision | None
) -> IdeaRevision:
    if not body.title.strip():
        raise DomainError("VALIDATION_ERROR", "Idea title must contain text", 422)
    rev = IdeaRevision(
        id=uuid.uuid4(),
        idea_id=row.id,
        user_id=row.user_id,
        revision=row.revision,
        sha256="0" * 64,
        **{
            key: getattr(prior, key)
            if prior is not None and key not in body.model_fields_set
            else getattr(body, key)
            for key in FIELDS
        },
    )
    db.add(rev)
    db.flush()
    selected = body.sources
    total = 0
    if selected is None:
        assert prior is not None
        frozen = [
            IdeaSource(revision_id=rev.id, idea_id=row.id, user_id=row.user_id, **source_values(s))
            for s in sources(db, prior)
        ]
    else:
        frozen = []
        seen = set()
        for selection in selected:
            marker = (selection.canonical_note_id, selection.start_offset, selection.end_offset)
            if marker in seen:
                raise DomainError("VALIDATION_ERROR", "Duplicate idea excerpt", 422)
            seen.add(marker)
            note = db.scalar(
                select(CanonicalAnalyticalNote).where(
                    CanonicalAnalyticalNote.id == selection.canonical_note_id,
                    CanonicalAnalyticalNote.user_id == row.user_id,
                )
            )
            if note is None:
                raise DomainError("NOT_FOUND", "Owned canonical note not found", 404)
            require_selectable_job(db, row.user_id, note.job_id)
            plan = db.scalar(
                select(PaperReadingApprovalPlan).where(
                    PaperReadingApprovalPlan.id == note.plan_id,
                    PaperReadingApprovalPlan.user_id == row.user_id,
                )
            )
            if plan is None:
                raise DomainError("NOT_FOUND", "Owned reading source not found", 404)
            material = canonical.material(db, row.user_id, plan.paper_id, note.id)
            if (
                material.note.sha256 != selection.expected_note_sha256
                or selection.end_offset > len(material.note.markdown)
                or material.note.markdown[selection.start_offset : selection.end_offset]
                != selection.exact_quote
            ):
                raise DomainError(
                    "IDEA_QUOTE_CHANGED", "Exact Unicode excerpt or canonical SHA differs", 409
                )
            facts = material.identity()
            frozen.append(
                IdeaSource(
                    revision_id=rev.id,
                    idea_id=row.id,
                    user_id=row.user_id,
                    canonical_note_id=note.id,
                    paper_id=plan.paper_id,
                    paper_title=material.paper.title,
                    reading_job_id=note.job_id,
                    reading_plan_id=plan.id,
                    note_sha256=note.sha256,
                    source_sha256=briefs.digest(facts),
                    source_facts=facts,
                    start_offset=selection.start_offset,
                    end_offset=selection.end_offset,
                    exact_quote=selection.exact_quote,
                )
            )
    for s in frozen:
        total += len(s.exact_quote.encode())
    if total > 262144:
        raise DomainError(
            "IDEA_QUOTES_TOO_LARGE",
            "Selected excerpts exceed 256 KiB UTF-8; nothing was truncated",
            422,
        )
    db.add_all(frozen)
    db.flush()
    names = tags(db, prior) if body.tags is None and prior else body.tags or []
    normalized_names: dict[str, str] = {}
    for name in names:
        clean = name.strip().lstrip("#")
        if not 1 <= len(clean) <= 80:
            raise DomainError("VALIDATION_ERROR", "Idea tags require 1 to 80 characters", 422)
        normalized_names.setdefault(clean.casefold(), clean)
    db.execute(delete(EntityTag).where(EntityTag.entity_id == row.id))
    for normalized, clean in normalized_names.items():
        db.add(
            IdeaRevisionTag(
                revision_id=rev.id,
                idea_id=row.id,
                user_id=row.user_id,
                name=clean,
                normalized_name=normalized,
            )
        )
        tag = db.scalar(
            select(Tag).where(Tag.user_id == row.user_id, Tag.normalized_name == normalized)
        )
        if tag is None:
            tag = Tag(id=uuid.uuid4(), user_id=row.user_id, name=clean, normalized_name=normalized)
            db.add(tag)
            db.flush()
        db.add(EntityTag(entity_id=row.id, tag_id=tag.id))
    db.flush()
    rev.sha256 = briefs.digest(snapshot(db, rev))
    row.title = rev.title
    row.content = rev.content
    row.status = rev.status
    return rev


def lookup(db: Session, owner: uuid.UUID, key: str) -> ResearchIdea:
    found = db.scalar(
        select(ResearchIdea)
        .where(ResearchIdea.user_id == owner, ResearchIdea.create_key == key)
        .execution_options(populate_existing=True)
    )
    if found is None:
        raise DomainError("NOT_FOUND", "No owned idea capture found for this key", 404)
    return found


def create(db: Session, owner: uuid.UUID, body: IdeaCreate) -> ResearchIdea:
    create_sha = briefs.digest(body.model_dump(mode="json")) if body.idempotency_key else None
    if body.idempotency_key:
        existing = db.scalar(
            select(ResearchIdea)
            .where(ResearchIdea.user_id == owner, ResearchIdea.create_key == body.idempotency_key)
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            if existing.create_sha256 != create_sha:
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT", "Idea capture key was used with different input", 409
                )
            return existing
    if body.project_id:
        get_project(db, owner, body.project_id)
    row = ResearchIdea(
        id=register_entity(db, owner, "idea"),
        user_id=owner,
        project_id=body.project_id,
        revision=1,
        create_key=body.idempotency_key,
        create_sha256=create_sha,
        title=body.title,
        content=body.content,
        status=body.status,
    )
    try:
        db.add(row)
        db.flush()
        write_revision(db, row, body, None)
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        if body.idempotency_key:
            existing = lookup(db, owner, body.idempotency_key)
            if existing.create_sha256 == create_sha:
                return existing
        raise DomainError(
            "IDEMPOTENCY_CONFLICT", "Another capture used this key; inspect before retry", 409
        ) from None
    except Exception:
        db.rollback()
        raise
    return row


def revise(db: Session, owner: uuid.UUID, identity: uuid.UUID, body: IdeaRevise) -> ResearchIdea:
    row = get(db, owner, identity, lock=True)
    prior = latest(db, row)
    if prior.sha256 != body.expected_revision_sha256 or not intact(db, prior):
        raise DomainError(
            "IDEA_REVISION_CHANGED", "Reload the current intact idea revision before saving", 409
        )
    try:
        row.revision += 1
        write_revision(db, row, body, prior)
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "IDEA_REVISION_CHANGED", "Another revision won; reload before saving", 409
        ) from None
    except Exception:
        db.rollback()
        raise
    return row


def list_sources(
    db: Session, owner: uuid.UUID, paper: uuid.UUID | None, limit: int, cursor: str | None
) -> ReproductionSourcePage:
    if paper:
        return canonical.list_sources(db, owner, paper, limit, cursor)
    q = (
        select(CanonicalAnalyticalNote, PaperReadingApprovalPlan.paper_id)
        .join(
            PaperReadingApprovalPlan,
            (CanonicalAnalyticalNote.plan_id == PaperReadingApprovalPlan.id)
            & (PaperReadingApprovalPlan.user_id == owner),
        )
        .join(Paper, (Paper.id == PaperReadingApprovalPlan.paper_id) & (Paper.user_id == owner))
        .where(
            CanonicalAnalyticalNote.user_id == owner,
            cursor_filter(CanonicalAnalyticalNote, cursor),
            selectable_job_clause(owner, CanonicalAnalyticalNote.job_id),
        )
        .order_by(CanonicalAnalyticalNote.created_at.desc(), CanonicalAnalyticalNote.id.desc())
        .limit(limit + 1)
    )
    found = list(db.execute(q))
    return ReproductionSourcePage(
        items=[canonical._choice(db, owner, p, n) for n, p in found[:limit]],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(found[limit - 1][0].created_at, found[limit - 1][0].id)
            if len(found) > limit
            else None,
        ),
    )


def task(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, body: IdeaTaskCreate
) -> IdeaTaskAction:
    row = get(db, owner, identity, lock=True)
    request = briefs.digest(body.model_dump(mode="json"))
    existing = db.scalar(
        select(IdeaTaskAction).where(
            IdeaTaskAction.idea_id == row.id,
            IdeaTaskAction.user_id == owner,
            IdeaTaskAction.idempotency_key == body.idempotency_key,
        )
    )
    if existing:
        if existing.request_sha256 != request:
            raise DomainError("IDEMPOTENCY_CONFLICT", "Task key was used with different input", 409)
        return existing
    rev = require_current(db, row, body.expected_revision_sha256)
    project = body.project_id if "project_id" in body.model_fields_set else row.project_id
    if project:
        get_project(db, owner, project)
    if not body.title.strip():
        raise DomainError("VALIDATION_ERROR", "Task title must contain text", 422)
    try:
        t = Task(
            id=register_entity(db, owner, "task"),
            user_id=owner,
            project_id=project,
            title=body.title,
            description=body.description,
            category=body.category,
            status="todo",
            priority="medium",
        )
        db.add(t)
        db.flush()
        receipt = IdeaTaskAction(
            user_id=owner,
            idea_id=row.id,
            revision_id=rev.id,
            task_id=t.id,
            idempotency_key=body.idempotency_key,
            request_sha256=request,
            revision_sha256=rev.sha256,
        )
        db.add(receipt)
        db.commit()
        db.refresh(receipt)
        return receipt
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "IDEA_ACTION_CONFLICT", "Reload action receipts after concurrent request", 409
        ) from None


def brief_preview(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, body: IdeaBriefPreviewCreate
) -> IdeaBriefPreviewOut:
    row = get(db, owner, identity)
    rev = require_current(db, row, body.expected_revision_sha256)
    project = get_project(db, owner, body.target_project_id)
    base = db.scalar(
        select(ResearchBrief)
        .where(ResearchBrief.project_id == project.id, ResearchBrief.user_id == owner)
        .order_by(ResearchBrief.revision.desc())
        .limit(1)
    )
    if base:
        from app.services import brief_idea_sources

        for old_source in brief_idea_sources.rows(db, base):
            if (
                old_source.idea_id == row.id
                and old_source.revision_id != rev.id
                and not set(old_source.selected_sections.split(",")).issubset(body.sections)
            ):
                raise DomainError(
                    "IDEA_SECTION_REVIEW_REQUIRED",
                    "A changed idea revision must explicitly reselect all previously derived sections",
                    409,
                )
    mapping = {
        "intent": rev.problem or rev.content,
        "hypotheses": rev.hypothesis,
        "routes": rev.method,
        "resources": "\n\n".join(x for x in (rev.required_dataset, rev.required_hardware) if x),
        "decision": "\n\n".join(x for x in (rev.contribution, rev.review_note) if x),
        "stage_plan": rev.next_experiment,
        "related_work": "\n\n".join(s.exact_quote for s in sources(db, rev)),
        "protocol": None,
    }
    frozen = snapshot(db, rev)
    result = IdeaBriefPreviewOut(
        idea_id=row.id,
        revision_id=rev.id,
        revision_sha256=rev.sha256,
        target_project_id=project.id,
        project_version=project.version,
        base_brief_id=base.id if base else None,
        expected_base_sha256=base.sha256 if base else None,
        idea=rev.title,
        sections=[ResearchBriefSectionCreate(key=k, content=mapping[k]) for k in body.sections],
        source_snapshot=frozen,
        preview_sha256="0" * 64,
    )
    result.preview_sha256 = briefs.digest(
        result.model_dump(mode="json", exclude={"preview_sha256"})
    )
    return result


def brief_create(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, body: IdeaBriefCreate
) -> IdeaBriefAction:
    row = get(db, owner, identity, lock=True)
    request = briefs.digest(body.model_dump(mode="json"))
    existing = db.scalar(
        select(IdeaBriefAction).where(
            IdeaBriefAction.idea_id == row.id,
            IdeaBriefAction.user_id == owner,
            IdeaBriefAction.idempotency_key == body.idempotency_key,
        )
    )
    if existing:
        if existing.request_sha256 != request:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT", "Brief key was used with different input", 409
            )
        return existing
    preview = brief_preview(
        db,
        owner,
        identity,
        IdeaBriefPreviewCreate.model_validate(
            body.model_dump(exclude={"idempotency_key", "expected_preview_sha256"})
        ),
    )
    if preview.preview_sha256 != body.expected_preview_sha256:
        raise DomainError(
            "IDEA_PREVIEW_CHANGED",
            "Idea, target project or latest brief changed; preview again",
            409,
        )
    source = ResearchBriefIdeaSource(
        brief_id=uuid.uuid4(),
        idea_id=row.id,
        user_id=owner,
        project_id=body.target_project_id,
        revision_id=preview.revision_id,
        revision_sha256=preview.revision_sha256,
        snapshot=preview.source_snapshot,
        source_sha256=briefs.digest(preview.source_snapshot),
        selected_sections=",".join(body.sections),
    )
    try:
        brief = briefs.create_brief(
            db,
            owner,
            body.target_project_id,
            ResearchBriefCreate(
                idea=preview.idea,
                base_brief_id=preview.base_brief_id,
                expected_base_sha256=preview.expected_base_sha256,
                sections=preview.sections,
            ),
            commit=False,
            idea_sources=[source],
        )
        receipt = IdeaBriefAction(
            user_id=owner,
            idea_id=row.id,
            revision_id=preview.revision_id,
            brief_id=brief.id,
            project_id=brief.project_id,
            idempotency_key=body.idempotency_key,
            request_sha256=request,
        )
        db.add(receipt)
        db.commit()
        db.refresh(receipt)
        return receipt
    except Exception:
        db.rollback()
        raise
