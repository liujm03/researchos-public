import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import Paper, PaperReading, ResearchJournal, Task, TaskDependency, TimeEntry
from app.schemas import JournalUpdate, TaskCreate, TaskPatch, TimeEntryCreate
from app.services.common import assert_version, cursor_filter, encode_cursor, register_entity
from app.services.projects import get_project


def get_task(db: Session, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    if task is None:
        raise DomainError("NOT_FOUND", "Task not found", 404)
    return task


def _validate_task_links(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None,
    parent_task_id: uuid.UUID | None,
    current_id: uuid.UUID | None = None,
) -> None:
    if project_id:
        get_project(db, user_id, project_id)
    if parent_task_id:
        parent: Task | None = get_task(db, user_id, parent_task_id)
        seen = {current_id} if current_id else set()
        while parent is not None:
            if parent.id in seen:
                raise DomainError("VALIDATION_ERROR", "Task tree cannot contain a cycle", 422)
            seen.add(parent.id)
            parent = get_task(db, user_id, parent.parent_task_id) if parent.parent_task_id else None


def create_task(db: Session, user_id: uuid.UUID, data: TaskCreate) -> Task:
    _validate_task_links(db, user_id, data.project_id, data.parent_task_id)
    item_id = register_entity(db, user_id, "task")
    values = data.model_dump()
    if data.due_at is not None:
        if data.due_at.tzinfo is None:
            raise DomainError("VALIDATION_ERROR", "due_at requires a timezone offset", 422)
        values["due_at"] = data.due_at.astimezone(UTC)
    if data.status == "done":
        values["completed_at"] = datetime.now(UTC)
    task = Task(id=item_id, user_id=user_id, **values)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def list_tasks(
    db: Session,
    user_id: uuid.UUID,
    limit: int,
    cursor: str | None,
    status: str | None,
    project_id: uuid.UUID | None,
) -> tuple[list[Task], str | None]:
    query = select(Task).where(Task.user_id == user_id, cursor_filter(Task, cursor))
    if status:
        query = query.where(Task.status == status)
    if project_id:
        get_project(db, user_id, project_id)
        query = query.where(Task.project_id == project_id)
    rows = list(db.scalars(query.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit + 1)))
    next_cursor = (
        encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    )
    return rows[:limit], next_cursor


def update_task(
    db: Session,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    data: TaskPatch,
    if_match: str | None,
) -> Task:
    task = get_task(db, user_id, task_id)
    assert_version(task.version, if_match)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("due_at") is not None:
        if changes["due_at"].tzinfo is None:
            raise DomainError("VALIDATION_ERROR", "due_at requires a timezone offset", 422)
        changes["due_at"] = changes["due_at"].astimezone(UTC)
    for required in ("title", "category", "priority", "status"):
        if required in changes and changes[required] is None:
            raise DomainError("VALIDATION_ERROR", f"{required} cannot be null", 422)
    _validate_task_links(
        db,
        user_id,
        changes.get("project_id", task.project_id),
        changes.get("parent_task_id", task.parent_task_id),
        task_id,
    )
    if changes.get("status") == "done" and task.status != "done":
        changes["completed_at"] = datetime.now(UTC)
    elif "status" in changes and changes["status"] != "done":
        changes["completed_at"] = None
    for key, value in changes.items():
        setattr(task, key, value)
    task.version += 1
    task.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(task)
    return task


def _dependency_reaches(db: Session, start: uuid.UUID, target: uuid.UUID) -> bool:
    stack = [start]
    visited: set[uuid.UUID] = set()
    while stack:
        item = stack.pop()
        if item == target:
            return True
        if item in visited:
            continue
        visited.add(item)
        stack.extend(
            db.scalars(
                select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == item)
            )
        )
    return False


def add_dependency(
    db: Session, user_id: uuid.UUID, task_id: uuid.UUID, depends_on_id: uuid.UUID
) -> None:
    get_task(db, user_id, task_id)
    get_task(db, user_id, depends_on_id)
    if task_id == depends_on_id or _dependency_reaches(db, depends_on_id, task_id):
        raise DomainError("VALIDATION_ERROR", "Task dependencies cannot contain a cycle", 422)
    if db.get(TaskDependency, (task_id, depends_on_id)) is None:
        db.add(TaskDependency(task_id=task_id, depends_on_task_id=depends_on_id))
        db.commit()


def get_journal(db: Session, user_id: uuid.UUID, journal_date: date) -> ResearchJournal | None:
    return db.scalar(
        select(ResearchJournal).where(
            ResearchJournal.user_id == user_id, ResearchJournal.journal_date == journal_date
        )
    )


def upsert_journal(
    db: Session,
    user_id: uuid.UUID,
    journal_date: date,
    data: JournalUpdate,
    if_match: str | None,
) -> ResearchJournal:
    journal = get_journal(db, user_id, journal_date)
    if journal is None:
        journal = ResearchJournal(user_id=user_id, journal_date=journal_date, **data.model_dump())
        db.add(journal)
    else:
        assert_version(journal.version, if_match)
        for key, value in data.model_dump().items():
            setattr(journal, key, value)
        journal.version += 1
        journal.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(journal)
    return journal


def journal_draft(
    db: Session, user_id: uuid.UUID, journal_date: date, timezone_name: str
) -> JournalUpdate:
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(journal_date, time.min, zone).astimezone(UTC)
    end = datetime.combine(journal_date + timedelta(days=1), time.min, zone).astimezone(UTC)
    finished = list(
        db.scalars(
            select(Task.title).where(
                Task.user_id == user_id,
                Task.completed_at >= start,
                Task.completed_at < end,
            )
        )
    )
    papers = list(
        db.scalars(
            select(Paper.title)
            .join(PaperReading, PaperReading.paper_id == Paper.id)
            .where(
                PaperReading.user_id == user_id,
                PaperReading.last_read_at >= start,
                PaperReading.last_read_at < end,
            )
        )
    )
    return JournalUpdate(
        completed="\n".join(f"- {title}" for title in finished) or None,
        papers_read="\n".join(f"- {title}" for title in papers) or None,
    )


def create_time_entry(db: Session, user_id: uuid.UUID, data: TimeEntryCreate) -> TimeEntry:
    if data.started_at.tzinfo is None or data.ended_at.tzinfo is None:
        raise DomainError("VALIDATION_ERROR", "Time entries require a timezone offset", 422)
    if data.ended_at <= data.started_at:
        raise DomainError("VALIDATION_ERROR", "ended_at must be after started_at", 422)
    if data.project_id:
        get_project(db, user_id, data.project_id)
    if data.task_id:
        get_task(db, user_id, data.task_id)
    values = data.model_dump()
    values["started_at"] = data.started_at.astimezone(UTC)
    values["ended_at"] = data.ended_at.astimezone(UTC)
    entry = TimeEntry(id=uuid.uuid4(), user_id=user_id, **values)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
