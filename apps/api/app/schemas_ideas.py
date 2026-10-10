"""Typed idea capture, frozen excerpts and owner-selected transitions."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import PageMeta
from app.schemas_research_briefs import BriefSectionKey, ResearchBriefSectionCreate

IdeaStatus = Literal[
    "INBOX", "EVALUATING", "PROMISING", "EXPERIMENTING", "VALIDATED", "REJECTED", "PAPER_CANDIDATE"
]


class IdeaSourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_note_id: uuid.UUID
    expected_note_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_quote: str = Field(min_length=1, max_length=40000)

    @model_validator(mode="after")
    def offsets(self) -> "IdeaSourceSelection":
        if self.end_offset - self.start_offset != len(self.exact_quote):
            raise ValueError("Offsets use Unicode code points and must match exact quote length")
        return self


class IdeaFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=320)
    content: str = Field(default="", max_length=40000)
    problem: str | None = Field(default=None, max_length=12000)
    hypothesis: str | None = Field(default=None, max_length=12000)
    method: str | None = Field(default=None, max_length=12000)
    contribution: str | None = Field(default=None, max_length=12000)
    difficulty: str | None = Field(default=None, max_length=4000)
    novelty: str | None = Field(default=None, max_length=4000)
    feasibility: str | None = Field(default=None, max_length=4000)
    required_dataset: str | None = Field(default=None, max_length=12000)
    required_hardware: str | None = Field(default=None, max_length=12000)
    next_experiment: str | None = Field(default=None, max_length=12000)
    review_note: str | None = Field(default=None, max_length=12000)
    status: IdeaStatus = "INBOX"


class IdeaCreate(IdeaFields):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=30)
    project_id: uuid.UUID | None = None
    sources: list[IdeaSourceSelection] = Field(default_factory=list, max_length=20)


class IdeaRevise(IdeaFields):
    tags: list[str] | None = Field(default=None, max_length=30)
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: list[IdeaSourceSelection] | None = Field(default=None, max_length=20)


class IdeaSourceOut(BaseModel):
    id: uuid.UUID
    canonical_note_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    reading_job_id: uuid.UUID
    reading_plan_id: uuid.UUID
    note_sha256: str
    source_sha256: str
    source_facts: dict[str, Any]
    start_offset: int
    end_offset: int
    exact_quote: str
    context_current: bool
    origin: Literal["AI_DERIVED"] = "AI_DERIVED"


class IdeaRevisionOut(IdeaFields):
    tags: list[str]
    id: uuid.UUID
    idea_id: uuid.UUID
    revision: int
    sha256: str
    created_at: datetime
    sources: list[IdeaSourceOut]
    context_current: bool
    integrity_valid: bool
    scientific_state: Literal["OWNER_REPORTED_NOT_SCIENTIFICALLY_VERIFIED"] = (
        "OWNER_REPORTED_NOT_SCIENTIFICALLY_VERIFIED"
    )


class IdeaSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    status: IdeaStatus
    revision: int
    created_at: datetime


class IdeaOut(IdeaSummary):
    current: IdeaRevisionOut
    task_actions: list["IdeaTaskReceipt"]
    brief_actions: list["IdeaBriefReceipt"]


class IdeaPage(BaseModel):
    items: list[IdeaSummary]
    page: PageMeta


class IdeaRevisionPage(BaseModel):
    items: list[IdeaRevisionOut]
    page: PageMeta


class IdeaTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=320)
    description: str | None = Field(default=None, max_length=40000)
    category: Literal["reading", "research", "coding", "experiment"] = "research"
    project_id: uuid.UUID | None = None


class IdeaTaskReceipt(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    idempotency_key: str
    id: uuid.UUID
    task_id: uuid.UUID
    revision_id: uuid.UUID
    revision_sha256: str
    created_at: datetime
    execution_authorized: Literal[False] = False


class IdeaBriefPreviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_project_id: uuid.UUID
    sections: list[BriefSectionKey] = Field(
        default=["intent", "hypotheses", "routes"], max_length=8
    )

    @model_validator(mode="after")
    def unique(self) -> "IdeaBriefPreviewCreate":
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("Duplicate section selection")
        return self


class IdeaBriefPreviewOut(BaseModel):
    idea_id: uuid.UUID
    revision_id: uuid.UUID
    revision_sha256: str
    target_project_id: uuid.UUID
    project_version: int
    base_brief_id: uuid.UUID | None
    expected_base_sha256: str | None
    idea: str
    sections: list[ResearchBriefSectionCreate]
    source_snapshot: dict[str, Any]
    preview_sha256: str
    execution_authorized: Literal[False] = False


class IdeaBriefCreate(IdeaBriefPreviewCreate):
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=120)


class IdeaBriefReceipt(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    idempotency_key: str
    id: uuid.UUID
    brief_id: uuid.UUID
    project_id: uuid.UUID
    revision_id: uuid.UUID
    created_at: datetime
    status: Literal["DRAFT"] = "DRAFT"
