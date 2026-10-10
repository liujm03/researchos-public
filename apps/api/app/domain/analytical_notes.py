"""Owner-reviewed canonical analytical note contracts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReadingPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: uuid.UUID
    collection: str = Field(min_length=1, max_length=160)


class ReadingPlanBatch(BaseModel):
    part_index: int
    pages: list[int]


class ReadingSourceFileOut(BaseModel):
    path: str
    role: Literal["INSTRUCTION", "TEMPLATE"]
    sha256: str
    size_bytes: int


class ReadingSourceFileContentOut(ReadingSourceFileOut):
    content: str


class ReadingPlanOut(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    attachment_id: uuid.UUID
    title: str
    page_count: int
    sha256: str
    model_key: str
    reasoning_effort: str
    skill_key: str
    skill_version: str
    skill_sha256: str
    template_sha256: str
    note_output_contract: Literal["PAPER_ANALYSIS_V1", "CANONICAL_MARKDOWN_V2"] = (
        "PAPER_ANALYSIS_V1"
    )
    output_root: str
    output_path: str
    existing_file_sha256: str | None
    plan_sha256: str
    page_batches: list[ReadingPlanBatch]
    writing_stage: Literal["WHOLE_PDF_WRITE_NOTE", "READ_ALL_PAGES_THEN_WRITE_NOTE"]
    created_at: datetime
    source_manifest_sha256: str | None = None
    source_binding_version: str | None = None
    source_files: list[ReadingSourceFileOut] = Field(default_factory=list)


class ApprovedReadingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: uuid.UUID
    approval_plan_id: uuid.UUID
    expected_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: Literal[True]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class CanonicalNoteOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    markdown: str
    sha256: str
    output_path: str
    export_status: Literal["PENDING", "SAVING", "SAVED", "CONFLICT", "FAILED"]
    export_error: str | None
    export_error_code: str | None
    export_attempt_count: int
    export_retryable: bool
    export_auto_retry_enabled: bool
    export_manual_retry_allowed: bool
    export_next_retry_at: datetime | None
    export_lease_expires_at: datetime | None
    exported_at: datetime | None
    created_at: datetime
