"""Explicit, owner-scoped Codex task API."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.models import CodexTask, CodexTaskEvent
from app.schemas_codex_tasks import CodexTaskKind, CodexTaskMode, CodexTaskStatus
from app.schemas_codex_tasks import CodexTaskOut as CodexTaskOut
from app.services import codex_tasks as service

router = APIRouter(prefix="/codex", tags=["codex"])


class CodexCapabilitiesOut(BaseModel):
    provider: str
    enabled: bool
    available: bool
    sdk_installed: bool
    authenticated: bool
    workspace_count: int
    model_key: str | None
    reasoning_effort: str | None = None
    supports_cancel: bool
    max_tokens_per_task: int | None
    budget_mode: Literal["LOCAL_LIMITS", "PROVIDER_QUOTA"] = "LOCAL_LIMITS"
    token_limit_is_soft: bool
    reason: str | None


class CodexWorkspaceOut(BaseModel):
    id: str
    name: str
    path: str
    allowed_modes: list[CodexTaskMode]
    available: bool
    reason: str | None
    write_available: bool
    write_reason: str | None


class CodexTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    prompt: str = Field(min_length=1, max_length=40_000)
    kind: CodexTaskKind = "general"
    mode: CodexTaskMode = "read_only"
    workspace_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    related_project_id: uuid.UUID | None = None
    related_research_question_id: uuid.UUID | None = None


class CodexTaskSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    kind: CodexTaskKind
    mode: CodexTaskMode
    workspace_id: str
    status: CodexTaskStatus
    created_at: datetime
    error: str | None


class CodexTaskEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    event_type: str
    message: str
    created_at: datetime


class CodexStartRequest(BaseModel):
    confirm_write: bool = False


@router.get("/capabilities", response_model=CodexCapabilitiesOut)
def capabilities(context: AuthContext = Depends(current_context)) -> CodexCapabilitiesOut:
    return CodexCapabilitiesOut.model_validate(service.codex_capabilities())


@router.get("/workspaces", response_model=list[CodexWorkspaceOut])
def workspaces(context: AuthContext = Depends(current_context)) -> list[CodexWorkspaceOut]:
    result = []
    for workspace in service.load_workspaces():
        available = workspace.path.is_dir()
        reason = None if available else "Configured directory does not exist"
        write_available = False
        write_reason: str | None = "Write mode is not allowed for this workspace"
        if "workspace_write" in workspace.allowed_modes:
            try:
                service.git_state(workspace.path, require_clean=True)
                write_available = True
                write_reason = None
            except DomainError as exc:
                write_reason = exc.message
        result.append(
            CodexWorkspaceOut(
                id=workspace.id,
                name=workspace.name,
                path=str(workspace.path),
                allowed_modes=list(workspace.allowed_modes),
                available=available,
                reason=reason,
                write_available=write_available,
                write_reason=write_reason,
            )
        )
    return result


@router.post("/tasks", response_model=CodexTaskOut, status_code=201)
def create_task(
    body: CodexTaskCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodexTaskOut:
    task = service.create_task(db, context.user.id, **body.model_dump())
    return CodexTaskOut.model_validate(task)


@router.get("/tasks", response_model=list[CodexTaskSummaryOut])
def list_tasks(
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[CodexTaskSummaryOut]:
    tasks = db.scalars(
        select(CodexTask)
        .where(CodexTask.user_id == context.user.id)
        .options(
            load_only(
                CodexTask.id,
                CodexTask.title,
                CodexTask.kind,
                CodexTask.mode,
                CodexTask.workspace_id,
                CodexTask.status,
                CodexTask.created_at,
                CodexTask.error,
            )
        )
        .order_by(CodexTask.created_at.desc(), CodexTask.id.desc())
        .limit(100)
    )
    return [CodexTaskSummaryOut.model_validate(task) for task in tasks]


@router.get("/tasks/{task_id}", response_model=CodexTaskOut)
def get_task(
    task_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> CodexTaskOut:
    return CodexTaskOut.model_validate(service.get_task(db, context.user.id, task_id))


@router.get("/tasks/{task_id}/events", response_model=list[CodexTaskEventOut])
def list_events(
    task_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[CodexTaskEventOut]:
    service.get_task(db, context.user.id, task_id)
    events = db.scalars(
        select(CodexTaskEvent)
        .where(CodexTaskEvent.task_id == task_id, CodexTaskEvent.user_id == context.user.id)
        .order_by(CodexTaskEvent.sequence)
        .limit(1000)
    )
    return [CodexTaskEventOut.model_validate(event) for event in events]


@router.post("/tasks/{task_id}/start", response_model=CodexTaskOut)
async def start_task(
    task_id: uuid.UUID,
    body: CodexStartRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodexTaskOut:
    return CodexTaskOut.model_validate(
        await service.start_task_with_sources(
            db, context.user.id, task_id, confirm_write=body.confirm_write
        )
    )


@router.post("/tasks/{task_id}/cancel", response_model=CodexTaskOut)
def cancel_task(
    task_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodexTaskOut:
    return CodexTaskOut.model_validate(service.cancel_task(db, context.user.id, task_id))
