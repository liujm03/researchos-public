"""Bounded baseline execution plans: source IDs and typed budgets, no arbitrary commands."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import PageMeta


class BaselineRunLimitsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: int = Field(default=120, ge=1, le=1800)
    cpu_millicores: int = Field(default=1000, ge=100, le=4000)
    memory_bytes: int = Field(default=536870912, ge=67108864, le=8589934592)
    pids: int = Field(default=32, ge=8, le=256)
    max_input_bytes: int = Field(default=268435456, ge=1, le=1073741824)
    max_input_files: int = Field(default=1000, ge=1, le=1000)
    max_log_bytes: int = Field(default=1048576, ge=1024, le=8388608)
    max_output_bytes: int = Field(default=33554432, ge=1024, le=268435456)
    max_output_files: int = Field(default=100, ge=1, le=1000)


class BaselineRunParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    random_seed: int = Field(default=0, ge=0, le=4294967295)


class BaselineRunPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    material_check_id: uuid.UUID | None = None
    entry_asset_id: uuid.UUID | None = None
    config_asset_id: uuid.UUID | None = None
    profile: Literal["PYTHON_SCRIPT_V1"] = "PYTHON_SCRIPT_V1"
    parameters: BaselineRunParameters = Field(default_factory=BaselineRunParameters)
    limits: BaselineRunLimitsIn = Field(default_factory=BaselineRunLimitsIn)
    expires_at: datetime
    max_jobs: int = Field(default=1, ge=1, le=20)


class BaselineRunPlanApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approve_execution: Literal[True]


class BaselineRunJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)


class BaselineRunInputOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    role: str
    dataset_version_id: uuid.UUID | None
    dataset_split: Literal["TRAIN", "VALIDATION"] | None
    sample_id: str | None
    group_id: str | None
    path: str
    source_sha256: str
    input_sha256: str
    size_bytes: int
    projected_content: str | None


class BaselineRuntimeOut(BaseModel):
    enabled: bool
    available: bool
    docker_host: str
    daemon_id: str | None
    image_id: str | None
    issues: list[str]
    checked_at: datetime
    profile: Literal["PYTHON_SCRIPT_V1"] = "PYTHON_SCRIPT_V1"
    scientific_qualification: Literal["NOT_GRANTED"] = "NOT_GRANTED"


class BaselineRunPlanOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version_id: uuid.UUID
    version_sha256: str
    material_check_id: uuid.UUID | None
    material_check_sha256: str | None
    image_id: str | None
    daemon_id: str | None
    profile: Literal["PYTHON_SCRIPT_V1"]
    entry_asset_id: uuid.UUID | None
    config_asset_id: uuid.UUID | None
    parameters: BaselineRunParameters
    limits: BaselineRunLimitsIn
    input_manifest_sha256: str
    sha256: str
    state: Literal["DRAFT", "ACTIVE", "REVOKED"]
    approved_sha256: str | None
    approved_at: datetime | None
    expires_at: datetime
    expired: bool
    max_jobs: int
    used_jobs: int
    jobs_remaining: int
    context_current: bool
    can_approve: bool
    can_enqueue: bool
    gaps: list[str]
    inputs: list[BaselineRunInputOut]
    initial_job_id: uuid.UUID | None
    created_at: datetime
    scientific_qualification: Literal["NOT_GRANTED"] = "NOT_GRANTED"


class BaselineRunPermitOut(BaseModel):
    id: uuid.UUID
    state: Literal["RESERVED", "ISSUED", "STARTED", "REVOKED"]
    issued_at: datetime | None
    expires_at: datetime
    manifest_sha256: str


class BaselineRunAttemptOut(BaseModel):
    id: uuid.UUID
    status: Literal["STARTED", "COMPLETED_CANDIDATE", "FAILED", "CANCELLED", "NEEDS_ATTENTION"]
    container_id: str | None
    container_name: str | None
    image_id: str
    daemon_id: str
    command_sha256: str | None
    input_manifest_sha256: str | None
    exit_code: int | None
    container_stopped: bool | None
    logs: str | None
    receipt_status: str | None
    input_sealed: bool = False
    input_seal: dict[str, str | bool] | None = None
    began_at: datetime
    ended_at: datetime | None
    issues: list[str]


class BaselineRunArtifactOut(BaseModel):
    id: uuid.UUID
    attempt_id: uuid.UUID
    attachment_id: uuid.UUID | None
    path: str
    sha256: str
    size_bytes: int
    disposition: Literal["AVAILABLE", "QUARANTINED", "UNAVAILABLE"]
    created_at: datetime


class BaselineRunJobOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version_id: uuid.UUID
    plan_id: uuid.UUID
    status: Literal[
        "QUEUED",
        "STARTING",
        "RUNNING",
        "CANCEL_REQUESTED",
        "COMPLETED_CANDIDATE",
        "FAILED",
        "CANCELLED",
        "NEEDS_ATTENTION",
    ]
    manifest_sha256: str
    idempotency_key: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    can_cancel: bool
    can_reconcile: bool
    permit: BaselineRunPermitOut
    attempt: BaselineRunAttemptOut | None
    artifacts: list[BaselineRunArtifactOut]
    scientific_qualification: Literal["NOT_GRANTED"] = "NOT_GRANTED"


class BaselineRunPlanPage(BaseModel):
    items: list[BaselineRunPlanOut]
    page: PageMeta


class BaselineRunJobPage(BaseModel):
    items: list[BaselineRunJobOut]
    page: PageMeta


class BaselineRunEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    occurred_at: datetime
    status: str | None
    code: str | None
