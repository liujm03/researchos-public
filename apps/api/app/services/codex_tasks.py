"""Owner-scoped Codex task lifecycle and workspace policy."""

import hashlib
import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.errors import DomainError
from app.models import CodexTask, CodexTaskEvent, ResearchProject, ResearchQuestion
from app.providers.registry import codex_runtime_capabilities

CodexMode = Literal["read_only", "workspace_write"]
KINDS = {
    "general",
    "repository_analysis",
    "code_review",
    "bug_fix",
    "code_change",
    "test_generation",
    "experiment_script",
    "paper_reproduction",
    "writing",
}
MODES = {"read_only", "workspace_write"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "NEEDS_ATTENTION"}


@dataclass(frozen=True)
class AllowedWorkspace:
    id: str
    name: str
    path: Path
    allowed_modes: tuple[CodexMode, ...]


def load_workspaces() -> list[AllowedWorkspace]:
    try:
        raw = json.loads(get_settings().codex_workspaces_json)
        if not isinstance(raw, list):
            raise ValueError("expected an array")
        rows: list[AllowedWorkspace] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("workspace must be an object")
            workspace_id, path_text = item.get("id"), item.get("path")
            if not isinstance(workspace_id, str) or not re.fullmatch(
                r"[a-zA-Z0-9_-]{1,80}", workspace_id
            ):
                raise ValueError("workspace id is invalid")
            if workspace_id in seen:
                raise ValueError("workspace ids must be unique")
            if not isinstance(path_text, str) or not Path(path_text).is_absolute():
                raise ValueError("workspace path must be absolute")
            modes = item.get("allowed_modes", ["read_only"])
            if not isinstance(modes, list) or not modes or any(mode not in MODES for mode in modes):
                raise ValueError("allowed_modes must contain supported modes")
            name = item.get("name", workspace_id)
            if not isinstance(name, str) or not name.strip():
                raise ValueError("workspace name is invalid")
            rows.append(
                AllowedWorkspace(
                    id=workspace_id,
                    name=name.strip()[:120],
                    path=Path(path_text).resolve(),
                    allowed_modes=tuple(cast(CodexMode, mode) for mode in dict.fromkeys(modes)),
                )
            )
            seen.add(workspace_id)
        return rows
    except (ValueError, TypeError, OSError) as exc:
        raise DomainError(
            "CODEX_CONFIGURATION_INVALID", f"Invalid CODEX_WORKSPACES_JSON: {exc}", 503
        ) from exc


def workspace_by_id(workspace_id: str, mode: str | None = None) -> AllowedWorkspace:
    workspace = next((row for row in load_workspaces() if row.id == workspace_id), None)
    if workspace is None:
        raise DomainError("WORKSPACE_NOT_ALLOWED", "Workspace is not on the Codex allowlist", 422)
    if not workspace.path.is_dir():
        raise DomainError("WORKSPACE_UNAVAILABLE", "Configured workspace is unavailable", 503)
    if mode is not None and mode not in workspace.allowed_modes:
        raise DomainError(
            "MODE_NOT_ALLOWED", "This workspace does not allow the requested mode", 422
        )
    if mode == "workspace_write":
        git_state(workspace.path, require_clean=False)
    return workspace


def _git(path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=8,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise DomainError("GIT_UNAVAILABLE", "Git inspection failed", 503) from exc
    if result.returncode != 0:
        raise DomainError("GIT_UNAVAILABLE", "Git repository is unavailable or untrusted", 422)
    return result.stdout.strip()


def git_state(path: Path, *, require_clean: bool) -> str:
    top = Path(_git(path, "rev-parse", "--show-toplevel")).resolve()
    if top != path.resolve():
        raise DomainError(
            "GIT_ROOT_REQUIRED", "Write mode requires the allowlisted Git repository root", 422
        )
    commit = _git(path, "rev-parse", "HEAD")
    if require_clean and _git(path, "status", "--porcelain", "--untracked-files=normal"):
        raise DomainError("WORKSPACE_DIRTY", "Write mode requires a clean Git worktree", 409)
    return commit


def codex_capabilities() -> dict[str, Any]:
    settings = get_settings()
    enabled = settings.codex_provider == "openai_codex_sdk"
    runtime = codex_runtime_capabilities()
    reason = None
    if not enabled:
        reason = "Codex provider is disabled"
    elif not settings.codex_model.strip():
        reason = "CODEX_MODEL must name an explicit model for provenance"
    elif not 60 <= settings.codex_task_timeout_seconds <= 86_400:
        reason = "CODEX_TASK_TIMEOUT_SECONDS must be between 60 and 86400"
    elif settings.codex_budget_mode not in {"LOCAL_LIMITS", "PROVIDER_QUOTA"}:
        reason = "CODEX_BUDGET_MODE must be LOCAL_LIMITS or PROVIDER_QUOTA"
    elif (
        settings.codex_budget_mode == "LOCAL_LIMITS"
        and not 1_000 <= settings.codex_max_tokens_per_task <= 1_000_000
    ):
        reason = "CODEX_MAX_TOKENS_PER_TASK must be between 1000 and 1000000"
    elif runtime.reason:
        reason = runtime.reason
    try:
        workspaces = load_workspaces()
        count = len(workspaces)
        if reason is None and not any(workspace.path.is_dir() for workspace in workspaces):
            reason = "No accessible Codex workspace is configured"
    except DomainError as exc:
        count = 0
        reason = exc.message
    return {
        "provider": "openai_codex_sdk",
        "enabled": enabled,
        "available": enabled and runtime.sdk_installed and runtime.authenticated and reason is None,
        "sdk_installed": runtime.sdk_installed,
        "authenticated": runtime.authenticated,
        "workspace_count": count,
        "model_key": settings.codex_model or None,
        "reasoning_effort": settings.codex_reasoning_effort,
        "supports_cancel": True,
        "max_tokens_per_task": settings.codex_max_tokens_per_task
        if settings.codex_budget_mode == "LOCAL_LIMITS"
        else None,
        "budget_mode": settings.codex_budget_mode,
        "token_limit_is_soft": settings.codex_budget_mode == "LOCAL_LIMITS",
        "reason": reason,
    }


def append_event(db: Session, task: CodexTask, event_type: str, message: str) -> None:
    locked = db.scalar(select(CodexTask).where(CodexTask.id == task.id).with_for_update())
    if locked is None:
        raise DomainError("NOT_FOUND", "Codex task not found", 404)
    if locked.event_sequence >= 500 and event_type in {
        "item/completed",
        "item/started",
        "turn/started",
        "error",
    }:
        if locked.event_sequence == 500:
            locked.event_sequence += 1
            db.add(
                CodexTaskEvent(
                    task_id=task.id,
                    user_id=task.user_id,
                    sequence=locked.event_sequence,
                    event_type="EVENTS_TRUNCATED",
                    message="Further progress events omitted; terminal events remain recorded",
                )
            )
        return
    locked.event_sequence += 1
    db.add(
        CodexTaskEvent(
            task_id=task.id,
            user_id=task.user_id,
            sequence=locked.event_sequence,
            event_type=event_type[:80],
            message=message[:4000],
        )
    )


def get_task(db: Session, user_id: uuid.UUID, task_id: uuid.UUID) -> CodexTask:
    task = db.scalar(select(CodexTask).where(CodexTask.id == task_id, CodexTask.user_id == user_id))
    if task is None:
        raise DomainError("NOT_FOUND", "Codex task not found", 404)
    return task


def create_task(
    db: Session,
    user_id: uuid.UUID,
    *,
    title: str,
    prompt: str,
    kind: str,
    mode: CodexMode,
    workspace_id: str,
    idempotency_key: str | None,
    related_project_id: uuid.UUID | None,
    related_research_question_id: uuid.UUID | None,
    commit: bool = True,
    _paper_context: bool = False,
    _writing_context: bool = False,
) -> CodexTask:
    if kind == "writing" and (not _writing_context or commit):
        raise DomainError(
            "WRITING_PLAN_REQUIRED",
            "Create writing through a frozen professional Skill preview",
            422,
        )
    if kind == "paper_reproduction" and (not _paper_context or commit):
        raise DomainError(
            "REPRODUCTION_CONTEXT_REQUIRED",
            "Create paper reproduction through the paper source preview",
            422,
        )
    workspace = workspace_by_id(workspace_id, mode)
    if kind not in KINDS:
        raise DomainError("VALIDATION_ERROR", "Unknown Codex task kind", 422)
    if related_project_id is not None:
        project = db.scalar(
            select(ResearchProject).where(
                ResearchProject.id == related_project_id, ResearchProject.user_id == user_id
            )
        )
        if project is None:
            raise DomainError("NOT_FOUND", "Related project not found", 404)
    if related_research_question_id is not None:
        question = db.scalar(
            select(ResearchQuestion)
            .join(ResearchProject, ResearchQuestion.project_id == ResearchProject.id)
            .where(
                ResearchQuestion.id == related_research_question_id,
                ResearchProject.user_id == user_id,
            )
        )
        if question is None or (related_project_id and question.project_id != related_project_id):
            raise DomainError("NOT_FOUND", "Related research question not found", 404)
        if related_project_id is None:
            related_project_id = question.project_id
    payload = {
        "title": title,
        "prompt": prompt,
        "kind": kind,
        "mode": mode,
        "workspace_id": workspace.id,
        "workspace_path": str(workspace.path),
        "related_project_id": str(related_project_id) if related_project_id else None,
        "related_research_question_id": str(related_research_question_id)
        if related_research_question_id
        else None,
    }
    request_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if idempotency_key:
        existing = db.scalar(
            select(CodexTask).where(
                CodexTask.user_id == user_id, CodexTask.idempotency_key == idempotency_key
            )
        )
        if existing:
            if existing.request_sha256 != request_hash:
                raise DomainError("IDEMPOTENCY_CONFLICT", "Key was used for a different task", 409)
            return existing
    task = CodexTask(
        user_id=user_id,
        title=title,
        prompt=prompt,
        kind=kind,
        mode=mode,
        workspace_id=workspace.id,
        workspace_path_snapshot=str(workspace.path),
        provider_key="openai_codex_sdk",
        model_key=get_settings().codex_model.strip() or "UNCONFIGURED",
        status="DRAFT",
        budget_mode=get_settings().codex_budget_mode,
        idempotency_key=idempotency_key,
        request_sha256=request_hash,
        related_project_id=related_project_id,
        related_research_question_id=related_research_question_id,
    )
    db.add(task)
    try:
        db.flush()
        append_event(db, task, "TASK_CREATED", "Task draft created by owner")
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        if idempotency_key:
            existing = db.scalar(
                select(CodexTask).where(
                    CodexTask.user_id == user_id,
                    CodexTask.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_hash:
                    raise DomainError(
                        "IDEMPOTENCY_CONFLICT", "Key was used for a different task", 409
                    ) from exc
                return existing
        raise
    db.refresh(task)
    return task


def start_task(
    db: Session,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    confirm_write: bool = False,
    _canonical_source_checked: bool = False,
    _commit: bool = True,
    _writing_context: bool = False,
) -> CodexTask:
    task = get_task(db, user_id, task_id)
    if task.kind == "writing" and not _writing_context:
        raise DomainError(
            "WRITING_START_PLAN_REQUIRED", "Start writing through its exact plan approval", 409
        )
    from app.domain.research_execution_policy import require_gateway_task_start
    from app.services.paper_reproduction import validate_reproduction_execution

    require_gateway_task_start(task.kind, mode=task.mode)
    from app.services.code_changes import validate_task

    validate_task(db, task)
    from app.services.writing import validate_task as validate_writing_task

    validate_writing_task(db, task)

    if task.kind == "paper_reproduction" and not _canonical_source_checked:
        from app.domain.paper_reproduction import CANONICAL_CONTEXT_VERSION
        from app.models import PaperReproductionContext

        source_kind = db.scalar(
            select(PaperReproductionContext.context_version).where(
                PaperReproductionContext.task_id == task.id,
                PaperReproductionContext.user_id == user_id,
            )
        )
        if source_kind == CANONICAL_CONTEXT_VERSION:
            raise DomainError(
                "REPRODUCTION_SOURCE_CHECK_REQUIRED",
                "Use the original-source-aware asynchronous start operation",
                409,
            )

    validate_reproduction_execution(db, task)
    if task.status in {"QUEUED", "RUNNING"}:
        return task
    if task.status != "DRAFT":
        raise DomainError("INVALID_STATE", "Only a draft task can be started", 409)
    capability = codex_capabilities()
    if not capability["available"]:
        raise DomainError("CODEX_UNAVAILABLE", capability["reason"] or "Codex unavailable", 503)
    workspace = workspace_by_id(task.workspace_id, task.mode)
    if str(workspace.path) != task.workspace_path_snapshot:
        raise DomainError("WORKSPACE_CHANGED", "Workspace allowlist path changed", 409)
    if task.mode == "workspace_write":
        if not confirm_write:
            raise DomainError(
                "WRITE_CONFIRMATION_REQUIRED", "Explicit write-mode confirmation is required", 422
            )
        task.base_commit = git_state(workspace.path, require_clean=True)
    task.model_key = get_settings().codex_model.strip()
    task.reasoning_effort = get_settings().codex_reasoning_effort
    task.provider_key = get_settings().codex_provider
    task.budget_mode = get_settings().codex_budget_mode
    task.max_tokens = (
        get_settings().codex_max_tokens_per_task if task.budget_mode == "LOCAL_LIMITS" else None
    )
    task.status = "QUEUED"
    append_event(
        db,
        task,
        "TASK_QUEUED",
        f"Owner confirmed workspace write; model {task.model_key}, budget mode {task.budget_mode}, local cap {task.max_tokens} fixed for execution"
        if task.mode == "workspace_write"
        else f"Owner started read-only task; model {task.model_key}, budget mode {task.budget_mode}, local cap {task.max_tokens} fixed for execution",
    )
    if _commit:
        db.commit()
    else:
        db.flush()
    db.refresh(task)
    return task


async def start_task_with_sources(
    db: Session, user_id: uuid.UUID, task_id: uuid.UUID, *, confirm_write: bool = False
) -> CodexTask:
    from app.services.paper_reproduction import validate_reproduction_before_execution

    task = get_task(db, user_id, task_id)
    from app.domain.research_execution_policy import require_gateway_task_start

    require_gateway_task_start(task.kind, mode=task.mode)
    from app.services.code_changes import validate_task

    validate_task(db, task)
    await validate_reproduction_before_execution(db, task)
    return start_task(
        db, user_id, task_id, confirm_write=confirm_write, _canonical_source_checked=True
    )


def cancel_task(db: Session, user_id: uuid.UUID, task_id: uuid.UUID) -> CodexTask:
    task = get_task(db, user_id, task_id)
    if task.status in {"DRAFT", "QUEUED"}:
        task.status = "CANCELLED"
        task.completed_at = datetime.now(UTC)
        append_event(db, task, "TASK_CANCELLED", "Owner cancelled before execution")
    elif task.status == "RUNNING":
        task.status = "CANCEL_REQUESTED"
        append_event(db, task, "CANCEL_REQUESTED", "Owner requested turn interruption")
    elif task.status in TERMINAL or task.status == "CANCEL_REQUESTED":
        return task
    db.commit()
    db.refresh(task)
    return task
