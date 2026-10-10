"""Imported server reports remain evidence candidates until explicit owner review."""

import math
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import PageMeta
from app.schemas_research_briefs import ResearchBriefSectionCreate


class ServerResultMetricCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    value: float
    unit: str | None = Field(default=None, max_length=80)
    split: str | None = Field(default=None, max_length=80)
    evaluation_protocol: str | None = Field(default=None, max_length=4000)

    @field_validator("value", mode="before")
    @classmethod
    def finite_number(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Metric must be a finite number")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("Metric must be a finite number")
        return value

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Metric identity must contain text")
        return value


class ServerResultArtifactDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, le=2**63 - 1, strict=True)
    mime_type: str = Field(min_length=1, max_length=120)
    included: bool = True


class ServerResultReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: Literal["researchos-server-result-v1"]
    receipt_id: str = Field(min_length=1, max_length=120)
    server_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    package_id: uuid.UUID
    package_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claimed_run_status: Literal["COMPLETED", "FAILED", "STOPPED", "RUNNING", "UNKNOWN"]
    claimed_job_id: str | None = Field(default=None, max_length=160)
    git_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dataset_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metrics: list[ServerResultMetricCreate] = Field(default_factory=list, max_length=100)
    artifacts: list[ServerResultArtifactDeclaration] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=40000)

    @field_validator("receipt_id")
    @classmethod
    def nonblank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Receipt identity must contain text")
        return value

    @model_validator(mode="after")
    def receipt_boundaries(self) -> "ServerResultReceipt":
        for value in (self.started_at, self.ended_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Run times need timezone")
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("Run end precedes start")
        if len({(v.name, v.split) for v in self.metrics}) != len(self.metrics):
            raise ValueError("Metric name/split identities must be unique")
        if len({v.path.casefold() for v in self.artifacts}) != len(self.artifacts):
            raise ValueError("Artifact paths must be unique")
        return self


class ServerResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt: ServerResultReceipt
    signature: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ServerResultPackageOption(BaseModel):
    id: uuid.UUID
    label: str
    bundle_sha256: str
    preview_sha256: str
    readiness: str


class ServerResultOptions(BaseModel):
    owner_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    packages: list[ServerResultPackageOption]
    page: PageMeta
    configured_server_id: str | None
    signature_verification_configured: bool
    scope_note: str


class ServerResultMetricOut(ServerResultMetricCreate):
    id: uuid.UUID


class ServerResultArtifactOut(ServerResultArtifactDeclaration):
    id: uuid.UUID
    verification: Literal["BYTES_VERIFIED", "DECLARED_NOT_INCLUDED", "MISMATCH", "MISSING"]
    attachment_id: uuid.UUID | None
    actual_sha256: str | None = None
    actual_size_bytes: int | None = None


class ServerResultTaskCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: uuid.UUID
    expected_version: int = Field(ge=1)


class ServerResultReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["ACCEPT", "REJECT", "COMMENT"]
    conclusion: str = Field(min_length=1, max_length=10000)
    acknowledge_gaps: bool = False
    complete_tasks: list[ServerResultTaskCompletion] = Field(default_factory=list, max_length=20)
    idempotency_key: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def explicit_review(self) -> "ServerResultReviewRequest":
        if not self.conclusion.strip():
            raise ValueError("Owner conclusion must contain text")
        ids = [item.task_id for item in self.complete_tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Task choices must be unique")
        if self.complete_tasks and self.decision != "ACCEPT":
            raise ValueError("Completing tasks requires an explicit acceptance")
        return self


class ServerResultReviewOut(BaseModel):
    id: uuid.UUID
    decision: str
    conclusion: str
    acknowledge_gaps: bool
    reviewed_at: datetime
    completed_task_ids: list[uuid.UUID]


class ServerResultTaskOption(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    version: int


class ServerResultSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    package_id: uuid.UUID
    receipt_id: str
    server_id: str | None
    status: Literal["IMPORTING", "READY", "NEEDS_ATTENTION", "FAILED"]
    result_sha256: str
    claimed_run_status: str
    origin_verification: Literal[
        "OWNER_UPLOADED_UNVERIFIED", "CONFIGURED_KEY_SIGNATURE", "INVALID_SIGNATURE"
    ]
    validation_status: Literal["MATCHED", "GAPS", "MISMATCH"]
    review_status: Literal["UNREVIEWED", "ACCEPTED", "REJECTED"]
    created_at: datetime
    input_attachment_id: uuid.UUID | None
    error_code: str | None
    error_message: str | None


class ServerResultOut(ServerResultSummary):
    receipt_sha256: str
    input_sha256: str
    claimed_job_id: str | None
    git_commit: str | None
    protocol_sha256: str | None
    config_sha256: str | None
    dataset_sha256: str | None
    started_at: datetime | None
    ended_at: datetime | None
    notes: str | None
    gaps: list[str]
    metrics: list[ServerResultMetricOut]
    artifacts: list[ServerResultArtifactOut]
    reviews: list[ServerResultReviewOut]
    linked_tasks: list[ServerResultTaskOption]
    next_brief_ids: list[uuid.UUID]
    scope_note: str
    execution_authorized: Literal[False] = False


class ServerResultPage(BaseModel):
    items: list[ServerResultSummary]
    page: PageMeta


class ServerResultNextBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idea: str = Field(min_length=1, max_length=12000)
    sections: list[ResearchBriefSectionCreate] = Field(default_factory=list, max_length=8)
    stop_rules: str | None = Field(default=None, max_length=40000)
    idempotency_key: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def actual_idea(self) -> "ServerResultNextBriefRequest":
        if not self.idea.strip():
            raise ValueError("Next research idea must contain text")
        if len({item.key for item in self.sections}) != len(self.sections):
            raise ValueError("Next brief section identities must be unique")
        return self


class ServerResultNextBriefOut(BaseModel):
    result_id: uuid.UUID
    brief_id: uuid.UUID
    status: Literal["DRAFT"] = "DRAFT"


class ServerResultRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_unknown: bool = False
    retry_idempotency_key: str = Field(min_length=1, max_length=120)
