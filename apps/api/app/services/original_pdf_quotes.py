"""Read-only literal quotation verification against the approved original bytes."""

import hashlib
import re
import unicodedata
from dataclasses import asdict, replace

from sqlalchemy.orm import Session

from app.domain.ai import PaperAnalysisRequest, PaperAnalysisResult
from app.domain.pdf_quotes import PDFQuoteProvider, VerifiedPDFQuote
from app.errors import DomainError
from app.models import PaperAnalysisJob
from app.providers.registry import pdf_quote_provider, storage_provider
from app.services.pdf_reading import _attachment, _read_verified, validate_pdf_frozen

NORMALIZER_VERSION = "literal-nfc-whitespace-ligatures-soft-hyphen-linewrap-v1"
MAX_QUOTES = 512
MAX_QUOTE_CHARACTERS = 32_000
MAX_TOTAL_QUOTE_CHARACTERS = 1_000_000
MAX_PAGES = 128
MAX_PAGE_CHARACTERS = 1_000_000
MAX_TOTAL_PAGE_CHARACTERS = 8_000_000
_LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
)


def normalized_literal(text: str, *, join_linewrap: bool = False) -> str:
    # NFC preserves mathematical and compatibility character distinctions.
    result = unicodedata.normalize("NFC", text).translate(_LIGATURES).replace("\u00ad", "")
    if join_linewrap:
        # Never remove an ordinary in-line hyphen, digit/operator or punctuation.
        result = re.sub(r"(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[a-z])", "", result)
    return " ".join(result.split())


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def verify_new_original_quotes(
    db: Session,
    job: PaperAnalysisJob,
    request: PaperAnalysisRequest,
    result: PaperAnalysisResult,
    *,
    provider: PDFQuoteProvider | None = None,
) -> tuple[PaperAnalysisRequest, list[dict[str, object]]]:
    """Return ephemeral proof only; never mutate DB, candidate or filesystem."""
    source = validate_pdf_frozen(db, job, request)
    descriptor = request.pdf_source
    assert descriptor is not None
    existing: set[tuple[int | None, str | None]] = set()
    covered: set[int] = set(descriptor.pages)
    for receipt in request.reading_receipts:
        pages = receipt.get("pages")
        if isinstance(pages, list):
            covered.update(
                page for page in pages if isinstance(page, int) and not isinstance(page, bool)
            )
        raw = receipt.get("result")
        if isinstance(raw, dict):
            parsed = PaperAnalysisResult.model_validate(raw)
            existing.update(
                (item.source_page, item.evidence_text)
                for section in parsed.sections
                for item in section.evidence
            )
    pending: list[tuple[int, int, str, int, str]] = []
    total = 0
    for section_index, section in enumerate(result.sections):
        for evidence_index, evidence in enumerate(section.evidence):
            quote, page = evidence.evidence_text, evidence.source_page
            if not quote or page in descriptor.pages or (page, quote) in existing:
                continue
            details = {
                "note_section": section.section_key,
                "evidence_index": evidence_index,
                "source_page": page,
            }
            if (
                page is None
                or isinstance(page, bool)
                or not 1 <= page <= source.page_count
                or page not in covered
                or evidence.source_block_index is not None
            ):
                raise DomainError(
                    "PDF_QUOTE_PAGE_INVALID",
                    "Quote must cite a completed original physical page",
                    422,
                    details=details,
                )
            total += len(quote)
            if (
                len(pending) >= MAX_QUOTES
                or len(quote) > MAX_QUOTE_CHARACTERS
                or total > MAX_TOTAL_QUOTE_CHARACTERS
            ):
                raise DomainError(
                    "PDF_QUOTE_LIMIT",
                    "Citation verification exceeds its bound",
                    422,
                    details=details,
                )
            pending.append((section_index, evidence_index, quote, page, section.section_key))
    if not pending:
        return replace(request, verified_pdf_quotes=()), []
    pages_to_check = tuple(sorted({item[3] for item in pending}))
    if len(pages_to_check) > MAX_PAGES:
        raise DomainError(
            "PDF_QUOTE_LIMIT", "Too many citation pages for one local verification", 422
        )
    attachment = _attachment(db, job.user_id, job.paper_id, source.attachment_id)
    content = await _read_verified(
        attachment, storage_provider(attachment.storage_provider), source.sha256
    )
    extracted = (provider or pdf_quote_provider()).extract(content, pages_to_check)
    if (
        len(extracted) != len(pages_to_check)
        or tuple(item.physical_page for item in extracted) != pages_to_check
    ):
        raise DomainError(
            "PDF_QUOTE_TEXT_UNAVAILABLE",
            "Native extraction did not return the exact requested pages",
            422,
        )
    if any(item.page_count != source.page_count for item in extracted):
        raise DomainError("PDF_SOURCE_CHANGED", "Original physical page count changed", 409)
    if (
        any(len(item.text) > MAX_PAGE_CHARACTERS for item in extracted)
        or sum(len(item.text) for item in extracted) > MAX_TOTAL_PAGE_CHARACTERS
    ):
        raise DomainError("PDF_QUOTE_LIMIT", "Native page text exceeds verification bound", 422)
    texts = {item.physical_page: item for item in extracted}
    proofs: list[VerifiedPDFQuote] = []
    audit: list[dict[str, object]] = []
    for section_index, evidence_index, quote, page, section_key in pending:
        item = texts[page]
        normalized_quote = normalized_literal(quote)
        details = {
            "note_section": section_key,
            "evidence_index": evidence_index,
            "source_page": page,
        }
        if not normalized_quote or not normalized_literal(item.text):
            raise DomainError(
                "PDF_QUOTE_TEXT_UNAVAILABLE",
                "Native original page text is empty; OCR was not inferred",
                422,
                details=details,
            )
        if normalized_quote in normalized_literal(item.text):
            mode = "NFC_WHITESPACE_TYPOGRAPHY_LITERAL"
        elif normalized_quote in normalized_literal(item.text, join_linewrap=True):
            mode = "ASCII_LETTER_LINEWRAP_HYPHEN_JOIN"
        else:
            raise DomainError(
                "PDF_QUOTE_MISMATCH",
                "Exact citation text is absent from the declared original page",
                422,
                details=details,
            )
        proof = VerifiedPDFQuote(
            page,
            source.sha256,
            _hash(quote),
            _hash(item.text),
            _hash(normalized_quote),
            item.extractor_version,
            NORMALIZER_VERSION,
            mode,
        )
        proofs.append(proof)
        audit.append(
            asdict(proof)
            | {
                "note_section": section_key,
                "section_index": section_index,
                "evidence_index": evidence_index,
            }
        )
    return replace(request, verified_pdf_quotes=tuple(proofs)), audit
