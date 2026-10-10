"""Exact idea snapshots selected into immutable briefs; old hashes stay unchanged."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_ideas import IdeaRevision, ResearchBriefIdeaSource, ResearchIdea
from app.models_research_briefs import ResearchBrief


def rows(db: Session, brief: ResearchBrief) -> list[ResearchBriefIdeaSource]:
    return list(
        db.scalars(
            select(ResearchBriefIdeaSource)
            .where(
                ResearchBriefIdeaSource.brief_id == brief.id,
                ResearchBriefIdeaSource.user_id == brief.user_id,
                ResearchBriefIdeaSource.project_id == brief.project_id,
            )
            .order_by(ResearchBriefIdeaSource.idea_id)
            .execution_options(populate_existing=True)
        )
    )


def values(row: ResearchBriefIdeaSource) -> dict[str, Any]:
    return {
        key: getattr(row, key)
        for key in (
            "idea_id",
            "revision_id",
            "revision_sha256",
            "snapshot",
            "source_sha256",
            "selected_sections",
        )
    }


def intact(row: ResearchBriefIdeaSource) -> bool:
    from app.services.research_briefs import digest

    return (
        digest(row.snapshot) == row.source_sha256
        and row.snapshot.get("idea_id") == str(row.idea_id)
        and row.snapshot.get("revision_id") == str(row.revision_id)
        and row.source_sha256 == row.revision_sha256
    )


def current(db: Session, row: ResearchBriefIdeaSource) -> bool:
    from app.services import ideas

    idea = db.scalar(
        select(ResearchIdea)
        .where(ResearchIdea.id == row.idea_id, ResearchIdea.user_id == row.user_id)
        .execution_options(populate_existing=True)
    )
    rev = db.scalar(
        select(IdeaRevision)
        .where(
            IdeaRevision.id == row.revision_id,
            IdeaRevision.idea_id == row.idea_id,
            IdeaRevision.user_id == row.user_id,
        )
        .execution_options(populate_existing=True)
    )
    return (
        intact(row)
        and idea is not None
        and rev is not None
        and idea.revision == rev.revision
        and rev.sha256 == row.revision_sha256
        and ideas.current(db, rev)
        and ideas.snapshot(db, rev) == row.snapshot
    )


def requires_note_permission(db: Session, brief: ResearchBrief) -> bool:
    return any(row.snapshot.get("sources") for row in rows(db, brief))
