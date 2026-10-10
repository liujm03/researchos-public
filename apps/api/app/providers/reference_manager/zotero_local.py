import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from app.domain.reference_manager import (
    AttachmentStream,
    IndexedText,
    ReferenceAttachment,
    ReferenceCatalogPage,
    ReferenceCollection,
    ReferenceItem,
    ReferencePage,
)
from app.domain.venue_cache import ReferenceVenueCacheProvider
from app.errors import DomainError
from app.providers.reference_manager.catalog import catalog_page
from app.providers.reference_manager.zotero_venue_fields import extract_venue_fields


class ZoteroLocalAdapter:
    provider_key = "zotero_local"

    def __init__(self, base_url: str, *, venue_cache: ReferenceVenueCacheProvider | None = None) -> None:
        self.venue_cache = venue_cache
        try:
            parsed = urlparse(base_url.rstrip("/"))
            port = parsed.port
        except ValueError:
            raise DomainError(
                "CONFIGURATION_ERROR", "Zotero Local API URL is invalid", 503
            ) from None
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or port != 23119
            or parsed.path != "/api"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise DomainError(
                "CONFIGURATION_ERROR",
                "Zotero Local API URL must be loopback port 23119 under /api",
                503,
            )
        self.base_url = base_url.rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.base_url}/",
            timeout=httpx.Timeout(10.0, read=30.0),
            trust_env=False,
            headers={"Zotero-API-Version": "3", "User-Agent": "ResearchOS/0.1"},
        )

    @staticmethod
    def _key(value: str) -> str:
        if not re.fullmatch(r"[A-Z0-9]{8}", value):
            raise DomainError("VALIDATION_ERROR", "Invalid Zotero item key", 422)
        return value

    async def _get(self, path: str, params: dict[str, str | int] | None = None) -> httpx.Response:
        try:
            async with self._client() as client:
                response = await client.get(path, params=params)
        except httpx.RequestError as exc:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Zotero Desktop is not reachable", 503
            ) from exc
        if response.status_code == 403:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Enable Zotero Local API in Zotero settings", 503
            )
        if response.status_code == 404:
            return response
        if response.status_code >= 400:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", f"Zotero Local API returned {response.status_code}", 503
            )
        return response

    async def status(self) -> dict[str, str | bool | None]:
        response = await self._get("")
        if response.status_code == 404:
            raise DomainError("PROVIDER_UNAVAILABLE", "Zotero Local API is unavailable", 503)
        server_id = response.headers.get("Zotero-Server-ID")
        if not server_id:
            raise DomainError(
                "CAPABILITY_UNAVAILABLE",
                "Zotero Local API did not provide an instance ID; update Zotero for safe sync",
                503,
            )
        return {
            "connected": True,
            "provider_key": self.provider_key,
            "mode": "local",
            "server_id": server_id,
            "api_version": response.headers.get("Zotero-API-Version", "3"),
            "can_read": True,
            "can_download_attachments": True,
            "can_write": False,
            "incremental_sync": True,
        }

    async def list_updated_items(self, since: int | None, limit: int, start: int) -> ReferencePage:
        params: dict[str, str | int] = {"limit": limit, "start": start, "format": "json"}
        if since is not None:
            params["since"] = since
        response = await self._get("users/0/items", params=params)
        if response.status_code == 404:
            raise DomainError("PROVIDER_UNAVAILABLE", "Zotero items endpoint is unavailable", 503)
        raw_version = response.headers.get("Last-Modified-Version")
        try:
            library_version = int(raw_version) if raw_version is not None else None
        except ValueError:
            library_version = None
        raw_items = response.json()
        child_types = {"attachment", "note", "annotation"}
        return ReferencePage(
            items=tuple(
                self._with_venue_cache(self._item(item))
                for item in raw_items
                if item.get("data", {}).get("itemType") not in child_types
            ),
            library_version=library_version,
            raw_count=len(raw_items),
            changed_parent_keys=tuple(
                item["data"]["parentItem"]
                for item in raw_items
                if item.get("data", {}).get("itemType") == "attachment"
                and item.get("data", {}).get("parentItem")
            ),
        )

    @staticmethod
    def _year(value: str | None) -> int | None:
        match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", value or "")
        return int(match.group()) if match else None

    @classmethod
    def _item(cls, source: dict[str, Any]) -> ReferenceItem:
        data = source.get("data", {})
        creators = tuple(
            " ".join(filter(None, [person.get("firstName"), person.get("lastName")])).strip()
            or person.get("name", "")
            for person in data.get("creators", [])
        )
        return ReferenceItem(
            key=source.get("key") or data.get("key", ""),
            version=int(source.get("version") or data.get("version") or 0),
            item_type=data.get("itemType", "unknown"),
            title=data.get("title") or data.get("shortTitle") or "Untitled",
            creators=tuple(name for name in creators if name),
            year=cls._year(data.get("date")),
            doi=data.get("DOI") or None,
            abstract=data.get("abstractNote") or None,
            url=data.get("url") or None,
            venue=data.get("publicationTitle") or data.get("conferenceName") or None,
            tags=tuple(tag.get("tag", "") for tag in data.get("tags", []) if tag.get("tag")),
            raw=source,
            venue_fields=extract_venue_fields(data),
        )

    def _with_venue_cache(self, item: ReferenceItem) -> ReferenceItem:
        if self.venue_cache is None or not item.venue:
            return item
        fields = self.venue_cache.fields(item.venue)
        if fields is None:
            return replace(item, venue_fields=None)  # Cannot erase an old plugin snapshot on failure.
        return replace(item, venue_fields=(item.venue_fields or {}) | fields)

    async def search_items(
        self, query: str, limit: int, start: int, collection_key: str | None = None
    ) -> list[ReferenceItem]:
        return list((await self.search_items_page(query, limit, start, collection_key)).items)

    async def search_items_page(
        self, query: str, limit: int, start: int, collection_key: str | None = None
    ) -> ReferenceCatalogPage:
        if not 1 <= limit <= 100 or start < 0:
            raise DomainError("VALIDATION_ERROR", "Invalid Zotero pagination", 422)
        params: dict[str, str | int] = {"limit": limit, "start": start, "format": "json"}
        if query:
            params["q"] = query
        path = (
            f"users/0/collections/{self._key(collection_key)}/items/top"
            if collection_key
            else "users/0/items/top"
        )
        response = await self._get(path, params=params)
        if response.status_code == 404:
            return ReferenceCatalogPage((), 0, 0, None)
        raw = response.json()
        records = tuple(
            self._with_venue_cache(self._item(item))
            for item in raw
            if item.get("data", {}).get("itemType") not in {"attachment", "note", "annotation"}
        )
        return catalog_page(
            records,
            raw_count=len(raw),
            source_total=response.headers.get("Total-Results"),
            limit=limit,
            start=start,
        )

    async def get_item(self, item_key: str) -> ReferenceItem | None:
        response = await self._get(f"users/0/items/{self._key(item_key)}")
        return None if response.status_code == 404 else self._with_venue_cache(self._item(response.json()))

    async def list_collections(self, limit: int, start: int) -> list[ReferenceCollection]:
        response = await self._get(
            "users/0/collections", params={"limit": limit, "start": start, "format": "json"}
        )
        return [
            ReferenceCollection(
                key=item.get("key") or item.get("data", {}).get("key", ""),
                name=item.get("data", {}).get("name", ""),
                parent_key=item.get("data", {}).get("parentCollection") or None,
            )
            for item in response.json()
        ]

    async def list_attachments(self, item_key: str) -> list[ReferenceAttachment]:
        response = await self._get(
            f"users/0/items/{self._key(item_key)}/children", params={"limit": 100, "format": "json"}
        )
        if response.status_code == 404:
            return []
        result: list[ReferenceAttachment] = []
        for item in response.json():
            data = item.get("data", {})
            if data.get("itemType") != "attachment":
                continue
            result.append(
                ReferenceAttachment(
                    key=item.get("key") or data.get("key", ""),
                    version=int(item.get("version") or data.get("version") or 0),
                    title=data.get("title") or data.get("filename") or "Attachment",
                    content_type=data.get("contentType") or None,
                    filename=data.get("filename") or None,
                    link_mode=data.get("linkMode") or None,
                )
            )
        return result

    async def open_attachment(self, attachment_key: str) -> AttachmentStream:
        client = self._client()
        try:
            request = client.build_request("GET", f"users/0/items/{self._key(attachment_key)}/file")
            response = await client.send(request, stream=True)
        except httpx.RequestError as exc:
            await client.aclose()
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Zotero attachment is not reachable", 503
            ) from exc
        if response.status_code == 302:
            location = response.headers.get("Location", "")
            await response.aclose()
            await client.aclose()
            parsed = urlparse(location)
            if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
                raise DomainError(
                    "PROVIDER_UNAVAILABLE", "Zotero returned an unsupported attachment URL", 503
                )
            try:
                path = Path(url2pathname(parsed.path)).resolve(strict=True)
                if not path.is_file():
                    raise FileNotFoundError(path)
                file = path.open("rb")
            except (OSError, ValueError) as exc:
                raise DomainError("NOT_FOUND", "Zotero PDF file is unavailable", 404) from exc
            if file.read(5) != b"%PDF-":
                file.close()
                raise DomainError("INVALID_PDF", "Zotero attachment is not a valid PDF", 422)
            file.seek(0)

            async def file_chunks() -> AsyncIterator[bytes]:
                while chunk := await asyncio.to_thread(file.read, 128 * 1024):
                    yield chunk

            async def close_file() -> None:
                await asyncio.to_thread(file.close)

            return AttachmentStream(
                chunks=file_chunks(),
                close=close_file,
                content_type="application/pdf",
                content_length=path.stat().st_size,
            )
        if response.status_code not in (200, 206):
            await response.aclose()
            await client.aclose()
            if response.status_code == 404:
                raise DomainError("NOT_FOUND", "Zotero attachment file is unavailable", 404)
            raise DomainError(
                "PROVIDER_UNAVAILABLE", f"Zotero attachment returned {response.status_code}", 503
            )
        length = response.headers.get("Content-Length")

        async def close() -> None:
            await response.aclose()
            await client.aclose()

        return AttachmentStream(
            chunks=response.aiter_bytes(),
            close=close,
            content_type=response.headers.get("Content-Type", "application/octet-stream"),
            content_length=int(length) if length and length.isdigit() else None,
        )

    async def get_indexed_fulltext(self, attachment_key: str) -> IndexedText | None:
        response = await self._get(f"users/0/items/{self._key(attachment_key)}/fulltext")
        if response.status_code == 404:
            return None
        data = response.json()
        return IndexedText(
            content=data.get("content", ""),
            indexed_pages=data.get("indexedPages"),
            total_pages=data.get("totalPages"),
        )
