import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.models import Task, TaskDependency, TimeEntry
from app.schemas import (
    JournalOut,
    JournalUpdate,
    PageMeta,
    TaskCreate,
    TaskOut,
    TaskPage,
    TaskPatch,
    TimeEntryCreate,
    TimeEntryOut,
)
from app.services import productivity as service

router = APIRouter(tags=["productivity"])


@router.get("/tasks", response_model=TaskPage)
def list_tasks(
    status: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> TaskPage:
    rows, next_cursor = service.list_tasks(db, context.user.id, limit, cursor, status, project_id)
    return TaskPage(
        items=[TaskOut.model_validate(row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(
    body: TaskCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> TaskOut:
    return TaskOut.model_validate(service.create_task(db, context.user.id, body))


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(
    task_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> TaskOut:
    return TaskOut.model_validate(service.get_task(db, context.user.id, task_id))


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: uuid.UUID,
    body: TaskPatch,
    if_match: str | None = Header(default=None),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> TaskOut:
    return TaskOut.model_validate(service.update_task(db, context.user.id, task_id, body, if_match))


@router.delete("/tasks/{task_id}", status_code=204)
def cancel_task(
    task_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    task = service.get_task(db, context.user.id, task_id)
    task.status = "cancelled"
    task.version += 1
    db.commit()


class DependencyRequest(BaseModel):
    depends_on_task_id: uuid.UUID


@router.get("/tasks/{task_id}/dependencies", response_model=list[uuid.UUID])
def list_dependencies(
    task_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[uuid.UUID]:
    service.get_task(db, context.user.id, task_id)
    return list(
        db.scalars(
            select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == task_id)
        )
    )


@router.post("/tasks/{task_id}/dependencies", status_code=204)
def add_dependency(
    task_id: uuid.UUID,
    body: DependencyRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    service.add_dependency(db, context.user.id, task_id, body.depends_on_task_id)


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}", status_code=204)
def remove_dependency(
    task_id: uuid.UUID,
    depends_on_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    service.get_task(db, context.user.id, task_id)
    row = db.get(TaskDependency, (task_id, depends_on_id))
    if row:
        db.delete(row)
        db.commit()


@router.get("/journals/{journal_date}", response_model=JournalOut | None)
def get_journal(
    journal_date: date,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> JournalOut | None:
    journal = service.get_journal(db, context.user.id, journal_date)
    return JournalOut.model_validate(journal) if journal else None


@router.put("/journals/{journal_date}", response_model=JournalOut)
def upsert_journal(
    journal_date: date,
    body: JournalUpdate,
    if_match: str | None = Header(default=None),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> JournalOut:
    return JournalOut.model_validate(
        service.upsert_journal(db, context.user.id, journal_date, body, if_match)
    )


@router.post("/journals/{journal_date}/draft", response_model=JournalUpdate)
def journal_draft(
    journal_date: date,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> JournalUpdate:
    return service.journal_draft(db, context.user.id, journal_date, context.user.timezone)


@router.get("/time-entries", response_model=list[TimeEntryOut])
def list_time_entries(
    start: datetime | None = None,
    end: datetime | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[TimeEntryOut]:
    query = select(TimeEntry).where(TimeEntry.user_id == context.user.id)
    if start:
        query = query.where(TimeEntry.ended_at > start)
    if end:
        query = query.where(TimeEntry.started_at < end)
    rows = db.scalars(query.order_by(TimeEntry.started_at.desc()).limit(100))
    return [TimeEntryOut.model_validate(row) for row in rows]


@router.post("/time-entries", response_model=TimeEntryOut, status_code=201)
def create_time_entry(
    body: TimeEntryCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> TimeEntryOut:
    return TimeEntryOut.model_validate(service.create_time_entry(db, context.user.id, body))


@router.get("/calendar")
def calendar(
    start: date,
    end: date,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[dict[str, str]]:
    if (end - start).days > 366 or end < start:
        raise DomainError("VALIDATION_ERROR", "Calendar range must be within one year", 422)
    zone = ZoneInfo(context.user.timezone)
    start_at = datetime.combine(start, time.min, zone).astimezone(UTC)
    end_at = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(UTC)
    rows = db.scalars(
        select(Task).where(
            Task.user_id == context.user.id,
            Task.due_at >= start_at,
            Task.due_at < end_at,
            Task.status != "cancelled",
        )
    )
    events: list[dict[str, str]] = []
    for task in rows:
        if task.due_at is None:
            continue
        due_utc = (
            task.due_at.replace(tzinfo=UTC)
            if task.due_at.tzinfo is None
            else task.due_at.astimezone(UTC)
        )
        events.append(
            {
                "id": str(task.id),
                "type": "task",
                "title": task.title,
                "at": due_utc.isoformat(),
                "local_date": due_utc.astimezone(zone).date().isoformat(),
                "status": task.status,
            }
        )
    return events
