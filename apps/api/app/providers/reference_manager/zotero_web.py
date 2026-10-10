"""Read-only Zotero Web API v3 adapter.

The API key is sent only to api.zotero.org. Attachment redirects use a new
client without credentials and are limited to HTTPS Zotero/S3 file hosts.
"""

import math
import re
import time
from typing import Any
from urllib.parse import urlparse

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
from app.errors import DomainError
from app.providers.reference_manager.catalog import catalog_page

_API_URL = "https://api.zotero.org/"
_BACKOFF_UNTIL: dict[tuple[str, str], float] = {}


class ZoteroWebAdapter:
    provider_key = "zotero_web"

    def __init__(
        self,
        api_key: str,
        library_type: str,
        library_id: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key or "\r" in api_key or "\n" in api_key:
            raise DomainError("CONFIGURATION_ERROR", "Zotero Web API key is not configured", 503)
        if library_type not in {"user", "group"} or not re.fullmatch(r"[1-9]\d*", library_id):
            raise DomainError("CONFIGURATION_ERROR", "Invalid Zotero library identity", 503)
        self._api_key = api_key
        self.library_type = library_type
        self.library_id = library_id
        self.library_prefix = f"{library_type}s/{library_id}"
        self.server_id = "zotero.org"
        self._transport = transport

    def _client(self, *, authenticated: bool = True) -> httpx.AsyncClient:
        headers = {"User-Agent": "ResearchOS/0.1"}
        if authenticated:
            headers.update({"Zotero-API-Version": "3", "Zotero-API-Key": self._api_key})
        return httpx.AsyncClient(
            base_url=_API_URL,
            headers=headers,
            timeout=httpx.Timeout(10.0, read=60.0),
            follow_redirects=False,
            transport=self._transport,
        )

    @staticmethod
    def _key(value: str) -> str:
        if not re.fullmatch(r"[A-Z0-9]{8}", value):
            raise DomainError("VALIDATION_ERROR", "Invalid Zotero item key", 422)
        return value

    @staticmethod
    def _page(limit: int, start: int) -> dict[str, int | str]:
        if not 1 <= limit <= 100 or start < 0:
            raise DomainError("VALIDATION_ERROR", "Invalid Zotero pagination", 422)
        return {"limit": limit, "start": start, "format": "json"}

    @staticmethod
    def _seconds(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return min(math.ceil(seconds), 3600)

    def _check_backoff(self) -> None:
        remaining = _BACKOFF_UNTIL.get((self.library_type, self.library_id), 0) - time.monotonic()
        if remaining > 0:
            raise DomainError(
                "PROVIDER_RATE_LIMITED",
                "Zotero Web API requested a backoff",
                429,
                details={"retry_after_seconds": math.ceil(remaining)},
            )

    def _check_response(self, response: httpx.Response, *, allow_redirect: bool = False) -> None:
        backoff = self._seconds(response.headers.get("Backoff"))
        if backoff:
            identity = (self.library_type, self.library_id)
            _BACKOFF_UNTIL[identity] = max(
                _BACKOFF_UNTIL.get(identity, 0), time.monotonic() + backoff
            )
        status = response.status_code
        if status in {200, 206, 404} or (allow_redirect and status in {301, 302, 303, 307, 308}):
            return
        if status in {401, 403}:
            raise DomainError("PROVIDER_AUTH_ERROR", "Zotero Web API access denied", 403)
        if status == 429:
            delay = self._seconds(response.headers.get("Retry-After")) or 5
            identity = (self.library_type, self.library_id)
            _BACKOFF_UNTIL[identity] = max(
                _BACKOFF_UNTIL.get(identity, 0), time.monotonic() + delay
            )
            raise DomainError(
                "PROVIDER_RATE_LIMITED",
                "Zotero Web API rate limit reached",
                429,
                details={"retry_after_seconds": delay},
            )
        if status == 503:
            unavailable_delay = self._seconds(response.headers.get("Retry-After"))
            raise DomainError(
                "PROVIDER_UNAVAILABLE",
                "Zotero Web API is temporarily unavailable",
                503,
                details={"retry_after_seconds": unavailable_delay} if unavailable_delay else None,
            )
        raise DomainError("PROVIDER_UNAVAILABLE", f"Zotero Web API returned {status}", 503)

    async def _get(self, path: str, params: dict[str, int | str] | None = None) -> httpx.Response:
        self._check_backoff()
        try:
            async with self._client() as client:
                response = await client.get(path, params=params)
        except httpx.RequestError as exc:
            raise DomainError("PROVIDER_UNAVAILABLE", "Zotero Web API is unreachable", 503) from exc
        self._check_response(response)
        return response

    async def status(self) -> dict[str, str | bool | None]:
        response = await self._get(f"{self.library_prefix}/collections", params=self._page(1, 0))
        if response.status_code == 404:
            raise DomainError("PROVIDER_UNAVAILABLE", "Zotero library not found", 503)
        return {
            "connected": True,
            "provider_key": self.provider_key,
            "mode": "web",
            "server_id": self.server_id,
            "api_version": response.headers.get("Zotero-API-Version", "3"),
            "library_type": self.library_type,
            "library_id": self.library_id,
            "can_read": True,
            "can_download_attachments": True,
            "can_write": False,
            "incremental_sync": True,
        }

    async def list_updated_items(self, since: int | None, limit: int, start: int) -> ReferencePage:
        """Read one changed-item page at a library version snapshot.

        Zotero Web API v3 documents ``since`` and the response's
        ``Last-Modified-Version`` for read-only incremental clients. Child
        attachments are not papers, but their changed parents must be checked.
        """
        params = self._page(limit, start)
        params["since"] = 0 if since is None else since
        response = await self._get(f"{self.library_prefix}/items", params)
        if response.status_code == 404:
            raise DomainError("PROVIDER_UNAVAILABLE", "Zotero items endpoint is unavailable", 503)
        raw_version = response.headers.get("Last-Modified-Version")
        try:
            library_version = int(raw_version) if raw_version is not None else None
        except ValueError:
            library_version = None
        raw_items = response.json()
        if not isinstance(raw_items, list):
            raise DomainError("PROVIDER_UNAVAILABLE", "Zotero returned invalid items", 503)
        child_types = {"attachment", "note", "annotation"}
        return ReferencePage(
            items=tuple(
                self._item(item)
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
        )

    async def search_items(
        self, query: str, limit: int, start: int, collection_key: str | None = None
    ) -> list[ReferenceItem]:
        return list((await self.search_items_page(query, limit, start, collection_key)).items)

    async def search_items_page(
        self, query: str, limit: int, start: int, collection_key: str | None = None
    ) -> ReferenceCatalogPage:
        params = self._page(limit, start)
        if query:
            params["q"] = query
        path = (
            f"{self.library_prefix}/collections/{self._key(collection_key)}/items/top"
            if collection_key
            else f"{self.library_prefix}/items/top"
        )
        response = await self._get(path, params)
        if response.status_code == 404:
            return ReferenceCatalogPage((), 0, 0, None)
        raw = response.json()
        records = tuple(
            self._item(item)
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
        response = await self._get(f"{self.library_prefix}/items/{self._key(item_key)}")
        return None if response.status_code == 404 else self._item(response.json())

    async def list_collections(self, limit: int, start: int) -> list[ReferenceCollection]:
        response = await self._get(
            f"{self.library_prefix}/collections", params=self._page(limit, start)
        )
        if response.status_code == 404:
            return []
        return [
            ReferenceCollection(
                key=item.get("key") or item.get("data", {}).get("key", ""),
                name=item.get("data", {}).get("name", ""),
                parent_key=item.get("data", {}).get("parentCollection") or None,
            )
            for item in response.json()
        ]

    async def list_attachments(self, item_key: str) -> list[ReferenceAttachment]:
        path = f"{self.library_prefix}/items/{self._key(item_key)}/children"
        result: list[ReferenceAttachment] = []
        start = 0
        while True:
            response = await self._get(path, params=self._page(100, start))
            if response.status_code == 404:
                return result
            page = response.json()
            for item in page:
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
            start += len(page)
            total = response.headers.get("Total-Results")
            if len(page) < 100 or (total and total.isdigit() and start >= int(total)):
                return result

    @staticmethod
    def _allowed_file_url(value: str) -> bool:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        try:
            return (
                parsed.scheme == "https"
                and parsed.port in {None, 443}
                and not parsed.username
                and not parsed.password
                and (
                    hostname == "api.zotero.org"
                    or hostname == "storage.zotero.org"
                    or hostname.endswith(".zotero.org")
                    or hostname.endswith(".amazonaws.com")
                )
            )
        except ValueError:
            return False

    async def open_attachment(self, attachment_key: str) -> AttachmentStream:
        self._check_backoff()
        path = f"{self.library_prefix}/items/{self._key(attachment_key)}/file"
        client = self._client()
        try:
            response = await client.send(client.build_request("GET", path), stream=True)
            self._check_response(response, allow_redirect=True)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location", "")
                await response.aclose()
                await client.aclose()
                if not self._allowed_file_url(location):
                    raise DomainError(
                        "PROVIDER_UNAVAILABLE", "Zotero returned an unsafe attachment URL", 503
                    )
                client = self._client(authenticated=False)
                response = await client.send(client.build_request("GET", location), stream=True)
                self._check_response(response)
            if response.status_code == 404:
                raise DomainError("NOT_FOUND", "Zotero attachment file is unavailable", 404)
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
        except httpx.RequestError as exc:
            await client.aclose()
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Zotero attachment is unreachable", 503
            ) from exc
        except BaseException:
            await client.aclose()
            raise

    async def get_indexed_fulltext(self, attachment_key: str) -> IndexedText | None:
        response = await self._get(
            f"{self.library_prefix}/items/{self._key(attachment_key)}/fulltext"
        )
        if response.status_code == 404:
            return None
        data = response.json()
        return IndexedText(
            content=data.get("content", ""),
            indexed_pages=data.get("indexedPages"),
            total_pages=data.get("totalPages"),
        )
