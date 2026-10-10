"""Owned source-cache copy consent; immutable members never grant execution."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import PageMeta
from app.schemas_repository_assets import AssetEventOut


class ProjectSourceEventOut(AssetEventOut):
    receipt_sha256: str | None = None
    receipt_path: str | None = None
    disposition: Literal["QUARANTINED"] | None = None


class ProjectSourceCapabilityOut(BaseModel):
    enabled: bool
    managed_root_label: str
    detail: str
    execution_authorized: Literal[False] = False


class ProjectSourcePlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_snapshot_id: uuid.UUID


class ProjectSourcePlanApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_copy: Literal[True]


class ProjectPathBindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    archive_binding_id: uuid.UUID
    purpose: Literal["REPOSITORY_SOURCE"]
    state: Literal["PROPOSED", "ACTIVE", "REVOKED"]
    root_fingerprint: str
    source_root_fingerprint: str
    relative_path: str
    scope_sha256: str
    approved_hash: str | None
    approved_at: datetime | None
    no_execution: Literal[True]


class ProjectSourcePlanOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    path_binding_id: uuid.UUID
    asset_snapshot_id: uuid.UUID
    asset_manifest_sha256: str
    source_snapshot_id: uuid.UUID
    provider_key: str
    repo_kind: str
    repo_id: str
    provider_id: str
    commit_sha: str
    source_status: Literal["MATERIALIZED", "PARTIAL"]
    gaps: list[str]
    file_count: int
    total_bytes: int
    plan_sha256: str
    state: Literal["DRAFT", "APPROVED"]
    approved_hash: str | None
    approved_at: datetime | None
    created_at: datetime
    root_label: str
    binding: ProjectPathBindingOut
    can_approve: bool
    initial_job_id: uuid.UUID | None
    execution_authorized: Literal[False] = False


class ProjectSourcePlanFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    file_key_sha256: str
    asset_file_id: uuid.UUID
    attachment_id: uuid.UUID
    path: str
    sha256: str
    size_bytes: int


class ProjectSourcePlanPage(BaseModel):
    items: list[ProjectSourcePlanOut]
    page: PageMeta


class ProjectSourcePlanFilePage(BaseModel):
    items: list[ProjectSourcePlanFileOut]
    page: PageMeta


class ProjectSourceJobOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    plan_id: uuid.UUID
    path_binding_id: uuid.UUID
    status: Literal[
        "QUEUED",
        "COPYING",
        "CANCEL_REQUESTED",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "NEEDS_ATTENTION",
    ]
    copied_files: int
    copied_bytes: int
    receipt_sha256: str | None
    receipt_path: str | None
    verified_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    can_cancel: bool
    can_resume: bool
    can_verify: bool
    can_reconcile: bool = False
    source_status: Literal["MATERIALIZED", "PARTIAL"]
    gaps: list[str]
    root_label: str
    binding_state: Literal["PROPOSED", "ACTIVE", "REVOKED"]
    execution_authorized: Literal[False] = False
    baseline_qualified: Literal[False] = False


class ProjectSourceJobPage(BaseModel):
    items: list[ProjectSourceJobOut]
    page: PageMeta


class ProjectSourceFileOut(BaseModel):
    id: uuid.UUID
    file_key_sha256: str
    path: str
    status: Literal["COPIED", "REUSED", "FAILED", "QUARANTINED"]
    actual_sha256: str | None
    actual_size_bytes: int | None
    relative_path: str | None
    verified_at: datetime | None
    error_code: str | None
    created_at: datetime


class ProjectSourceFilePage(BaseModel):
    items: list[ProjectSourceFileOut]
    page: PageMeta


class ProjectSourceCheckOut(BaseModel):
    path: str
    status: Literal["VERIFIED", "MISSING", "CHANGED", "UNAVAILABLE", "UNSAFE"]
    actual_sha256: str | None = None
    actual_size_bytes: int | None = None


class ProjectSourceVerifyOut(BaseModel):
    job_id: uuid.UUID
    checked_at: datetime
    verified: bool
    files: list[ProjectSourceCheckOut]
    gaps: list[str]
    execution_authorized: Literal[False] = False
