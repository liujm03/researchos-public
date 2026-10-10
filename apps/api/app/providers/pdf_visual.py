"""Original PDF page raster transport. No text extraction or reorganization."""

import hashlib
from contextlib import closing
from io import BytesIO

import pypdfium2 as pdfium  # type: ignore[import-untyped]

from app.domain.ai import PDFPageImage
from app.errors import DomainError

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_PAGE_PIXELS = 12_000_000


class PDFiumVisualProvider:
    render_version = f"pdfium-original-page-v1-scale3-rgb/{pdfium.PYPDFIUM_INFO}/{pdfium.PDFIUM_INFO}"

    def page_count(self, content: bytes, *, max_pages: int | None) -> int:
        try:
            with pdfium.PdfDocument(content) as document:
                count = len(document)
                if count < 1 or (max_pages is not None and count > max_pages):
                    raise DomainError("PDF_PAGE_LIMIT", "PDF page count exceeds configured limit", 422)
                return count
        except DomainError:
            raise
        except Exception:
            raise DomainError("PDF_UNREADABLE", "Original PDF could not be opened", 422) from None

    def render(self, content: bytes, pages: tuple[int, ...]) -> tuple[PDFPageImage, ...]:
        if not pages or len(pages) > 20 or len(set(pages)) != len(pages):
            raise DomainError("PDF_PAGE_RANGE_INVALID", "Select one to twenty unique PDF pages", 422)
        images: list[PDFPageImage] = []
        try:
            with pdfium.PdfDocument(content) as document:
                for number in pages:
                    if isinstance(number, bool) or not 1 <= number <= len(document):
                        raise DomainError("PDF_PAGE_RANGE_INVALID", "PDF page is outside the source", 422)
                    with closing(document[number - 1]) as page:
                        width, height = page.get_size()
                        if width <= 0 or height <= 0 or width * height * 9 > MAX_PAGE_PIXELS:
                            raise DomainError("PDF_PAGE_SIZE_LIMIT", "PDF page dimensions exceed rendering limit", 422)
                        bitmap = page.render(scale=3)
                        try:
                            original_image = bitmap.to_pil()
                            try:
                                image = original_image.convert("RGB")
                            finally:
                                original_image.close()
                            try:
                                with BytesIO() as output:
                                    image.save(output, format="PNG")
                                    data = output.getvalue()
                                if len(data) > MAX_IMAGE_BYTES:
                                    raise DomainError("PDF_PAGE_SIZE_LIMIT", "Rendered page exceeds image limit", 422)
                                images.append(PDFPageImage(number, data, hashlib.sha256(data).hexdigest(), image.width, image.height))
                                if sum(len(item.png) for item in images) > 128 * 1024 * 1024:
                                    raise DomainError("PDF_PAGE_SIZE_LIMIT", "Page batch exceeds image transport limit", 422)
                            finally:
                                image.close()
                        finally:
                            bitmap.close()
            return tuple(images)
        except DomainError:
            raise
        except Exception:
            raise DomainError("PDF_RENDER_FAILED", "Original PDF page could not be rendered", 422) from None
