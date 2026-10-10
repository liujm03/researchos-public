"""Explicit owner-selected source and bounded code proposal contracts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import PageMeta


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CodeChangeSelection(Strict):
    binding_id: uuid.UUID
    paths: list[str] = Field(min_length=1, max_length=20)
    instructions: str = Field(min_length=1, max_length=12000)

    @field_validator("paths")
    @classmethod
    def paths_unique(cls, values: list[str]) -> list[str]:
        if len({x.casefold() for x in values}) != len(values):
            raise ValueError("Paths must be unique")
        if any(not x or len(x) > 240 for x in values):
            raise ValueError("Invalid relative file path")
        return values


class CodeChangeFileOut(Strict):
    path: str
    exists: bool
    sha256: str | None
    content: str
    size_bytes: int


class CodeChangePreview(Strict):
    selection: CodeChangeSelection
    workspace_fingerprint: str
    preview_sha256: str
    files: list[CodeChangeFileOut]
    source_scope: Literal["OWNER_SELECTED_CODE"] = "OWNER_SELECTED_CODE"
    execution_authorized: Literal[False] = False


class CodeChangeCreate(Strict):
    selection: CodeChangeSelection
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_source_transfer: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=120)


class CodeChangeImport(Strict):
    expected_task_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=120)


class CodeChangeApply(Strict):
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_apply: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=120)
    acknowledge_unknown: bool = False


class CodeProposalFileOut(Strict):
    path: str
    before_sha256: str | None
    after_sha256: str
    after_text: str
    diff: str
    size_bytes: int


class CodeApplyReceiptOut(Strict):
    path: str
    before_sha256: str | None
    after_sha256: str
    size_bytes: int
    reused: bool


class CodeApplyAttemptOut(Strict):
    id: uuid.UUID
    status: str
    idempotency_key: str
    receipts: list[CodeApplyReceiptOut]
    observations: list[CodeChangeFileOut]
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class CodeChangeSummary(Strict):
    id: uuid.UUID
    project_id: uuid.UUID
    binding_id: uuid.UUID
    task_id: uuid.UUID
    status: str
    created_at: datetime


class CodeChangeOut(CodeChangeSummary):
    selection: CodeChangeSelection
    preview_sha256: str
    workspace_fingerprint: str
    files: list[CodeChangeFileOut]
    task_status: str
    task_result_sha256: str | None
    proposal_sha256: str | None
    rationale: str | None
    proposal_files: list[CodeProposalFileOut]
    attempts: list[CodeApplyAttemptOut]
    execution_authorized: Literal[False] = False


class CodeChangePage(Strict):
    items: list[CodeChangeSummary]
    page: PageMeta


class CodeChangeOptions(Strict):
    project_id: uuid.UUID
    binding_id: uuid.UUID | None
    workspace_key: str | None
    repository: str | None
    enabled: bool
    maximum_files: int = 20
    maximum_file_bytes: int = 262144
    maximum_total_bytes: int = 1048576
    execution_authorized: Literal[False] = False


class CodeChangeReconciliation(Strict):
    plan_id: uuid.UUID
    proposal_sha256: str
    observed_sha256: str
    files: list[CodeChangeFileOut]
    marker_required: bool


class CodeChangeAbandon(Strict):
    observed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_abandon: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=120)
