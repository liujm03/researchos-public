"""Pinned asset cache consent; no workspace execution, baseline or training approval."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import PageMeta


class AssetCapabilityOut(BaseModel):
    enabled: bool
    max_bytes: int
    max_files: int
    detail: str
    execution_authorized: Literal[False] = False


class AssetSnapshotChoiceOut(BaseModel):
    asset_snapshot_id: uuid.UUID
    job_id: uuid.UUID
    plan_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    provider_key: str
    repo_kind: str
    repo_id: str
    commit_sha: str
    status: Literal["MATERIALIZED", "PARTIAL"]
    stored_files: int
    stored_bytes: int
    gaps: list[str]
    created_at: datetime
    baseline_qualified: Literal[False] = False
    execution_authorized: Literal[False] = False


class AssetSnapshotChoicePage(BaseModel):
    items: list[AssetSnapshotChoiceOut]
    page: PageMeta


class AssetPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_paths: list[str] | None = Field(default=None, max_length=1000)
    max_bytes: int | None = Field(default=None, ge=1, le=1073741824)
    max_files: int | None = Field(default=None, ge=1, le=10000)

    @model_validator(mode="after")
    def distinct_paths(self) -> "AssetPlanCreate":
        if self.selected_paths is not None and (
            not self.selected_paths
            or len(set(self.selected_paths)) != len(self.selected_paths)
            or any(not path or len(path) > 2000 for path in self.selected_paths)
        ):
            raise ValueError("Select unique nonempty relative paths within the bound")
        return self


class AssetPlanApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_download: Literal[True]


class AssetPlanFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    file_key_sha256: str
    path: str
    size_bytes: int | None
    digest_algorithm: str | None
    digest: str | None
    file_kind: Literal["REGULAR", "LFS", "SYMLINK", "SUBMODULE"]
    supported: bool
    selected: bool
    issue: str | None


class AssetPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_snapshot_id: uuid.UUID
    provider_key: str
    repo_kind: str
    repo_id: str
    provider_id: str
    license_id: str | None
    commit_sha: str
    plan_sha256: str
    manifest_sha256: str
    total_files: int
    total_bytes: int | None
    selected_files: int
    selected_bytes: int
    max_bytes: int
    max_files: int
    scope: Literal["FULL_INVENTORY", "SELECTED_SUBSET"]
    inventory_complete: bool
    state: Literal["DRAFT", "APPROVED"]
    approved_hash: str | None
    approved_at: datetime | None
    created_at: datetime
    gaps: list[str]
    initial_job_id: uuid.UUID | None
    can_approve: bool
    execution_authorized: Literal[False] = False


class AssetPlanPage(BaseModel):
    items: list[AssetPlanOut]
    page: PageMeta


class AssetPlanFilePage(BaseModel):
    items: list[AssetPlanFileOut]
    page: PageMeta


class AssetFileOut(BaseModel):
    id: uuid.UUID
    file_key_sha256: str
    path: str
    attachment_id: uuid.UUID | None
    status: Literal["STORING", "STORED", "FAILED", "UNSUPPORTED", "QUARANTINED"]
    actual_sha256: str | None
    actual_size_bytes: int | None
    remote_verified: bool
    error_code: str | None
    created_at: datetime
    download_url: str | None


class AssetSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: Literal["MATERIALIZED", "PARTIAL"]
    manifest_sha256: str
    stored_files: int
    stored_bytes: int
    created_at: datetime
    gaps: list[str]
    baseline_qualified: Literal[False] = False


class AssetJobOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    status: Literal[
        "QUEUED",
        "DOWNLOADING",
        "CANCEL_REQUESTED",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "NEEDS_ATTENTION",
    ]
    stored_files: int
    stored_bytes: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    snapshot: AssetSnapshotOut | None
    can_resume: bool
    can_cancel: bool
    execution_authorized: Literal[False] = False


class AssetJobPage(BaseModel):
    items: list[AssetJobOut]
    page: PageMeta


class AssetFilePage(BaseModel):
    items: list[AssetFileOut]
    page: PageMeta


class AssetEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    occurred_at: datetime
    status: str | None
    code: str | None
