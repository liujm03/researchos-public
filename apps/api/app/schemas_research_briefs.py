"""Immutable owner research briefs; review never grants execution authority."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import PageMeta

BriefSectionKey = Literal[
    "intent",
    "related_work",
    "hypotheses",
    "resources",
    "routes",
    "protocol",
    "stage_plan",
    "decision",
]
BriefOrigin = Literal["OWNER_INPUT", "PROJECT_CONTEXT", "MISSING", "AI_INFERRED"]


class ResearchBriefSectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: BriefSectionKey
    content: str | None = Field(default=None, max_length=40000)

    @field_validator("content")
    @classmethod
    def blank_is_unknown(cls, value: str | None) -> str | None:
        return None if value is not None and not value.strip() else value


class ResearchBriefCanonicalSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_note_id: uuid.UUID
    expected_note_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResearchBriefCanonicalChoiceOut(BaseModel):
    canonical_note_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    note_sha256: str
    note_characters: int
    note_bytes: int
    created_at: datetime
    can_select: bool
    gaps: list[str]


class ResearchBriefCanonicalSourceOut(ResearchBriefCanonicalChoiceOut):
    markdown: str
    reading_job_id: uuid.UUID
    reading_plan_id: uuid.UUID
    source_facts: dict[str, Any]
    source_scope: Literal["DERIVED_NOTE"] = "DERIVED_NOTE"
    note_origin: Literal["AI_DERIVED"] = "AI_DERIVED"
    context_current: bool


class ResearchBriefCanonicalSourcePage(BaseModel):
    items: list[ResearchBriefCanonicalChoiceOut]
    page: PageMeta


class ResearchBriefCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idea: str = Field(min_length=1, max_length=12000)
    base_brief_id: uuid.UUID | None = None
    expected_base_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    sections: list[ResearchBriefSectionCreate] = Field(default_factory=list, max_length=8)
    evidence_paper_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    canonical_note_sources: list[ResearchBriefCanonicalSelection] = Field(
        default_factory=list, max_length=20
    )
    stop_rules: str | None = Field(default=None, max_length=40000)

    @field_validator("stop_rules")
    @classmethod
    def blank_stop_rules(cls, value: str | None) -> str | None:
        return None if value is not None and not value.strip() else value

    @model_validator(mode="after")
    def validate_scope(self) -> "ResearchBriefCreate":
        if not self.idea.strip():
            raise ValueError("Idea must contain non-whitespace text")
        if (self.base_brief_id is None) != (self.expected_base_sha256 is None):
            raise ValueError("Base identity and hash must be provided together")
        if len({item.key for item in self.sections}) != len(self.sections):
            raise ValueError("Section keys must be unique")
        if len(set(self.evidence_paper_ids)) != len(self.evidence_paper_ids):
            raise ValueError("Evidence paper identities must be unique")
        if len({item.canonical_note_id for item in self.canonical_note_sources}) != len(
            self.canonical_note_sources
        ):
            raise ValueError("Canonical note identities must be unique")
        return self


class ResearchBriefReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["ACCEPT", "REJECT"]
    comment: str | None = Field(default=None, max_length=4000)


class ResearchBriefSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: BriefSectionKey
    content: str | None
    origin_type: BriefOrigin
    uncertainty: str | None
    source_planning_job_id: uuid.UUID | None = None
    source_result_sha256: str | None = None


class ResearchBriefEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    paper_id: uuid.UUID
    title: str
    abstract: str | None
    year: int | None
    doi: str | None
    paper_version: int
    sha256: str


class ResearchBriefReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    decision: Literal["ACCEPT", "REJECT"]
    comment: str | None
    reviewed_at: datetime


class ResearchBriefSummaryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    revision: int
    idea: str
    sha256: str
    status: Literal["DRAFT", "ACCEPTED", "REJECTED"]
    context_current: bool
    created_at: datetime
    execution_authorized: Literal[False] = False


class ResearchBriefDetailOut(ResearchBriefSummaryOut):
    user_id: uuid.UUID
    project_version: int
    base_brief_id: uuid.UUID | None
    stop_rules: str | None
    stop_rules_origin: Literal["OWNER_INPUT", "AI_INFERRED"] | None = None
    stop_source_planning_job_id: uuid.UUID | None = None
    stop_source_result_sha256: str | None = None
    sections: list[ResearchBriefSectionOut]
    evidence: list[ResearchBriefEvidenceOut]
    canonical_note_sources: list[ResearchBriefCanonicalSourceOut] = Field(default_factory=list)
    idea_sources: list[dict[str, Any]] = Field(default_factory=list)
    review: ResearchBriefReviewOut | None
    gaps: list[str]


class ResearchBriefPage(BaseModel):
    items: list[ResearchBriefSummaryOut]
    page: PageMeta
