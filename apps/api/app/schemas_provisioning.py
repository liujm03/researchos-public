"""Explicit project scaffolding approval and safe execution progress."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProvisionJobStatus = Literal[
    "QUEUED",
    "PREPARING",
    "LOCAL_READY",
    "CREATING_REMOTE",
    "REMOTE_CREATED",
    "BINDING",
    "COMPLETED",
    "FAILED",
    "NEEDS_ATTENTION",
    "CANCELLED",
]


class ProvisionCapabilityOut(BaseModel):
    enabled: bool
    managed_root_label: str
    github_owner: str | None
    github_owner_id: int | None
    detail: str


class ProvisionPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_name: str | None = Field(default=None, min_length=1, max_length=160)
    repository_name: str | None = Field(default=None, min_length=1, max_length=100)


class ProvisionFileOut(BaseModel):
    path: str
    sha256: str
    size_bytes: int
    content: str


class ProvisionPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    folder_name: str
    repository_name: str
    github_owner: str
    github_owner_id: int
    template_key: str
    template_sha256: str
    plan_sha256: str
    created_at: datetime
    files: list[ProvisionFileOut]


class ProvisionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: uuid.UUID
    expected_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: Literal[True]


class ProvisionObservedConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_repository_id: int = Field(gt=0)
    adopt: Literal[True]


class ProvisionJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    plan_id: uuid.UUID
    active_project_id: uuid.UUID | None
    status: ProvisionJobStatus
    repository_id: int | None
    observed_repository_id: int | None
    binding_id: uuid.UUID | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class ProvisionJobListOut(BaseModel):
    items: list[ProvisionJobOut]


class ProvisionEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    event_kind: str
    message: str
    created_at: datetime
