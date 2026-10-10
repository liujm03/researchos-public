"""Shared authenticated Codex task response; independent of routers."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

type CodexTaskKind = Literal[
    "general",
    "repository_analysis",
    "code_review",
    "bug_fix",
    "code_change",
    "test_generation",
    "experiment_script",
    "paper_reproduction",
    "writing",
]
type CodexTaskMode = Literal["read_only", "workspace_write"]
type CodexTaskStatus = Literal[
    "DRAFT",
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "NEEDS_ATTENTION",
]


class CodexTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    prompt: str
    kind: CodexTaskKind
    mode: CodexTaskMode
    workspace_id: str
    workspace_path_snapshot: str
    status: CodexTaskStatus
    provider_key: str
    model_key: str
    reasoning_effort: str | None = None
    related_project_id: uuid.UUID | None
    related_research_question_id: uuid.UUID | None
    codex_thread_id: str | None
    codex_turn_id: str | None
    base_commit: str | None
    diff_summary: str | None
    diff_patch: str | None
    diff_truncated: bool
    final_response: str | None
    input_tokens: int | None
    output_tokens: int | None
    max_tokens: int | None
    budget_mode: Literal["LOCAL_LIMITS", "PROVIDER_QUOTA"] = "LOCAL_LIMITS"
    token_budget_exceeded: bool
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
