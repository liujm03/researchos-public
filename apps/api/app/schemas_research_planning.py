"""One owner-approved metadata planning scope; no code or scientific execution grant."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.analytical_notes import ReadingSourceFileContentOut
from app.schemas import PageMeta
from app.schemas_research_briefs import ResearchBriefDetailOut


class PlanningProfileOut(BaseModel):
    key: str
    label: str


class PlanningCapabilityOut(BaseModel):
    enabled: bool
    stage: Literal["PLANNING"] = "PLANNING"
    scope: Literal["BRIEF_METADATA_ONLY"] = "BRIEF_METADATA_ONLY"
    supported_scopes: list[str] = Field(
        default_factory=lambda: ["BRIEF_METADATA_ONLY", "BRIEF_DERIVED_NOTES"]
    )
    no_tools: Literal[True] = True
    profiles: list[PlanningProfileOut]
    detail: str


class PlanningGrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief_id: uuid.UUID
    expected_brief_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile: str = Field(min_length=1, max_length=80)
    focus: str = Field(default="", max_length=12000)
    max_jobs: int = Field(default=1, ge=1, le=20)
    timeout_seconds: int = Field(default=900, ge=60, le=1800)
    expires_at: AwareDatetime


class PlanningGrantApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    allow_cloud_transfer: Literal[True]


class PlanningJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: str | None = Field(default=None, max_length=12000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class PlanningGrantOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    brief_id: uuid.UUID
    brief_sha256: str
    sha256: str
    profile: str
    focus: str
    skill_key: str
    skill_version: str
    instructions_sha256: str
    source_manifest_sha256: str
    output_contract_version: str
    output_contract_sha256: str | None
    output_contract_payload: dict[str, Any] | None
    state: Literal["DRAFT", "ACTIVE", "REVOKED"]
    scope: Literal["BRIEF_METADATA_ONLY", "BRIEF_DERIVED_NOTES"]
    no_tools: Literal[True]
    model_key: str
    reasoning_effort: str
    expires_at: datetime
    timeout_seconds: int
    max_jobs: int
    used_jobs: int
    jobs_remaining: int
    approved_at: datetime | None
    approved_sha256: str | None
    created_at: datetime
    context_current: bool
    expired: bool
    effective_state: Literal["DRAFT", "ACTIVE", "REVOKED", "EXPIRED"]
    warnings: list[str]
    gaps: list[str]
    can_submit: bool
    initial_job_id: uuid.UUID | None
    files: list[ReadingSourceFileContentOut]
    brief: ResearchBriefDetailOut
    execution_stage: Literal["PLANNING"] = "PLANNING"
    scientific_execution_authorized: Literal[False] = False


class PlanningPermitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    grant_id: uuid.UUID
    manifest_sha256: str
    expires_at: datetime
    state: Literal["RESERVED", "ISSUED", "STARTED", "REVOKED"]
    issued_at: datetime | None


class PlanningAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    permit_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    status: Literal["RUNNING", "COMPLETED", "FAILED", "NEEDS_ATTENTION", "CANCELLED"]
    provider_response_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    error_code: str | None
    error_message: str | None


class PlanningResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    markdown: str
    attempt_id: uuid.UUID
    sha256: str
    size_bytes: int
    review_status: Literal["CANDIDATE"]
    disposition: Literal["AVAILABLE", "QUARANTINED"]
    normalization_status: Literal[
        "AVAILABLE", "UNUSABLE", "NOT_REQUESTED", "NOT_RECORDED", "QUARANTINED"
    ]
    normalization_issue: str | None
    created_at: datetime


class PlanningJobOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    grant_id: uuid.UUID
    status: Literal[
        "QUEUED",
        "RUNNING",
        "CANCEL_REQUESTED",
        "COMPLETED",
        "FAILED",
        "NEEDS_ATTENTION",
        "CANCELLED",
    ]
    manifest_sha256: str
    focus: str
    input_snapshot: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    permit: PlanningPermitOut | None
    attempts: list[PlanningAttemptOut]
    result: PlanningResultOut | None
    scientific_execution_authorized: Literal[False] = False


class PlanningGrantPage(BaseModel):
    items: list[PlanningGrantOut]
    page: PageMeta


class PlanningJobPage(BaseModel):
    items: list[PlanningJobOut]
    page: PageMeta
