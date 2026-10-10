"""Ports for local discovery links, not remote literature search results."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DiscoveryVenue:
    key: str
    label: str
    publisher: str
    homepage_url: str
    search_url: str
    search_note: str


@dataclass(frozen=True)
class DiscoveryGroup:
    key: str
    label: str
    items: tuple[DiscoveryVenue, ...]


class LiteratureDiscoveryLinksProvider(Protocol):
    def links(self, query: str, from_year: int, until_year: int) -> tuple[DiscoveryGroup, ...]: ...
