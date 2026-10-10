import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_note_trash import NoteTrashMemberOut


class NoteDeletionBlockerOut(BaseModel):
    code: str
    message: str
    href: str | None = None


class NoteDeletionFileOut(BaseModel):
    kind: Literal["NOTE_CURRENT", "NOTE_REVISION", "NOTE_MIRROR"]
    path: str
    sha256: str
    size_bytes: int
    exists: bool


class NoteDeletionPreviewOut(BaseModel):
    note_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    reading_job_id: uuid.UUID | None
    scope: Literal["READING_RUN"] = "READING_RUN"
    preview_sha256: str
    members: list[NoteTrashMemberOut]
    files: list[NoteDeletionFileOut]
    blockers: list[NoteDeletionBlockerOut]
    can_delete: bool
    recoverable: Literal[False] = False
    deletion_mode: Literal["PERMANENT"] = "PERMANENT"
    backups_in_scope: Literal[False] = False


class NoteDeletionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=120, pattern=r"^\S+$")
    confirm: Literal[True]


class NoteDeletionRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]


class NoteDeletionOut(BaseModel):
    id: uuid.UUID
    note_id: uuid.UUID
    paper_id: uuid.UUID
    scope: Literal["READING_RUN"] = "READING_RUN"
    preview_sha256: str
    idempotency_key: str
    state: Literal["DELETING", "COMPLETED", "FAILED", "NEEDS_ATTENTION"]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    files_total: int
    files_deleted_count: int
    recoverable: Literal[False] = False
    backups_in_scope: Literal[False] = False
