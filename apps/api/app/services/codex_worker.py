"""Durable Codex task processor. A separate process runs this service."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import SessionLocal
from app.domain.codex import CodexProvider, CodexRunRequest
from app.errors import DomainError
from app.models import CodexTask
from app.services.codex_diff import capture_review_patch
from app.services.codex_tasks import _git, append_event, git_state, workspace_by_id


def claim_next_codex_task(db: Session) -> CodexTask | None:
    task = db.scalar(
        select(CodexTask)
        .where(CodexTask.status == "QUEUED")
        .order_by(CodexTask.created_at, CodexTask.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if task is None:
        return None
    task.status = "RUNNING"
    task.started_at = datetime.now(UTC)
    task.worker_lease_id = uuid.uuid4().hex
    task.last_heartbeat_at = datetime.now(UTC)
    append_event(db, task, "TASK_RUNNING", "Codex worker claimed task")
    db.commit()
    return task


def recover_stale_codex_tasks(db: Session, *, older_than_seconds: int = 120) -> int:
    threshold = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    stale = list(
        db.scalars(
            select(CodexTask)
            .where(
                CodexTask.status.in_(["RUNNING", "CANCEL_REQUESTED"]),
                CodexTask.last_heartbeat_at < threshold,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for task in stale:
        task.status = "NEEDS_ATTENTION"
        task.error = "UNKNOWN_OUTCOME: worker heartbeat expired; inspect Codex thread and workspace"
        task.completed_at = datetime.now(UTC)
        append_event(db, task, "UNKNOWN_OUTCOME", task.error)
    if stale:
        db.commit()
    return len(stale)


async def heartbeat_codex_task(task_id: uuid.UUID, lease_id: str) -> None:
    while True:
        await asyncio.sleep(15)
        with SessionLocal() as db:
            result = cast(
                CursorResult[Any],
                db.execute(
                    update(CodexTask)
                    .where(
                        CodexTask.id == task_id,
                        CodexTask.worker_lease_id == lease_id,
                        CodexTask.status.in_(["RUNNING", "CANCEL_REQUESTED"]),
                    )
                    .values(last_heartbeat_at=datetime.now(UTC))
                ),
            )
            db.commit()
            if result.rowcount == 0:
                return


async def _fresh_cancel_check(task_id: uuid.UUID) -> bool:
    with SessionLocal() as session:
        status = session.scalar(select(CodexTask.status).where(CodexTask.id == task_id))
        return status in {"CANCEL_REQUESTED", "CANCELLED"}


async def process_codex_task(
    db: Session,
    task_id: uuid.UUID,
    provider: CodexProvider,
    *,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
) -> CodexTask:
    task = db.get(CodexTask, task_id)
    if task is None:
        raise DomainError("NOT_FOUND", "Codex task not found", 404)
    if task.status not in {"RUNNING", "CANCEL_REQUESTED"}:
        return task

    async def is_cancelled() -> bool:
        if cancel_check is not None:
            return await cancel_check()
        return await _fresh_cancel_check(task_id)

    async def emit(event_type: str, message: str) -> None:
        append_event(db, task, event_type, message)
        db.commit()

    async def on_started(thread_id: str, turn_id: str) -> None:
        task.codex_thread_id = thread_id
        task.codex_turn_id = turn_id or None
        append_event(
            db,
            task,
            "TURN_STARTED" if turn_id else "THREAD_STARTED",
            "Codex thread and turn identifiers recorded"
            if turn_id
            else "Codex thread identifier recorded before turn creation",
        )
        db.commit()

    try:
        from app.domain.codex import CODEX_NO_EXECUTION_CONTRACT
        from app.domain.research_execution_policy import require_gateway_model_turn

        require_gateway_model_turn(
            task.kind,
            mode=task.mode,
            no_execution_verified=getattr(provider, "execution_contract", None)
            == CODEX_NO_EXECUTION_CONTRACT,
        )
        from app.services.code_changes import validate_task
        from app.services.paper_reproduction import validate_reproduction_before_execution
        from app.services.writing import validate_task as validate_writing_task

        validate_task(db, task)
        validate_writing_task(db, task)
        await validate_reproduction_before_execution(db, task)
        if provider.provider_key != task.provider_key:
            raise DomainError("PROVIDER_CHANGED", "Codex provider no longer matches task", 409)
        settings = get_settings()
        if settings.codex_provider != task.provider_key or settings.codex_model != task.model_key:
            raise DomainError("CODEX_CONFIGURATION_CHANGED", "Codex model or provider changed", 409)
        if task.budget_mode not in {"LOCAL_LIMITS", "PROVIDER_QUOTA"}:
            raise DomainError("TOKEN_BUDGET_INVALID", "Recorded Codex budget mode is invalid", 409)
        if task.budget_mode == "PROVIDER_QUOTA" and task.max_tokens is not None:
            raise DomainError(
                "TOKEN_BUDGET_INVALID", "Account-quota task must not contain a local token cap", 409
            )
        if task.max_tokens is None and task.budget_mode == "LOCAL_LIMITS":
            # Queued tasks created before the budget migration are frozen before execution.
            if not 1_000 <= settings.codex_max_tokens_per_task <= 1_000_000:
                raise DomainError("TOKEN_BUDGET_INVALID", "Codex token budget is invalid", 409)
            task.max_tokens = settings.codex_max_tokens_per_task
            append_event(db, task, "TOKEN_BUDGET_SNAPSHOTTED", f"Soft token cap: {task.max_tokens}")
            db.commit()
        workspace = workspace_by_id(task.workspace_id, task.mode)
        if str(workspace.path) != task.workspace_path_snapshot:
            raise DomainError("WORKSPACE_CHANGED", "Workspace allowlist path changed", 409)
        if task.mode == "workspace_write":
            current_commit = git_state(workspace.path, require_clean=True)
            if current_commit != task.base_commit:
                raise DomainError(
                    "BASE_COMMIT_CHANGED", "Git HEAD changed before task execution", 409
                )
        if await is_cancelled():
            task.status = "CANCELLED"
            append_event(db, task, "TASK_CANCELLED", "Cancelled before Codex thread began")
        else:
            # Re-read owner scope immediately before the uncalled execution.
            require_gateway_model_turn(
                task.kind,
                mode=task.mode,
                no_execution_verified=getattr(provider, "execution_contract", None)
                == CODEX_NO_EXECUTION_CONTRACT,
            )
            validate_task(db, task)
            validate_writing_task(db, task)
            await validate_reproduction_before_execution(db, task)
            if await is_cancelled() or task.status == "CANCEL_REQUESTED":
                task.status = "CANCELLED"
                task.completed_at = datetime.now(UTC)
                append_event(
                    db,
                    task,
                    "TASK_CANCELLED",
                    "Cancelled during final source verification; no Codex turn began",
                )
                db.commit()
                return task
            if task.status != "RUNNING":
                db.rollback()
                return task
            if (
                get_settings().codex_provider != task.provider_key
                or get_settings().codex_model != task.model_key
            ):
                raise DomainError(
                    "CODEX_CONFIGURATION_CHANGED",
                    "Codex model or provider changed during source verification",
                    409,
                )
            from app.models_code_changes import CodeChangePlan

            selected_code_task = (
                db.scalar(
                    select(CodeChangePlan.id).where(
                        CodeChangePlan.task_id == task.id, CodeChangePlan.user_id == task.user_id
                    )
                )
                is not None
            )
            run_request = CodexRunRequest(
                prompt=task.prompt,
                workspace_path=task.workspace_path_snapshot,
                mode=task.mode,  # type: ignore[arg-type]
                model=task.model_key,
                timeout_seconds=settings.codex_task_timeout_seconds,
                max_tokens=task.max_tokens,
                budget_mode=task.budget_mode,  # type: ignore[arg-type]
                reasoning_effort=task.reasoning_effort or settings.codex_reasoning_effort,
                output_format="CODE_CHANGE_JSON" if selected_code_task else "MARKDOWN",
            )
            execution_lease = task.worker_lease_id
            db.rollback()
            result = await provider.run(
                run_request,
                emit,
                on_started,
                is_cancelled,
            )
            db.refresh(task)
            late_result = (
                task.status == "NEEDS_ATTENTION" or task.worker_lease_id != execution_lease
            )
            if not late_result:
                task.status = result.status
            from app.models_code_changes import CodeChangePlan

            bounded_code = (
                db.scalar(
                    select(CodeChangePlan.id).where(
                        CodeChangePlan.task_id == task.id, CodeChangePlan.user_id == task.user_id
                    )
                )
                is not None
            )
            bounded_writing = task.kind == "writing"
            bounded_data = bounded_code or bounded_writing
            if bounded_data and late_result:
                from app.models import ResearchEvent
                from app.services.code_changes import sha

                raw = result.final_response
                db.add(
                    ResearchEvent(
                        event_id=uuid.uuid4(),
                        user_id=task.user_id,
                        event_type="WRITING_LATE_RESULT"
                        if bounded_writing
                        else "CODE_CHANGE_LATE_RESULT",
                        schema_version="1.0",
                        occurred_at=datetime.now(UTC),
                        source="codex-worker",
                        correlation_id=task.id,
                        payload={
                            "worker_lease_id": execution_lease,
                            "status": result.status,
                            "response_sha256": sha(raw) if raw else None,
                            "response": raw
                            if raw and len(raw.encode("utf-8")) <= 2 * 1024 * 1024
                            else None,
                            "response_omitted": bool(
                                raw and len(raw.encode("utf-8")) > 2 * 1024 * 1024
                            ),
                            "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                        },
                    )
                )
                append_event(
                    db,
                    task,
                    "LATE_RESULT",
                    "Late bounded candidate retained separately; current model completion preserved",
                )
                db.commit()
                db.refresh(task)
                return task
            too_large = (
                bounded_data
                and result.final_response is not None
                and len(result.final_response.encode("utf-8")) > 2 * 1024 * 1024
            )
            task.final_response = (
                (None if too_large else result.final_response)
                if bounded_data
                else (result.final_response[:200_000] if result.final_response else None)
            )
            if too_large:
                task.status = "NEEDS_ATTENTION"
                task.error = (
                    "WRITING_RESULT_TOO_LARGE: exact response exceeds the writing contract"
                    if bounded_writing
                    else "CODE_RESULT_TOO_LARGE: exact response exceeds the bounded code contract"
                )
            task.input_tokens = result.input_tokens
            task.output_tokens = result.output_tokens
            task.token_budget_exceeded = result.token_budget_exceeded
            if not late_result and not too_large:
                task.error = result.error[:4000] if result.error else None
            if not late_result and task.status == "COMPLETED" and not task.final_response:
                task.status = "NEEDS_ATTENTION"
                task.error = "AI_EMPTY_RESULT: Codex completed without a reviewable final response"
            append_event(
                db,
                task,
                "LATE_RESULT" if late_result else "TASK_FINISHED",
                "Codex returned after outcome became uncertain"
                if late_result
                else f"Codex task ended: {task.status}",
            )
            if bounded_writing and not late_result and task.status == "COMPLETED":
                from app.services.writing import save_completed_candidate

                try:
                    with db.begin_nested():
                        save_completed_candidate(db, task)
                    append_event(
                        db,
                        task,
                        "WRITING_CANDIDATE_SAVED",
                        "Original Markdown saved automatically; no manuscript adopted",
                    )
                except Exception as save_error:
                    append_event(
                        db,
                        task,
                        "WRITING_CANDIDATE_SAVE_FAILED",
                        f"Raw completion retained; candidate save needs recovery: {type(save_error).__name__}",
                    )
    except DomainError as exc:
        task.status = "NEEDS_ATTENTION" if exc.status_code == 409 else "FAILED"
        task.error = exc.message
        append_event(db, task, "TASK_ERROR", f"{exc.code}: {exc.message}")
    except Exception as exc:
        task.status = "FAILED"
        task.error = f"Codex adapter failed: {type(exc).__name__}"
        append_event(db, task, "TASK_ERROR", task.error)
    if task.mode == "workspace_write":
        try:
            path = Path(task.workspace_path_snapshot)
            summary = _write_diff_summary(path, task.base_commit)
            if task.base_commit:
                captured = capture_review_patch(path, task.base_commit)
                task.diff_patch = captured.patch
                task.diff_truncated = captured.truncated
                task.diff_summary = f"{summary}\n{captured.note}"[:20_000]
            else:
                task.diff_summary = summary
            if task.base_commit and _git(path, "rev-parse", "HEAD") != task.base_commit:
                task.status = "NEEDS_ATTENTION"
                task.error = "Git HEAD changed during Codex execution; inspect repository history"
                append_event(db, task, "HEAD_CHANGED", task.error)
        except DomainError as exc:
            task.status = "NEEDS_ATTENTION"
            task.error = f"Cannot inspect workspace after Codex task: {exc.message}"
            append_event(db, task, "DIFF_UNAVAILABLE", task.error)
    task.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(task)
    return task


def _write_diff_summary(path: Path, base_commit: str | None) -> str:
    if base_commit is None:
        return "No base commit recorded"
    status = _git(path, "status", "--porcelain", "--untracked-files=normal")
    diff = _git(path, "diff", "--stat", base_commit)
    return (
        f"Base commit: {base_commit}\nGit status:\n{status or '(clean)'}\nDiff stat:\n{diff or '(none)'}"
    )[:16_000]
