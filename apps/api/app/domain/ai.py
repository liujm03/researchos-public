import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.domain.pdf_quotes import VerifiedPDFQuote

AnalysisScope = Literal["METADATA_ONLY", "ABSTRACT_ONLY", "FULL_TEXT"]
AnalysisMode = Literal["FAST", "STANDARD", "DEEP"]
AnalysisBudgetMode = Literal["LOCAL_LIMITS", "PROVIDER_QUOTA"]
ClaimType = Literal["PAPER_REPORTED", "AI_INTERPRETATION"]
NoteOutputContract = Literal["PAPER_ANALYSIS_V1", "CANONICAL_MARKDOWN_V2"]


class CanonicalMarkdownOutput(BaseModel):
    """Thin transport envelope; the approved Skill owns the unchanged Markdown."""

    model_config = ConfigDict(extra="forbid", strict=True)

    markdown: str = Field(min_length=1)


CANONICAL_MARKDOWN_SCHEMA: dict[str, object] = CanonicalMarkdownOutput.model_json_schema()

SECTION_KEYS = (
    "analytical_note",
    "problem_source",
    "research_gap",
    "research_question",
    "motivation",
    "contributions",
    "method_overview",
    "architecture",
    "dataset",
    "experiments",
    "results",
    "limitations",
    "reproduction",
    "research_inspiration",
)


class EvidenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: ClaimType
    source_section: str | None
    source_page: int | None
    source_block_index: int | None
    evidence_text: str | None


class AnalysisSectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_key: str
    body_markdown: str | None
    origin_type: ClaimType
    uncertainty: str | None
    evidence: list[EvidenceResult] = Field(default_factory=list)


class PaperAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    sections: list[AnalysisSectionResult]
    warnings: list[str]


@dataclass(frozen=True)
class SourceText:
    section_key: str
    text: str
    page: int | None
    block_index: int | None
    title: str | None = None
    ancestor_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class PDFReadingSource:
    attachment_id: uuid.UUID
    sha256: str
    page_count: int
    pages: tuple[int, ...]
    skill_key: str
    skill_version: str
    skill_instructions: str
    skill_sha256: str
    render_version: str
    template_text: str | None = None
    template_sha256: str | None = None
    stage: Literal["READ_PAGES", "WRITE_NOTE"] = "WRITE_NOTE"
    # Missing in historical frozen payloads: keep their original strict contract.
    note_output_contract: NoteOutputContract = "PAPER_ANALYSIS_V1"


@dataclass(frozen=True)
class PDFPageImage:
    page: int
    png: bytes
    sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class PaperAnalysisRequest:
    title: str
    year: int | None
    abstract: str | None
    scope: AnalysisScope
    mode: AnalysisMode
    source_texts: tuple[SourceText, ...]
    # None requests the Codex account's output allowance. API adapters must not
    # infer that an owner authorized unlimited paid API calls from this value.
    max_output_tokens: int | None
    pdf_source: PDFReadingSource | None = None
    # Ephemeral original-page transport. Never serialize these bytes in DB snapshots.
    page_images: tuple[PDFPageImage, ...] = ()
    # Frozen owner/Zotero identity + canonical file plan. These are data, not instructions.
    writer_identity: dict[str, object] | None = None
    # Long-paper writing consumes source-grounded receipts from actual original-page
    # reading calls; it never presents these receipts as the paper's raw quotations.
    reading_receipts: tuple[dict[str, object], ...] = ()
    reasoning_effort: str | None = None
    # Ephemeral verifier capabilities; never deserialized from owner/model JSON.
    verified_pdf_quotes: tuple["VerifiedPDFQuote", ...] = ()


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class AIAnalysisResponse:
    result: PaperAnalysisResult
    usage: AIUsage
    provider_response_id: str | None


@dataclass(frozen=True)
class AIProviderDescriptor:
    provider_key: str
    model_key: str | None
    configured: bool
    available: bool
    reason_code: str | None = None
    reason_message: str | None = None


class AIProvider(Protocol):
    provider_key: str
    model_key: str

    async def analyze_paper(self, request: PaperAnalysisRequest) -> AIAnalysisResponse: ...
