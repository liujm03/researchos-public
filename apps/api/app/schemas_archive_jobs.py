"""Owner-facing archive policy, execution progress and safe event contracts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ArchiveJobStatus = Literal[
    "QUEUED",
    "PREPARING",
    "COMMITTING",
    "PUBLISHING",
    "COMPLETED",
    "UNCHANGED",
    "FAILED",
    "NEEDS_ATTENTION",
    "CANCELLED",
]
ARCHIVE_TAG_PATTERN = (
    r"^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*)?$"
)


class ArchiveJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str | None = Field(default=None, min_length=1, max_length=120, pattern=ARCHIVE_TAG_PATTERN)


class ArchivePolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_enabled: bool
    interval_minutes: int = Field(default=60, ge=10, le=10080)


class ArchivePolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    auto_enabled: bool
    interval_minutes: int
    next_archive_at: datetime | None
    workspace_fingerprint: str | None


class ArchiveJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    binding_id: uuid.UUID
    tag: str
    trigger_kind: Literal["MANUAL", "SCHEDULED"]
    status: ArchiveJobStatus
    active_binding_id: uuid.UUID | None
    workspace_fingerprint: str
    manifest_sha256: str | None
    commit_sha: str | None
    version_id: uuid.UUID | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class ArchiveJobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    event_kind: str
    message: str
    created_at: datetime


class ArchiveJobListOut(BaseModel):
    items: list[ArchiveJobOut]
