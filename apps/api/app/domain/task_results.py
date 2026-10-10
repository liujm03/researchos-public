"""Typed handoff projection; references never imply scientific verification."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReadingEnvelopeSkillOut(BaseModel):
    key: str
    version: str
    assembled_sha256: str | None = None
    source_manifest_sha256: str | None = None
    source_binding_version: str | None = None
    source_verified: bool
    ready_binding: Literal[False] = False


class EnvelopeInputRef(BaseModel):
    kind: str
    id: str
    sha256: str | None = None
    version: str | None = None
    page_count: int | None = None


class EnvelopeArtifact(BaseModel):
    kind: str
    id: uuid.UUID
    sha256: str
    size_bytes: int = Field(ge=0)
    version: str | None = None
    path: str | None = None
    verification: str


class EnvelopeReceipt(BaseModel):
    id: str
    kind: str
    status: str
    provider_response_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class EnvelopeGap(BaseModel):
    code: str
    detail: str


class ReadingResultEnvelopeOut(BaseModel):
    schema_version: Literal["reading-result-envelope-v1"] = "reading-result-envelope-v1"
    task_id: uuid.UUID
    attempt_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    project_ids: list[uuid.UUID]
    paper_id: uuid.UUID
    checked_at: datetime
    job_status: str
    skill_binding: ReadingEnvelopeSkillOut | None = None
    input_refs: list[EnvelopeInputRef]
    output_artifacts: list[EnvelopeArtifact]
    tool_receipt_refs: list[EnvelopeReceipt]
    gaps: list[EnvelopeGap]
    completion_proposal: Literal["NEEDS_HUMAN_REVIEW", "BLOCKED", "NO_RESULT"]
    next_action: str
    file_recheck_available: bool = False
