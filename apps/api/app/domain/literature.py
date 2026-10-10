"""Provider-independent candidates from online literature metadata sources.

Candidates are untrusted external facts. A service must compare provenance and
require the owner's review before applying them to human-edited Paper fields.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PaperCandidate:
    provider_key: str
    provider_id: str
    doi: str | None
    title: str | None
    authors: tuple[str, ...]
    year: int | None
    venue: str | None
    paper_type: str | None
    abstract: str | None
    url: str | None
    source_hash: str
    source_updated_at: datetime | None
    arxiv_id: str | None = None
    source_version: int | None = None
    pdf_url: str | None = None


class LiteratureProvider(Protocol):
    provider_key: str
    capabilities: frozenset[str]


class DoiLookupProvider(LiteratureProvider, Protocol):
    async def get_paper_by_doi(self, doi: str) -> PaperCandidate | None: ...


class PaperIdLookupProvider(LiteratureProvider, Protocol):
    async def get_paper_by_id(self, paper_id: str) -> PaperCandidate | None: ...


@dataclass(frozen=True)
class LiteratureSearchQuery:
    query: str
    from_year: int | None = None
    until_year: int | None = None
    limit: int = 20
    cursor: str | None = None


@dataclass(frozen=True)
class LiteratureSearchPage:
    items: tuple[PaperCandidate, ...]
    next_cursor: str | None
    total_results: int | None
    source_url: str
    fetched_at: datetime
    warnings: tuple[str, ...] = ()


class SearchLiteratureProvider(LiteratureProvider, Protocol):
    async def search_papers(self, query: LiteratureSearchQuery) -> LiteratureSearchPage: ...
