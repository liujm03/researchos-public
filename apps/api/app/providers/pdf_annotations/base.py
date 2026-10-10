from typing import Protocol

from app.schemas_pdf_annotations import PdfAnnotationOut


class PdfAnnotationProvider(Protocol):
    def page_count(self, source: bytes) -> int: ...

    def export(self, source: bytes, annotations: list[PdfAnnotationOut]) -> bytes: ...
