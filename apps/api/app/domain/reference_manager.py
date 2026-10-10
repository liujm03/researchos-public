from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ReferenceItem:
    key: str
    version: int
    item_type: str
    title: str
    creators: tuple[str, ...]
    year: int | None
    doi: str | None
    abstract: str | None
    url: str | None
    venue: str | None
    tags: tuple[str, ...]
    raw: dict[str, Any]
    venue_fields: dict[str, str] | None = None


@dataclass(frozen=True)
class ReferenceCollection:
    key: str
    name: str
    parent_key: str | None


@dataclass(frozen=True)
class ReferenceAttachment:
    key: str
    version: int
    title: str
    content_type: str | None
    filename: str | None
    link_mode: str | None


@dataclass
class AttachmentStream:
    chunks: AsyncIterator[bytes]
    close: Callable[[], Awaitable[None]]
    content_type: str
    content_length: int | None


@dataclass(frozen=True)
class IndexedText:
    content: str
    indexed_pages: int | None
    total_pages: int | None


@dataclass(frozen=True)
class ReferencePage:
    """One page from an incremental source, with its library snapshot version."""

    items: tuple[ReferenceItem, ...]
    library_version: int | None
    raw_count: int
    changed_parent_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceCatalogPage:
    items: tuple[ReferenceItem, ...]
    raw_count: int
    source_total: int | None
    next_start: int | None


class ReferenceManagerProvider(Protocol):
    provider_key: str

    async def status(self) -> dict[str, str | bool | None]: ...

    async def search_items(
        self, query: str, limit: int, start: int, collection_key: str | None = None
    ) -> list[ReferenceItem]: ...

    async def get_item(self, item_key: str) -> ReferenceItem | None: ...

    async def list_collections(self, limit: int, start: int) -> list[ReferenceCollection]: ...

    async def list_attachments(self, item_key: str) -> list[ReferenceAttachment]: ...

    async def open_attachment(self, attachment_key: str) -> AttachmentStream: ...

    async def get_indexed_fulltext(self, attachment_key: str) -> IndexedText | None: ...


@runtime_checkable
class IncrementalReferenceManagerProvider(ReferenceManagerProvider, Protocol):
    """Optional capability for a provider with a stable library version cursor."""

    async def list_updated_items(
        self, since: int | None, limit: int, start: int
    ) -> ReferencePage: ...


@runtime_checkable
class CatalogReferenceManagerProvider(ReferenceManagerProvider, Protocol):
    """Optional raw pagination metadata for a complete browsable catalog."""

    async def search_items_page(
        self, query: str, limit: int, start: int, collection_key: str | None = None
    ) -> ReferenceCatalogPage: ...
