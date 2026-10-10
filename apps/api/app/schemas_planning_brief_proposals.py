"""Literal AI quotations and explicit owner-selected immutable brief revisions."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas_research_briefs import BriefSectionKey, ResearchBriefDetailOut


class PlanningProposalSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: BriefSectionKey
    content: str | None
    source_start: int | None
    source_end: int | None
    uncertainty: str | None


class PlanningBriefProposalOut(BaseModel):
    job_id: uuid.UUID
    attempt_id: uuid.UUID | None
    result_sha256: str | None
    proposal_sha256: str | None
    normalization_status: Literal[
        "AVAILABLE", "UNUSABLE", "NOT_REQUESTED", "NOT_RECORDED", "QUARANTINED"
    ]
    normalization_issue: str | None
    contract_version: str | None
    sections: list[PlanningProposalSectionOut]
    stop_rules_quote: str | None
    stop_source_start: int | None
    stop_source_end: int | None
    warnings: list[str]
    gaps: list[str]
    adoptable: bool


class PlanningBriefAdoptionPreviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_brief_id: uuid.UUID
    expected_base_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_section_keys: list[BriefSectionKey] = Field(default_factory=list, max_length=8)
    include_stop_rules: bool = False
    expected_result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_proposal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def unique_keys(self) -> "PlanningBriefAdoptionPreviewCreate":
        if not self.selected_section_keys and not self.include_stop_rules:
            raise ValueError("Select at least one candidate section or the stopping rule")
        if len(set(self.selected_section_keys)) != len(self.selected_section_keys):
            raise ValueError("Select each candidate section at most once")
        return self


class PlanningBriefAdoptionCreate(PlanningBriefAdoptionPreviewCreate):
    idempotency_key: str = Field(min_length=1, max_length=128)
    acknowledge_stale_context: bool = False


class PlanningBriefDiffOut(BaseModel):
    key: str
    current_content: str | None
    proposed_content: str
    current_origin: str | None
    overwrites_owner_input: bool


class PlanningBriefAdoptionPreviewOut(BaseModel):
    job_id: uuid.UUID
    base_brief_id: uuid.UUID
    base_sha256: str
    result_sha256: str
    proposal_sha256: str
    source_stale: bool
    effective_changes: bool
    diffs: list[PlanningBriefDiffOut]
    warnings: list[str]
    gaps: list[str]


class PlanningBriefAdoptionReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    new_brief_id: uuid.UUID
    base_brief_id: uuid.UUID
    result_sha256: str
    proposal_sha256: str
    request_sha256: str
    idempotency_key: str
    include_stop_rules: bool
    created_at: datetime


class PlanningBriefAdoptionOut(BaseModel):
    brief: ResearchBriefDetailOut
    receipt: PlanningBriefAdoptionReceiptOut
