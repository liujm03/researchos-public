"""Human-authored manuscript revisions and explicit evidence mappings."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import PageMeta
from app.schemas_evidence_bundles import EvidenceBundleOut

Check = Literal["UNCHECKED", "OWNER_CONFIRMED", "ISSUE"]


class PublicationSectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=240)
    kind: Literal["SKELETON", "MANUSCRIPT"]
    markdown: str = Field(default="", max_length=262144)
    status: Literal["NOT_STARTED", "DRAFT", "REVISING", "COMPLETED"] = "DRAFT"


class PublicationSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle_id: uuid.UUID
    expected_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublicationBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_quote: str = Field(min_length=1, max_length=20000)
    bundle_id: uuid.UUID
    claim_id: uuid.UUID
    claim_revision_id: uuid.UUID
    expected_claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    relation: Literal["SUPPORTS", "REFUTES", "CONTEXT"]
    paper_id: uuid.UUID | None = None
    format_check: Check = "UNCHECKED"
    metadata_check: Check = "UNCHECKED"
    support_check: Check = "UNCHECKED"
    note: str = Field(default="", max_length=4000)


class PublicationFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=320)
    target_venue: str = Field(default="", max_length=240)
    stage: Literal["DRAFT", "INTERNAL_REVIEW", "REVISING", "ARCHIVED", "SUBMITTED", "MAJOR_REVISION", "MINOR_REVISION", "ACCEPTED", "PUBLISHED"] = "DRAFT"
    sections: list[PublicationSectionInput] = Field(min_length=1, max_length=30)
    sources: list[PublicationSourceInput] = Field(default_factory=list, max_length=20)
    bindings: list[PublicationBindingInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def bounded_unique(self) -> "PublicationFields":
        if not self.title.strip() or any(not x.title.strip() for x in self.sections):
            raise ValueError("Nonblank publication and section titles are required")
        if len({x.key for x in self.sections}) != len(self.sections):
            raise ValueError("Section keys must be unique")
        if len({x.bundle_id for x in self.sources}) != len(self.sources):
            raise ValueError("Evidence bundles must be unique")
        if sum(len(x.markdown.encode("utf-8")) for x in self.sections) > 1048576:
            raise ValueError("Manuscript Markdown exceeds 1 MiB")
        return self


class PublicationPreview(BaseModel):
    fields: PublicationFields
    preview_sha256: str
    gaps: list[str]
    source_details: list[EvidenceBundleOut]
    scientific_execution_authorized: Literal[False] = False


class PublicationCreate(PublicationFields):
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_gaps: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class PublicationRevise(PublicationFields):
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_gaps: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class PublicationReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: uuid.UUID
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["ACCEPT", "REJECT", "COMMENT"]
    conclusion: str = Field(min_length=1, max_length=10000)
    acknowledge_gaps: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class PublicationReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    revision_id: uuid.UUID
    revision_sha256: str
    decision: str
    conclusion: str
    acknowledge_gaps: bool
    idempotency_key: str
    reviewed_at: datetime


class PublicationRevisionOut(PublicationFields):
    id: uuid.UUID
    publication_id: uuid.UUID
    project_id: uuid.UUID
    revision: int
    sha256: str
    source_sha256: str
    created_at: datetime
    source_details: list[EvidenceBundleOut]
    integrity_valid: bool
    context_current: bool
    gaps: list[str]
    reviews: list[PublicationReviewOut]
    owner_review_state: Literal["CANDIDATE", "OWNER_ACCEPTED", "OWNER_REJECTED"]
    scientific_verification: Literal["NOT_AUTOMATICALLY_VERIFIED"] = "NOT_AUTOMATICALLY_VERIFIED"
    scientific_execution_authorized: Literal[False] = False


class PublicationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    revision: int
    created_at: datetime


class PublicationOut(PublicationSummary):
    current: PublicationRevisionOut
    operation_receipt: "PublicationOperationReceipt | None" = None


class PublicationOperationReceipt(BaseModel):
    kind: Literal["create", "revision", "review"]
    request_sha256: str
    revision_id: uuid.UUID
    idempotency_key: str


class PublicationPage(BaseModel):
    items: list[PublicationSummary]
    page: PageMeta


class PublicationRevisionPage(BaseModel):
    items: list[PublicationRevisionOut]
    page: PageMeta
