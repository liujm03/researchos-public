import uuid
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    CodexTask,
    Paper,
    PaperAnalysisJob,
    PaperReading,
    PaperResearchNote,
    ResearchEntity,
    ResearchNoteSection,
    ResearchProject,
    Task,
)
from app.models_ideas import ResearchIdea
from app.schemas_dashboard import DashboardActivityDay, DashboardVisualization
from app.services.note_trash import selectable_job_clause


def visualization(
    db: Session, owner: uuid.UUID, zone_name: str, day: date
) -> DashboardVisualization:
    """Owner-only read model. No provider calls, inferred progress or stored counters."""
    zone = ZoneInfo(zone_name)
    first = day - timedelta(days=29)
    start = datetime.combine(first, time.min, zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)

    def entity_join(entity_id: InstrumentedAttribute[uuid.UUID]) -> ColumnElement[bool]:
        return and_(
            ResearchEntity.id == entity_id,
            ResearchEntity.user_id == owner,
            ResearchEntity.deleted_at.is_(None),
        )

    reading_state = func.coalesce(PaperReading.reading_status, "unread")
    reading = dict(
        db.execute(
            select(reading_state, func.count(Paper.id))
            .select_from(Paper)
            .join(ResearchEntity, entity_join(Paper.id))
            .outerjoin(
                PaperReading, and_(PaperReading.paper_id == Paper.id, PaperReading.user_id == owner)
            )
            .where(Paper.user_id == owner)
            .group_by(reading_state)
        ).all()
    )
    stages = dict(
        db.execute(
            select(ResearchProject.pipeline_stage, func.count())
            .join(ResearchEntity, entity_join(ResearchProject.id))
            .where(ResearchProject.user_id == owner, ResearchProject.status == "active")
            .group_by(ResearchProject.pipeline_stage)
        ).all()
    )
    note_paper = aliased(ResearchEntity)
    notes: int = (
        db.scalar(
            select(func.count(func.distinct(PaperResearchNote.paper_id)))
            .join(ResearchEntity, entity_join(PaperResearchNote.id))
            .join(Paper, and_(Paper.id == PaperResearchNote.paper_id, Paper.user_id == owner))
            .join(
                note_paper,
                and_(
                    note_paper.id == Paper.id,
                    note_paper.user_id == owner,
                    note_paper.deleted_at.is_(None),
                ),
            )
            .where(
                PaperResearchNote.user_id == owner,
                exists(
                    select(ResearchNoteSection.id).where(
                        ResearchNoteSection.note_id == PaperResearchNote.id,
                        func.length(func.trim(func.coalesce(ResearchNoteSection.body_markdown, "")))
                        > 0,
                    )
                ),
                selectable_job_clause(owner, PaperResearchNote.analysis_job_id),
            )
        )
        or 0
    )
    ideas: int = (
        db.scalar(
            select(func.count())
            .select_from(ResearchIdea)
            .join(ResearchEntity, entity_join(ResearchIdea.id))
            .where(ResearchIdea.user_id == owner)
        )
        or 0
    )
    ai: Counter[str] = Counter()
    tasks = dict(
        db.execute(
            select(Task.status, func.count())
            .join(ResearchEntity, entity_join(Task.id))
            .where(Task.user_id == owner)
            .group_by(Task.status)
        ).all()
    )
    for status, count in db.execute(
        select(CodexTask.status, func.count())
        .where(CodexTask.user_id == owner)
        .group_by(CodexTask.status)
    ):
        ai[status] += count
    for status, count in db.execute(
        select(PaperAnalysisJob.status, func.count())
        .where(
            PaperAnalysisJob.user_id == owner,
            PaperAnalysisJob.source_type == "PDF",
            selectable_job_clause(owner, PaperAnalysisJob.id),
        )
        .group_by(PaperAnalysisJob.status)
    ):
        ai[status] += count
    added: Counter[date] = Counter()
    completed: Counter[date] = Counter()

    def local_day(value: datetime) -> date:
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return aware.astimezone(zone).date()

    for timestamp in db.scalars(
        select(Paper.created_at)
        .join(ResearchEntity, entity_join(Paper.id))
        .where(Paper.user_id == owner, Paper.created_at >= start, Paper.created_at < end)
    ):
        added[local_day(timestamp)] += 1
    for completed_at in db.scalars(
        select(Task.completed_at)
        .join(ResearchEntity, entity_join(Task.id))
        .where(Task.user_id == owner, Task.completed_at >= start, Task.completed_at < end)
    ):
        if completed_at is not None:
            completed[local_day(completed_at)] += 1
    active = {"QUEUED", "RUNNING", "ANALYZING", "CANCEL_REQUESTED"}
    attention = {
        "FAILED",
        "WAITING_CONFIG",
        "WAITING_BUDGET",
        "WAITING_PROVIDER_QUOTA",
        "WAITING_OWNER_ACK",
        "UNKNOWN",
        "NEEDS_RECONCILIATION",
        "NEEDS_ATTENTION",
    }
    return DashboardVisualization(
        observed_at=datetime.now(UTC),
        from_date=first,
        to_date=day,
        papers_total=sum(reading.values()),
        papers_with_notes=notes,
        projects_active=sum(stages.values()),
        ideas_total=ideas,
        tasks_open=sum(tasks.get(status, 0) for status in ("todo", "in_progress", "blocked")),
        tasks_completed=tasks.get("done", 0),
        ai_active=sum(ai[status] for status in active),
        ai_attention=sum(ai[status] for status in attention),
        reading_status_counts=reading,
        project_stage_counts=stages,
        ai_status_counts=dict(ai),
        activity=[
            DashboardActivityDay(
                date=first + timedelta(days=offset),
                papers_added=added[first + timedelta(days=offset)],
                tasks_completed=completed[first + timedelta(days=offset)],
            )
            for offset in range(30)
        ],
    )
