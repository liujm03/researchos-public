from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ParsedBlockData:
    block_index: int
    page_number: int
    section_key: str
    text: str


@dataclass(frozen=True)
class ParsedSectionData:
    section_key: str
    title: str | None
    start_page: int | None
    end_page: int | None
    coverage_status: str
    text: str | None
    semantic_key: str | None = None
    heading_level: int | None = None
    parent_section_key: str | None = None


@dataclass(frozen=True)
class ParseWarningData:
    code: str
    message: str
    page_number: int | None = None


@dataclass(frozen=True)
class ParseResult:
    page_count: int
    extracted_characters: int
    status: str
    blocks: tuple[ParsedBlockData, ...]
    sections: tuple[ParsedSectionData, ...]
    warnings: tuple[ParseWarningData, ...]


class PaperParser(Protocol):
    parser_name: str
    parser_version: str

    def parse(self, path: Path, *, max_pages: int) -> ParseResult: ...
