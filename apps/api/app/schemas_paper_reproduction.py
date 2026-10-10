"""Explicit legacy compatibility and original-PDF-derived canonical preparation inputs."""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.paper_reproduction import (
    NoteExcerptRange,
    ReproductionScope,
    ReproductionSelection,
    ReproductionStage,
)
from app.schemas import PageMeta


class ReproductionExcerptRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Excerpt end must be greater than start")
        return self


class PaperReproductionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: ReproductionStage = "PLAN"
    source_scope: ReproductionScope | None = None
    goal: str = Field(min_length=1, max_length=4000)
    note_id: uuid.UUID | None = None
    parsed_document_id: uuid.UUID | None = None
    section_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    canonical_note_id: uuid.UUID | None = None
    expected_note_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    selection_mode: Literal["FULL", "EXCERPTS"] = "FULL"
    excerpt_ranges: list[ReproductionExcerptRange] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def source_contract(self) -> Self:
        if self.canonical_note_id is not None:
            if self.expected_note_sha256 is None:
                raise ValueError("Canonical preparation requires the exact note SHA-256")
            if self.note_id or self.parsed_document_id or self.section_ids:
                raise ValueError("Canonical and legacy source selections cannot be mixed")
            if self.source_scope not in {None, "DERIVED_NOTE"}:
                raise ValueError("Canonical text is DERIVED_NOTE, not original PDF input")
            if (self.selection_mode == "FULL" and self.excerpt_ranges) or (
                self.selection_mode == "EXCERPTS" and not self.excerpt_ranges
            ):
                raise ValueError("Choose either complete Markdown or explicit excerpt ranges")
        elif (
            self.source_scope == "DERIVED_NOTE"
            or self.expected_note_sha256 is not None
            or self.excerpt_ranges
            or self.selection_mode != "FULL"
        ):
            raise ValueError("Canonical fields require a canonical note identity")
        return self

    def selection(self) -> ReproductionSelection:
        return ReproductionSelection(
            stage=self.stage,
            source_scope=self.source_scope
            or ("DERIVED_NOTE" if self.canonical_note_id else "ABSTRACT_ONLY"),
            goal=self.goal,
            note_id=self.note_id,
            parsed_document_id=self.parsed_document_id,
            section_ids=tuple(self.section_ids),
            canonical_note_id=self.canonical_note_id,
            expected_note_sha256=self.expected_note_sha256,
            selection_mode=self.selection_mode,
            excerpt_ranges=tuple(
                NoteExcerptRange(row.start, row.end) for row in self.excerpt_ranges
            ),
        )


class PaperReproductionCreateRequest(PaperReproductionPreviewRequest):
    title: str = Field(min_length=1, max_length=240)
    instructions: str = Field(default="", max_length=4000)
    workspace_id: str = Field(min_length=1, max_length=80)
    mode: Literal["read_only", "workspace_write"] = "read_only"
    expected_context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class ReproductionExcerptOut(ReproductionExcerptRange):
    text: str
    sha256: str


class ReproductionHeadingOut(BaseModel):
    title: str
    level: int
    start: int
    end: int


class ReproductionSourceOut(BaseModel):
    paper_title: str | None = None
    id: uuid.UUID
    paper_id: uuid.UUID
    reading_job_id: uuid.UUID
    reading_plan_id: uuid.UUID
    pdf_attachment_id: uuid.UUID
    note_sha256: str
    note_characters: int
    note_bytes: int
    pdf_sha256: str
    page_count: int
    skill_key: str
    skill_version: str
    skill_sha256: str
    source_manifest_sha256: str | None
    skill_provenance: Literal["FROZEN_FILES", "LEGACY_INSTRUCTIONS"]
    provenance_gaps: list[str] = Field(default_factory=list)
    created_at: datetime
    note_origin: Literal["AI_DERIVED"] = "AI_DERIVED"
    origin_reading_scope: Literal["FULL_TEXT"] = "FULL_TEXT"
    pdf_delivery: Literal["BOUND_NOT_SENT"] = "BOUND_NOT_SENT"
    pdf_bytes_verified: bool = False
    can_prepare: bool
    gaps: list[str]


class ReproductionSourceContentOut(ReproductionSourceOut):
    markdown: str
    headings: list[ReproductionHeadingOut]
    range_unit: Literal["UNICODE_CODE_POINTS"] = "UNICODE_CODE_POINTS"


class ReproductionSourcePage(BaseModel):
    items: list[ReproductionSourceOut]
    page: PageMeta


class PaperReproductionPreviewOut(BaseModel):
    task_id: uuid.UUID | None
    paper_id: uuid.UUID
    paper_title: str
    paper_metadata_version: int
    stage: ReproductionStage
    source_scope: ReproductionScope
    goal: str
    note_id: uuid.UUID | None
    note_revision: int | None
    note_review_status: str | None
    parsed_document_id: uuid.UUID | None
    pdf_sha256: str | None
    parser_name: str | None
    parser_version: str | None
    parser_status: str | None
    section_ids: list[uuid.UUID]
    context_text: str
    context_sha256: str
    context_characters: int
    max_context_characters: int
    warnings: list[str]
    context_version: str = "paper-reproduction-v1"
    canonical_note_id: uuid.UUID | None = None
    canonical_note_sha256: str | None = None
    reading_job_id: uuid.UUID | None = None
    reading_plan_id: uuid.UUID | None = None
    pdf_attachment_id: uuid.UUID | None = None
    page_count: int | None = None
    reading_plan_sha256: str | None = None
    skill_key: str | None = None
    skill_version: str | None = None
    skill_sha256: str | None = None
    source_manifest_sha256: str | None = None
    skill_provenance: Literal["FROZEN_FILES", "LEGACY_INSTRUCTIONS"] | None = None
    provenance_gaps: list[str] = Field(default_factory=list)
    note_origin: Literal["AI_DERIVED"] | None = None
    origin_reading_scope: Literal["FULL_TEXT"] | None = None
    pdf_delivery: Literal["BOUND_NOT_SENT"] | None = None
    pdf_bytes_verified: bool = False
    selection_mode: Literal["FULL", "EXCERPTS"] | None = None
    excerpts: list[ReproductionExcerptOut] = Field(default_factory=list)
    omitted_ranges: list[ReproductionExcerptRange] = Field(default_factory=list)
    range_unit: Literal["UNICODE_CODE_POINTS"] = "UNICODE_CODE_POINTS"
    context_bytes: int | None = None
    max_context_bytes: int | None = None
