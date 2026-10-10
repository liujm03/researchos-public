"""Explicit project-scoped metadata search and candidate adoption contracts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import PageMeta


class LiteratureSearchSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID | None = None
    query: str = Field(min_length=2, max_length=500)
    terms: list[str] = Field(default_factory=list, max_length=20)
    venue_keys: list[str] = Field(default_factory=list, max_length=20)
    from_year: int | None = Field(default=None, ge=1400, le=2200)
    until_year: int | None = Field(default=None, ge=1400, le=2200)
    page_size: int = Field(default=20, ge=1, le=50)
    provider_key: str = Field(default="crossref", pattern=r"^[a-z][a-z0-9_]{0,63}$")

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2 or any(ord(c) < 32 for c in value):
            raise ValueError("A nonempty metadata query is required")
        return value

    @field_validator("terms", "venue_keys")
    @classmethod
    def clean_values(cls, values: list[str]) -> list[str]:
        cleaned = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > 120 for value in cleaned):
            raise ValueError("Search values must have 1 to 120 characters")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def valid_years(self) -> "LiteratureSearchSelection":
        if self.from_year is not None and self.until_year is not None:
            if self.from_year > self.until_year:
                raise ValueError("from_year must be at most until_year")
        return self


class LiteratureVenueOption(BaseModel):
    key: str
    label: str


class LiteratureQuestionOption(BaseModel):
    id: uuid.UUID
    question: str


class LiteratureResearchLink(BaseModel):
    key: str
    label: str
    publisher: str
    homepage_url: str
    search_url: str
    search_note: str


class LiteratureResearchLinkGroup(BaseModel):
    key: str
    label: str
    items: list[LiteratureResearchLink]


class LiteratureResearchLinks(BaseModel):
    project_id: uuid.UUID
    project_name: str
    query: str
    recent_from_year: int
    recent_until_year: int
    questions: list[LiteratureQuestionOption]
    groups: list[LiteratureResearchLinkGroup]


class LiteratureRecommendationOptions(BaseModel):
    owner_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    project_version: int
    recent_from_year: int
    recent_until_year: int
    questions: list[LiteratureQuestionOption]
    venues: list[LiteratureVenueOption]
    provider_key: str
    coverage_note: str


class LiteratureSearchTransmission(BaseModel):
    query: str
    from_year: int | None
    until_year: int | None
    page_size: int


class LiteratureSearchPreviewOut(BaseModel):
    project_id: uuid.UUID
    project_name: str
    question: str | None
    selection: LiteratureSearchSelection
    context_sha256: str
    transmission: LiteratureSearchTransmission
    coverage_note: str


class LiteratureSearchStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection: LiteratureSearchSelection
    expected_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_metadata_search: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class LiteratureSearchNextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve_metadata_search: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class LiteratureCandidateOut(BaseModel):
    id: uuid.UUID
    candidate_sha256: str
    provider_key: str
    provider_id: str
    title: str | None
    doi: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    paper_type: str | None
    abstract: str | None
    url: str | None
    source_hash: str
    source_updated_at: datetime | None
    venue_key: str | None
    venue_status: Literal["MATCHED", "OTHER", "UNKNOWN"]
    in_scope: bool
    publication_status: Literal["METADATA_REPORTED", "PREPRINT", "UNKNOWN"]
    rank_score: int
    match_reasons: list[str]
    warnings: list[str]
    review_status: Literal["CANDIDATE", "ADOPTED"]
    paper_id: uuid.UUID | None
    can_adopt: bool
    adoption_warning: str | None


class LiteratureSearchBatchSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    parent_batch_id: uuid.UUID | None
    provider_key: str
    query: str
    status: Literal["FETCHING", "COMPLETED", "FAILED", "NEEDS_ATTENTION"]
    created_at: datetime
    completed_at: datetime | None
    candidate_count: int
    has_more: bool
    error_code: str | None
    error_message: str | None


class LiteratureSearchBatchOut(LiteratureSearchBatchSummary):
    project_name: str
    project_version: int
    question_text: str | None
    selection: LiteratureSearchSelection
    context_sha256: str
    source_url: str | None
    fetched_at: datetime | None
    total_results: int | None
    retry_after_seconds: int | None
    warnings: list[str]
    coverage_note: str
    items: list[LiteratureCandidateOut]


class LiteratureSearchBatchPage(BaseModel):
    items: list[LiteratureSearchBatchSummary]
    page: PageMeta


class LiteratureCandidateAdoptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LiteratureCandidateAdoptOut(BaseModel):
    candidate_id: uuid.UUID
    paper_id: uuid.UUID
    created: bool
    already_adopted: bool
