"""Exact source selections and explicit scientific owner decisions."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import PageMeta

ClaimKind = Literal["HYPOTHESIS", "FINDING", "LIMITATION", "RESEARCH_GAP"]
EvidenceRelation = Literal["SUPPORTS", "REFUTES", "CONTEXT"]
EvidenceKind = Literal["RESULT_METRIC", "RESULT_ARTIFACT", "CANONICAL_QUOTE", "OWNER_OBSERVATION"]


class ClaimEvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: EvidenceKind
    relation: EvidenceRelation
    rationale: str = Field(default="", max_length=4000)
    result_id: uuid.UUID | None = None
    expected_result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    metric_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    canonical_note_id: uuid.UUID | None = None
    expected_note_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, gt=0)
    exact_quote: str | None = Field(default=None, min_length=1, max_length=20000)
    observation: str | None = Field(default=None, min_length=1, max_length=20000)

    @model_validator(mode="after")
    def selection(self) -> "ClaimEvidenceSelection":
        groups = {
            "RESULT_METRIC": {"result_id", "expected_result_sha256", "metric_id"},
            "RESULT_ARTIFACT": {"result_id", "expected_result_sha256", "artifact_id"},
            "CANONICAL_QUOTE": {
                "canonical_note_id",
                "expected_note_sha256",
                "start_offset",
                "end_offset",
                "exact_quote",
            },
            "OWNER_OBSERVATION": {"observation"},
        }
        required = groups[self.source_kind]
        all_fields = set.union(*groups.values())
        if any(getattr(self, k) is None for k in required) or any(
            getattr(self, k) is not None for k in all_fields - required
        ):
            raise ValueError("Select exactly the fields for this evidence source kind")
        if self.source_kind == "CANONICAL_QUOTE":
            assert (
                self.end_offset is not None
                and self.start_offset is not None
                and self.exact_quote is not None
            )
            if self.end_offset - self.start_offset != len(self.exact_quote):
                raise ValueError(
                    "Offsets are Unicode code points and must match exact quote length"
                )
        if self.observation is not None and not self.observation.strip():
            raise ValueError("Observation needs text")
        return self


class ClaimFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=320)
    text: str = Field(min_length=1, max_length=20000)
    kind: ClaimKind = "HYPOTHESIS"
    conditions: str = Field(default="", max_length=12000)
    limitations: str = Field(default="", max_length=12000)
    evaluation_criteria: str = Field(default="", max_length=12000)
    research_question_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def nonblank(self) -> "ClaimFields":
        if not self.title.strip() or not self.text.strip():
            raise ValueError("Claim title and text need content")
        return self


class ClaimCreate(ClaimFields):
    project_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=120)
    evidence: list[ClaimEvidenceSelection] = Field(default_factory=list, max_length=40)


class ClaimRevise(ClaimFields):
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=120)
    evidence: list[ClaimEvidenceSelection] = Field(default_factory=list, max_length=40)


class ClaimEvidenceOut(BaseModel):
    id: uuid.UUID
    source_kind: EvidenceKind
    relation: EvidenceRelation
    rationale: str
    result_id: uuid.UUID | None
    result_sha256: str | None
    metric_id: uuid.UUID | None
    artifact_id: uuid.UUID | None
    canonical_note_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    paper_title: str | None
    note_sha256: str | None
    start_offset: int | None
    end_offset: int | None
    exact_quote: str | None
    observation: str | None
    metric_name: str | None
    metric_value: float | None
    metric_unit: str | None
    metric_split: str | None
    evaluation_protocol: str | None
    protocol_sha256: str | None
    dataset_sha256: str | None
    artifact_path: str | None
    artifact_sha256: str | None
    artifact_verification: str | None
    source_facts: dict[str, Any]
    source_sha256: str
    context_current: bool
    origin: str


class ClaimReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: uuid.UUID
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["ACCEPT", "REJECT", "COMMENT"]
    conclusion: str = Field(min_length=1, max_length=10000)
    acknowledge_gaps: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class ClaimReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    revision_id: uuid.UUID
    revision_sha256: str
    evidence_sha256: str
    decision: str
    conclusion: str
    acknowledge_gaps: bool
    idempotency_key: str
    reviewed_at: datetime


class ClaimRevisionOut(ClaimFields):
    id: uuid.UUID
    claim_id: uuid.UUID
    project_id: uuid.UUID
    revision: int
    sha256: str
    evidence_sha256: str
    created_at: datetime
    evidence: list[ClaimEvidenceOut]
    reviews: list[ClaimReviewOut]
    integrity_valid: bool
    context_current: bool
    gaps: list[str]
    scientific_state: Literal["CANDIDATE", "OWNER_ACCEPTED", "OWNER_REJECTED"]
    scientific_verification: Literal["NOT_AUTOMATICALLY_VERIFIED"] = "NOT_AUTOMATICALLY_VERIFIED"


class ClaimSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    revision: int
    created_at: datetime


class ClaimOut(ClaimSummary):
    current: ClaimRevisionOut


class ClaimPage(BaseModel):
    items: list[ClaimSummary]
    page: PageMeta


class ClaimRevisionPage(BaseModel):
    items: list[ClaimRevisionOut]
    page: PageMeta


class ClaimResultSourceOption(BaseModel):
    id: uuid.UUID
    receipt_id: str
    result_sha256: str
    claimed_run_status: str
    origin_verification: str
    validation_status: str
    integrity_valid: bool


class ClaimResultSourcePage(BaseModel):
    items: list[ClaimResultSourceOption]
    page: PageMeta
