import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Paper, PaperReading, ResearchProject, Task, TimeEntry
from app.schemas import (
    AnalyticsOverview,
    DashboardOut,
    DashboardPaper,
    DashboardProject,
    DashboardTask,
    HeatmapDay,
    HeatmapOut,
)
from app.services.dashboard_visualization import visualization


def _bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
    return start, end


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _minutes_in_window(
    db: Session,
    user_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> int:
    entries = db.scalars(
        select(TimeEntry).where(
            TimeEntry.user_id == user_id,
            TimeEntry.started_at < end,
            TimeEntry.ended_at > start,
        )
    )
    return round(
        sum(
            (
                min(_as_utc(entry.ended_at), end) - max(_as_utc(entry.started_at), start)
            ).total_seconds()
            / 60
            for entry in entries
        )
    )


def dashboard(db: Session, user_id: uuid.UUID, zone_name: str, day: date) -> DashboardOut:
    zone = ZoneInfo(zone_name)
    today_start, today_end = _bounds(day, zone)
    week_start, _ = _bounds(day - timedelta(days=day.weekday()), zone)
    month_start, _ = _bounds(day.replace(day=1), zone)
    today_tasks = list(
        db.scalars(
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.due_at >= today_start,
                Task.due_at < today_end,
                Task.status != "cancelled",
            )
            .order_by(Task.due_at, Task.id)
            .limit(20)
        )
    )
    projects = list(
        db.scalars(
            select(ResearchProject)
            .where(ResearchProject.user_id == user_id, ResearchProject.status == "active")
            .order_by(ResearchProject.updated_at.desc())
            .limit(5)
        )
    )
    recent = db.execute(
        select(Paper, PaperReading)
        .join(PaperReading, PaperReading.paper_id == Paper.id)
        .where(Paper.user_id == user_id, PaperReading.user_id == user_id)
        .order_by(PaperReading.last_read_at.desc().nullslast(), Paper.created_at.desc())
        .limit(5)
    ).all()
    papers_read_total = (
        db.scalar(
            select(func.count())
            .select_from(PaperReading)
            .where(
                PaperReading.user_id == user_id,
                PaperReading.reading_status.in_(
                    ["reading", "deep_reading", "reproducing", "completed"]
                ),
            )
        )
        or 0
    )
    tasks_completed = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user_id, Task.status == "done")
        )
        or 0
    )
    tasks_open = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user_id, Task.status.in_(["todo", "in_progress", "blocked"]))
        )
        or 0
    )
    return DashboardOut(
        date=day,
        timezone=zone_name,
        today_tasks=[
            DashboardTask(
                id=task.id,
                title=task.title,
                category=task.category,
                status=task.status,
                due_at=task.due_at,
                project_id=task.project_id,
            )
            for task in today_tasks
        ],
        current_projects=[
            DashboardProject(
                id=project.id,
                name=project.name,
                pipeline_stage=project.pipeline_stage,
                status=project.status,
            )
            for project in projects
        ],
        recent_papers=[
            DashboardPaper(
                id=paper.id,
                title=paper.title,
                year=paper.year,
                reading_status=reading.reading_status,
                importance=reading.importance,
                relevance=reading.relevance,
                last_read_at=reading.last_read_at,
            )
            for paper, reading in recent
        ],
        papers_read_total=papers_read_total,
        research_minutes_week=_minutes_in_window(db, user_id, week_start, today_end),
        research_minutes_month=_minutes_in_window(db, user_id, month_start, today_end),
        tasks_completed=tasks_completed,
        tasks_open=tasks_open,
        visualization=visualization(db, user_id, zone_name, day),
    )


def overview(
    db: Session, user_id: uuid.UUID, zone_name: str, first: date, last: date
) -> AnalyticsOverview:
    zone = ZoneInfo(zone_name)
    start, _ = _bounds(first, zone)
    _, end = _bounds(last, zone)
    minutes: dict[str, int] = defaultdict(int)
    for entry in db.scalars(
        select(TimeEntry).where(
            TimeEntry.user_id == user_id,
            TimeEntry.started_at < end,
            TimeEntry.ended_at > start,
        )
    ):
        minutes[entry.category] += round(
            (
                min(_as_utc(entry.ended_at), end) - max(_as_utc(entry.started_at), start)
            ).total_seconds()
            / 60
        )
    papers_completed = (
        db.scalar(
            select(func.count())
            .select_from(PaperReading)
            .where(
                PaperReading.user_id == user_id,
                PaperReading.completed_at >= start,
                PaperReading.completed_at < end,
            )
        )
        or 0
    )
    tasks_completed = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user_id, Task.completed_at >= start, Task.completed_at < end)
        )
        or 0
    )
    projects_active = (
        db.scalar(
            select(func.count())
            .select_from(ResearchProject)
            .where(ResearchProject.user_id == user_id, ResearchProject.status == "active")
        )
        or 0
    )
    return AnalyticsOverview(
        from_date=first,
        to_date=last,
        research_minutes_by_category=dict(minutes),
        papers_completed=papers_completed,
        tasks_completed=tasks_completed,
        projects_active=projects_active,
    )


def heatmap(db: Session, user_id: uuid.UUID, zone_name: str, year: int, measure: str) -> HeatmapOut:
    zone = ZoneInfo(zone_name)
    first = date(year, 1, 1)
    last = date(year, 12, 31)
    start, _ = _bounds(first, zone)
    _, end = _bounds(last, zone)
    values: dict[date, float] = defaultdict(float)
    if measure == "hours":
        entries = db.scalars(
            select(TimeEntry).where(
                TimeEntry.user_id == user_id,
                TimeEntry.started_at < end,
                TimeEntry.ended_at > start,
            )
        )
        for entry in entries:
            entry_start = _as_utc(entry.started_at)
            entry_end = _as_utc(entry.ended_at)
            cursor = max(entry_start.astimezone(zone).date(), first)
            final = min(entry_end.astimezone(zone).date(), last)
            while cursor <= final:
                day_start, day_end = _bounds(cursor, zone)
                overlap = max(
                    0.0,
                    (min(entry_end, day_end) - max(entry_start, day_start)).total_seconds(),
                )
                values[cursor] += overlap / 3600
                cursor += timedelta(days=1)
        unit = "hours"
    else:
        for completed_at in db.scalars(
            select(Task.completed_at).where(
                Task.user_id == user_id,
                Task.completed_at >= start,
                Task.completed_at < end,
            )
        ):
            if completed_at is not None:
                values[_as_utc(completed_at).astimezone(zone).date()] += 1
        for read_at in db.scalars(
            select(PaperReading.last_read_at).where(
                PaperReading.user_id == user_id,
                PaperReading.last_read_at >= start,
                PaperReading.last_read_at < end,
            )
        ):
            if read_at is not None:
                values[_as_utc(read_at).astimezone(zone).date()] += 1
        unit = "events"
    days: list[HeatmapDay] = []
    cursor = first
    while cursor <= last:
        value = round(values[cursor], 2)
        thresholds = (0, 0.5, 1, 2, 4) if measure == "hours" else (0, 1, 2, 3, 5)
        level = sum(value >= threshold for threshold in thresholds[1:]) if value > 0 else 0
        days.append(HeatmapDay(date=cursor, value=value, level=min(level + (value > 0), 5)))
        cursor += timedelta(days=1)
    return HeatmapOut(year=year, measure=measure, unit=unit, days=days)
