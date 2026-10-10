from dataclasses import dataclass
from typing import Protocol

from app.domain.ai import PDFPageImage


@dataclass(frozen=True)
class ReadingSkillSource:
    path: str
    role: str
    sha256: str
    size_bytes: int
    content: str


@dataclass(frozen=True)
class ReadingSkillReceipt:
    key: str
    version: str
    instructions: str
    sha256: str
    warnings: tuple[str, ...] = ()
    template_text: str | None = None
    template_sha256: str | None = None
    source_files: tuple[ReadingSkillSource, ...] = ()


class ReadingSkillProvider(Protocol):
    def load(self) -> ReadingSkillReceipt: ...


class PDFVisualProvider(Protocol):
    render_version: str

    def page_count(self, content: bytes, *, max_pages: int | None) -> int: ...

    def render(self, content: bytes, pages: tuple[int, ...]) -> tuple[PDFPageImage, ...]: ...
