import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NoteDeleteScope = Literal["VERSION", "READING_RUN"]


class GeneratedFileSettingsOut(BaseModel):
    enabled: bool
    note_delete_scope: Literal["READING_RUN"] = "READING_RUN"
    file_disposition: Literal["DELETE_MANAGED_FILES"] = "DELETE_MANAGED_FILES"
    reclaims_disk_space: Literal[True] = True
    deletion_mode: Literal["PERMANENT"] = "PERMANENT"
    recoverable: Literal[False] = False


class GeneratedFileSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    note_delete_scope: NoteDeleteScope | None = None


class NoteTrashPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: NoteDeleteScope | None = None


class NoteTrashRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: NoteDeleteScope
    expected_preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=120, pattern=r"^\S+$")
    confirm: Literal[True]


class NoteTrashRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=120, pattern=r"^\S+$")
    confirm: Literal[True]


class NoteTrashMemberOut(BaseModel):
    note_id: uuid.UUID
    revision: int
    created_by: str
    content_sha256: str


class NoteReferenceCountOut(BaseModel):
    kind: str
    count: int


class NoteTrashPreviewOut(BaseModel):
    note_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    scope: NoteDeleteScope
    preview_sha256: str
    members: list[NoteTrashMemberOut]
    file_paths: list[str]
    reference_counts: list[NoteReferenceCountOut]
    warnings: list[str]
    file_disposition: Literal["PRESERVED"] = "PRESERVED"
    reclaims_disk_space: Literal[False] = False


class NoteTrashEntryOut(NoteTrashPreviewOut):
    id: uuid.UUID
    state: Literal["TRASHED", "RESTORED"]
    version: int
    idempotency_key: str
    created_at: datetime
    restored_at: datetime | None
