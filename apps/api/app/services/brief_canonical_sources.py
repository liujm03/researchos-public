"""DB-only complete canonical notes explicitly selected into immutable briefs."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import Paper
from app.models_analytical import CanonicalAnalyticalNote, PaperReadingApprovalPlan
from app.models_research_briefs import ResearchBrief, ResearchBriefCanonicalSource
from app.schemas import PageMeta
from app.schemas_research_briefs import (
    ResearchBriefCanonicalChoiceOut,
    ResearchBriefCanonicalSelection,
    ResearchBriefCanonicalSourceOut,
    ResearchBriefCanonicalSourcePage,
)
from app.services import canonical_reproduction
from app.services.common import cursor_filter, encode_cursor
from app.services.note_trash import require_selectable_job, selectable_job_clause
from app.services.project_note_scope import canonical_in_project, canonical_note_project_clause
from app.services.projects import get_project

MAX_TOTAL_BYTES = 1024 * 1024
MAX_NOTE_CHARACTERS = 524288


def rows(db: Session, brief: ResearchBrief) -> list[ResearchBriefCanonicalSource]:
    return list(
        db.scalars(
            select(ResearchBriefCanonicalSource)
            .where(
                ResearchBriefCanonicalSource.brief_id == brief.id,
                ResearchBriefCanonicalSource.user_id == brief.user_id,
                ResearchBriefCanonicalSource.project_id == brief.project_id,
            )
            .order_by(ResearchBriefCanonicalSource.canonical_note_id)
            .execution_options(populate_existing=True)
        )
    )


def values(row: ResearchBriefCanonicalSource) -> dict[str, Any]:
    return {
        key: getattr(row, key)
        for key in (
            "canonical_note_id",
            "paper_id",
            "reading_job_id",
            "reading_plan_id",
            "pdf_attachment_id",
            "paper_title",
            "note_sha256",
            "markdown",
            "source_scope",
            "note_origin",
            "source_facts",
            "source_sha256",
        )
    }


def intact(row: ResearchBriefCanonicalSource) -> bool:
    from app.services.research_briefs import digest

    return (
        canonical_reproduction.sha(row.markdown) == row.note_sha256
        and digest(row.source_facts) == row.source_sha256
        and row.source_facts.get("canonical_note_id") == str(row.canonical_note_id)
        and row.source_facts.get("paper_id") == str(row.paper_id)
        and row.source_facts.get("reading_job_id") == str(row.reading_job_id)
        and row.source_facts.get("reading_plan_id") == str(row.reading_plan_id)
        and row.source_facts.get("pdf_attachment_id") == str(row.pdf_attachment_id)
        and row.source_facts.get("note_sha256") == row.note_sha256
        and row.source_facts.get("paper_title") == row.paper_title
        and row.source_scope == "DERIVED_NOTE"
        and row.note_origin == "AI_DERIVED"
    )


def current(db: Session, row: ResearchBriefCanonicalSource) -> bool:
    if not intact(row):
        return False
    if not canonical_in_project(
        db, row.user_id, row.canonical_note_id, row.project_id, row.paper_id
    ):
        return False
    try:
        material = canonical_reproduction.material(
            db, row.user_id, row.paper_id, row.canonical_note_id
        )
        return material.identity() == row.source_facts and material.note.markdown == row.markdown
    except DomainError:
        return False


def freeze(
    db: Session, brief: ResearchBrief, selections: list[ResearchBriefCanonicalSelection]
) -> list[ResearchBriefCanonicalSource]:
    from app.services.research_briefs import digest

    result = []
    total = 0
    for selected in selections:
        note = db.scalar(
            select(CanonicalAnalyticalNote)
            .where(
                CanonicalAnalyticalNote.id == selected.canonical_note_id,
                CanonicalAnalyticalNote.user_id == brief.user_id,
            )
            .execution_options(populate_existing=True)
        )
        if note is None:
            raise DomainError("NOT_FOUND", "Owned canonical note not found", 404)
        require_selectable_job(db, brief.user_id, note.job_id)
        plan = db.scalar(
            select(PaperReadingApprovalPlan).where(
                PaperReadingApprovalPlan.id == note.plan_id,
                PaperReadingApprovalPlan.user_id == brief.user_id,
            )
        )
        if plan is None or not canonical_in_project(
            db, brief.user_id, note.id, brief.project_id, plan.paper_id
        ):
            raise DomainError(
                "BRIEF_NOTE_NOT_LINKED",
                "Classify this reading note under the project before selection",
                409,
            )
        material = canonical_reproduction.material(db, brief.user_id, plan.paper_id, note.id)
        if material.note.sha256 != selected.expected_note_sha256:
            raise DomainError("BRIEF_NOTE_CHANGED", "Canonical note differs from selected SHA", 409)
        total += len(material.note.markdown.encode("utf-8"))
        if len(material.note.markdown) > MAX_NOTE_CHARACTERS or total > MAX_TOTAL_BYTES:
            raise DomainError(
                "BRIEF_NOTES_TOO_LARGE",
                "Selected exact Markdown exceeds 524288 characters per note or 1 MiB total UTF-8. Nothing was truncated.",
                422,
            )
        facts = material.identity()
        result.append(
            ResearchBriefCanonicalSource(
                brief_id=brief.id,
                project_id=brief.project_id,
                user_id=brief.user_id,
                canonical_note_id=note.id,
                paper_id=plan.paper_id,
                reading_job_id=material.job.id,
                reading_plan_id=plan.id,
                pdf_attachment_id=material.attachment.id,
                paper_title=material.paper.title,
                note_sha256=material.note.sha256,
                markdown=material.note.markdown,
                source_scope="DERIVED_NOTE",
                note_origin="AI_DERIVED",
                source_facts=facts,
                source_sha256=digest(facts),
            )
        )
    return result


def out(db: Session, row: ResearchBriefCanonicalSource) -> ResearchBriefCanonicalSourceOut:
    is_current = current(db, row)
    gaps = list(row.source_facts.get("provenance_gaps", []))
    if not intact(row):
        gaps.append("CANONICAL_SNAPSHOT_INVALID")
    if not is_current:
        gaps.append("CANONICAL_SOURCE_CHANGED")
    return ResearchBriefCanonicalSourceOut(
        canonical_note_id=row.canonical_note_id,
        paper_id=row.paper_id,
        paper_title=row.paper_title,
        note_sha256=row.note_sha256,
        note_characters=len(row.markdown),
        note_bytes=len(row.markdown.encode()),
        created_at=row.created_at,
        can_select=is_current,
        gaps=gaps,
        markdown=row.markdown,
        reading_job_id=row.reading_job_id,
        reading_plan_id=row.reading_plan_id,
        source_facts=row.source_facts,
        context_current=is_current,
    )


def list_sources(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    paper_id: uuid.UUID | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> ResearchBriefCanonicalSourcePage:
    get_project(db, owner, project)
    query = (
        select(CanonicalAnalyticalNote, Paper)
        .join(
            PaperReadingApprovalPlan,
            (PaperReadingApprovalPlan.id == CanonicalAnalyticalNote.plan_id)
            & (PaperReadingApprovalPlan.user_id == owner),
        )
        .join(Paper, (Paper.id == PaperReadingApprovalPlan.paper_id) & (Paper.user_id == owner))
        .where(
            CanonicalAnalyticalNote.user_id == owner,
            selectable_job_clause(owner, CanonicalAnalyticalNote.job_id),
            canonical_note_project_clause(db, owner, project),
            cursor_filter(CanonicalAnalyticalNote, cursor),
        )
    )
    if paper_id is not None:
        query = query.where(Paper.id == paper_id)
    found = list(
        db.execute(
            query.order_by(
                CanonicalAnalyticalNote.created_at.desc(), CanonicalAnalyticalNote.id.desc()
            ).limit(limit + 1)
        ).all()
    )
    result = []
    for note, paper in found[:limit]:
        gaps = []
        try:
            canonical_reproduction.material(db, owner, paper.id, note.id)
        except DomainError as exc:
            gaps.append(exc.code)
        if (
            len(note.markdown) > MAX_NOTE_CHARACTERS
            or len(note.markdown.encode()) > MAX_TOTAL_BYTES
        ):
            gaps.append("BRIEF_NOTES_TOO_LARGE")
        result.append(
            ResearchBriefCanonicalChoiceOut(
                canonical_note_id=note.id,
                paper_id=paper.id,
                paper_title=paper.title,
                note_sha256=note.sha256,
                note_characters=len(note.markdown),
                note_bytes=len(note.markdown.encode()),
                created_at=note.created_at,
                can_select=not gaps,
                gaps=gaps,
            )
        )
    return ResearchBriefCanonicalSourcePage(
        items=result,
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(found[limit - 1][0].created_at, found[limit - 1][0].id)
            if len(found) > limit
            else None,
        ),
    )
