"""Explicit professional writing selection, preview, start and candidate adoption."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import PageMeta
from app.schemas_codex_tasks import CodexTaskOut
from app.schemas_publications import PublicationPreview


class WritingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: uuid.UUID
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile: Literal["tech-paper-template", "research-paper-writing", "pre-submission-reviewer"]
    target_section_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    focus: str = Field(default="", max_length=12000)
    output_language: Literal["en"] = "en"
    venue_style: Literal["GENERIC", "IEEE", "ELSEVIER", "CVPR"] = "GENERIC"
    bundle_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique(self) -> "WritingSelection":
        if len(set(self.bundle_ids)) != len(self.bundle_ids):
            raise ValueError("Select each evidence bundle once")
        return self


class WritingSkillFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    path: str
    role: str
    sha256: str
    size_bytes: int
    content: str


class WritingPreview(BaseModel):
    selection: WritingSelection
    preview_sha256: str
    input_snapshot: dict[str, Any]
    skill_files: list[WritingSkillFileOut]
    skill_key: str
    skill_version: str
    skill_manifest_sha256: str
    model_key: str
    reasoning_effort: str
    provider_key: Literal["openai_codex_sdk"] = "openai_codex_sdk"
    budget_mode: Literal["LOCAL_LIMITS", "PROVIDER_QUOTA"]
    max_tokens: int | None
    gaps: list[str]
    source_scope: Literal["PUBLICATION_DERIVED_TEXT"] = "PUBLICATION_DERIVED_TEXT"
    no_tools: Literal[True] = True
    scientific_execution_authorized: Literal[False] = False


class WritingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: WritingSelection
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_cloud_transfer: Literal[True]
    acknowledge_gaps: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class WritingStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_start: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=120)


class WritingImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=120)


class WritingAdoptionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_quote: str = Field(min_length=1, max_length=262144)
    expected_publication_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WritingAdopt(WritingAdoptionSelection):
    expected_adoption_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_gaps: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class WritingCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    markdown: str
    sha256: str
    task_response_sha256: str
    created_at: datetime


class WritingAdoptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    publication_revision_id: uuid.UUID
    revision_sha256: str
    exact_quote: str
    start_offset: int
    end_offset: int
    created_at: datetime


class WritingOperationReceipt(BaseModel):
    kind: Literal["create", "start", "import", "adopt", "issue"]
    request_sha256: str
    idempotency_key: str


class WritingPlanSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    publication_id: uuid.UUID
    revision_id: uuid.UUID
    task_id: uuid.UUID
    created_at: datetime


class WritingPlanOut(WritingPlanSummary):
    preview: WritingPreview
    task: CodexTaskOut
    candidate: WritingCandidateOut | None
    adoptions: list[WritingAdoptionOut]
    issues: list["WritingIssueOut"] = Field(default_factory=list)
    operation_receipt: WritingOperationReceipt | None = None
    context_current: bool
    gaps: list[str]


class WritingPlanPage(BaseModel):
    items: list[WritingPlanSummary]
    page: PageMeta


class WritingProfileOut(BaseModel):
    key: str
    label: str
    targets: list[str]


class WritingOptions(BaseModel):
    enabled: bool
    profiles: list[WritingProfileOut]
    model_key: str
    reasoning_effort: str
    no_tools: Literal[True] = True
    detail: str
    styles: list["WritingStyleOut"] = Field(default_factory=list)


class WritingStyleOut(BaseModel):
    key: Literal["GENERIC", "IEEE", "ELSEVIER", "CVPR"]
    label: str
    available: bool
    detail: str


WritingAdoptionPreview = PublicationPreview
WritingAdoptSelection = WritingAdoptionSelection


class WritingIssueCreate(WritingAdoptionSelection):
    title: str = Field(min_length=1, max_length=320)
    severity: Literal["CRITICAL", "MAJOR", "MINOR"]
    priority: Literal["low", "medium", "high", "urgent"] = "high"
    category: Literal["writing", "research"] = "writing"
    idempotency_key: str = Field(min_length=1, max_length=120)


class WritingIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID
    severity: str
    exact_quote: str
    start_offset: int
    end_offset: int
    created_at: datetime
