"""Untrusted bibliography file candidates, before any owner-confirmed import."""

from dataclasses import dataclass
from typing import Literal, Protocol

BibliographyFormat = Literal["bibtex", "ris"]


@dataclass(frozen=True)
class BibliographyCandidate:
    key: str | None
    title: str | None
    authors: tuple[str, ...]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    abstract: str | None
    url: str | None
    entry_type: str
    source_key: str
    source_hash: str
    errors: tuple[str, ...]


class BibliographyParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BibliographyParser(Protocol):
    def parse(self, content: str, format: BibliographyFormat) -> list[BibliographyCandidate]: ...
