"""Native original-page text is a literal citation verifier, not a paper summary."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NativePDFPageText:
    physical_page: int
    page_count: int
    text: str
    extractor_version: str


@dataclass(frozen=True)
class VerifiedPDFQuote:
    physical_page: int
    pdf_sha256: str
    quote_sha256: str
    native_text_sha256: str
    normalized_quote_sha256: str
    extractor_version: str
    normalizer_version: str
    match_mode: str


class PDFQuoteProvider(Protocol):
    def extract(self, content: bytes, pages: tuple[int, ...]) -> tuple[NativePDFPageText, ...]: ...
