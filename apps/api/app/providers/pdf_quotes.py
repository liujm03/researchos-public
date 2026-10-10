"""Bounded native PDFium page text; no OCR, section parsing or AI."""

from contextlib import closing

import pypdfium2 as pdfium  # type: ignore[import-untyped]

from app.domain.pdf_quotes import NativePDFPageText
from app.errors import DomainError

MAX_QUOTE_PAGES = 128
MAX_NATIVE_PAGE_CHARACTERS = 1_000_000
MAX_NATIVE_TOTAL_CHARACTERS = 8_000_000


class PDFiumQuoteProvider:
    version = f"pdfium-native-quote-v1/{pdfium.PYPDFIUM_INFO}/{pdfium.PDFIUM_INFO}"

    def extract(self, content: bytes, pages: tuple[int, ...]) -> tuple[NativePDFPageText, ...]:
        if not pages or len(pages) > MAX_QUOTE_PAGES or len(set(pages)) != len(pages):
            raise DomainError(
                "PDF_QUOTE_LIMIT", "Citation page verification exceeds its bound", 422
            )
        extracted: list[NativePDFPageText] = []
        total = 0
        try:
            with pdfium.PdfDocument(content) as document:
                for number in pages:
                    if (
                        isinstance(number, bool)
                        or not isinstance(number, int)
                        or not 1 <= number <= len(document)
                    ):
                        raise DomainError(
                            "PDF_QUOTE_PAGE_INVALID", "Citation physical page is unavailable", 422
                        )
                    with (
                        closing(document[number - 1]) as page,
                        closing(page.get_textpage()) as native,
                    ):
                        count = native.count_chars()
                        if count > MAX_NATIVE_PAGE_CHARACTERS:
                            raise DomainError(
                                "PDF_QUOTE_LIMIT",
                                "Native page text exceeds verification bound",
                                422,
                            )
                        total += count
                        if total > MAX_NATIVE_TOTAL_CHARACTERS:
                            raise DomainError(
                                "PDF_QUOTE_LIMIT", "Native text exceeds verification bound", 422
                            )
                        text = native.get_text_range(errors="strict")
                    extracted.append(NativePDFPageText(number, len(document), text, self.version))
            return tuple(extracted)
        except DomainError:
            raise
        except Exception:
            raise DomainError(
                "PDF_QUOTE_TEXT_UNAVAILABLE", "Native original-page text could not be read", 422
            ) from None
