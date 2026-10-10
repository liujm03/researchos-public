"""Read-only DOI lookup and paginated search of Crossref's official REST API."""

import hashlib
import html
import json
import math
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.domain.literature import LiteratureSearchPage, LiteratureSearchQuery, PaperCandidate
from app.domain.literature_identity import validate_doi as normalize_doi
from app.domain.literature_identity import validate_doi_name
from app.errors import DomainError

_API_URL = "https://api.crossref.org/"
_TAG = re.compile(r"<[^>]*>")
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_CURSOR_LENGTH = 16384


def _valid_cursor(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= _MAX_CURSOR_LENGTH
        and all(33 <= ord(char) <= 126 for char in value)
    )


def _search_params(query: LiteratureSearchQuery) -> dict[str, str]:
    if (
        not isinstance(query.query, str)
        or not 1 <= len(query.query) <= 1000
        or not query.query.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in query.query)
        or type(query.limit) is not int
        or not 1 <= query.limit <= 50
        or any(
            year is not None and (type(year) is not int or not 1000 <= year <= 2999)
            for year in (query.from_year, query.until_year)
        )
        or (
            query.from_year is not None
            and query.until_year is not None
            and query.from_year > query.until_year
        )
        or (query.cursor is not None and not _valid_cursor(query.cursor))
    ):
        raise DomainError("VALIDATION_ERROR", "Invalid literature search query", 422)
    params = {
        "query.bibliographic": query.query.strip(),
        "rows": str(query.limit),
        "cursor": query.cursor or "*",
    }
    filters: list[str] = []
    if query.from_year is not None:
        filters.append(f"from-pub-date:{query.from_year}-01-01")
    if query.until_year is not None:
        filters.append(f"until-pub-date:{query.until_year}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    return params


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\\" in value
        ):
            return None
    except ValueError:
        return None
    return value


def _candidate(
    message: dict[str, Any], doi: str, *, publication_only: bool = False
) -> PaperCandidate:
    payload = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return PaperCandidate(
        provider_key="crossref",
        provider_id=doi,
        doi=doi,
        title=_text(message.get("title")),
        authors=_authors(message),
        year=_year({key: value for key, value in message.items() if key != "created"})
        if publication_only
        else _year(message),
        venue=_text(message.get("container-title")),
        paper_type=_text(message.get("type")),
        abstract=_text(message.get("abstract")),
        url=_safe_url(message.get("URL")),
        source_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        source_updated_at=_updated_at(message),
    )


def _text(value: object) -> str | None:
    # Malformed nested arrays are not valid Crossref text; avoid unbounded recursion.
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str):
        return None
    cleaned = " ".join(html.unescape(_TAG.sub(" ", value)).split())
    return cleaned or None


def _year(message: dict[str, Any]) -> int | None:
    for key in ("published", "issued", "published-print", "published-online", "created"):
        date = message.get(key)
        if not isinstance(date, dict):
            continue
        parts = date.get("date-parts")
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
            continue
        if parts[0] and type(parts[0][0]) is int and 1000 <= parts[0][0] <= 2999:
            return parts[0][0]
    return None


def _updated_at(message: dict[str, Any]) -> datetime | None:
    deposited = message.get("deposited")
    if not isinstance(deposited, dict):
        return None
    value = deposited.get("date-time")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _authors(message: dict[str, Any]) -> tuple[str, ...]:
    people = message.get("author")
    if not isinstance(people, list):
        return ()
    names: list[str] = []
    for person in people:
        if not isinstance(person, dict):
            continue
        name = _text(person.get("name"))
        if name is None:
            name = " ".join(
                part for part in (_text(person.get("given")), _text(person.get("family"))) if part
            )
        if name:
            names.append(name)
    return tuple(names)


def _retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(math.ceil(seconds), 3600)


class CrossrefAdapter:
    """One owner-triggered request per page; no automatic traversal or imports."""

    provider_key = "crossref"
    capabilities = frozenset({"get_paper_by_doi", "search_papers"})

    def __init__(
        self,
        contact_email: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if contact_email is not None and (
            len(contact_email) > 254
            or "@" not in contact_email
            or any(ord(char) < 33 or ord(char) > 126 for char in contact_email)
        ):
            raise DomainError("CONFIGURATION_ERROR", "Invalid Crossref contact email", 503)
        self._contact_email = contact_email
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        user_agent = "ResearchOS/0.1"
        if self._contact_email:
            user_agent += f" (mailto:{self._contact_email})"
        return httpx.AsyncClient(
            base_url=_API_URL,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(10.0, read=30.0),
            follow_redirects=False,
            transport=self._transport,
        )

    async def search_papers(self, query: LiteratureSearchQuery) -> LiteratureSearchPage:
        params = _search_params(query)
        source_url = str(httpx.URL(_API_URL + "works", params=params))
        try:
            async with self._client() as client:
                async with client.stream("GET", "works", params=params) as response:
                    if response.status_code == 429:
                        delay = _retry_after(response.headers.get("Retry-After"))
                        raise DomainError(
                            "PROVIDER_RATE_LIMITED",
                            "Crossref rate limit reached",
                            429,
                            details={"retry_after_seconds": delay} if delay is not None else None,
                        )
                    if response.status_code != 200:
                        raise DomainError(
                            "PROVIDER_UNAVAILABLE",
                            f"Crossref returned HTTP {response.status_code}",
                            503,
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise DomainError(
                                "PROVIDER_UNAVAILABLE", "Crossref response exceeds size limit", 503
                            )
                        body.extend(chunk)
        except httpx.TimeoutException as exc:
            raise DomainError("PROVIDER_TIMEOUT", "Crossref search timed out", 503) from exc
        except (httpx.RequestError, httpx.DecodingError) as exc:
            raise DomainError("PROVIDER_UNAVAILABLE", "Crossref search failed", 503) from exc
        try:
            envelope = json.loads(body)
        except (ValueError, RecursionError) as exc:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Crossref returned invalid JSON", 503
            ) from exc
        if not isinstance(envelope, dict) or not isinstance(envelope.get("message"), dict):
            raise DomainError("PROVIDER_UNAVAILABLE", "Crossref returned invalid search data", 503)
        message = envelope["message"]
        items = message.get("items")
        if not isinstance(items, list) or len(items) > query.limit:
            raise DomainError("PROVIDER_UNAVAILABLE", "Crossref returned invalid search items", 503)
        warnings: list[str] = []
        candidates: list[PaperCandidate] = []
        seen: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("DOI"), str):
                warnings.append("MALFORMED_ITEM_SKIPPED")
                continue
            try:
                doi = validate_doi_name(item["DOI"])
            except DomainError:
                warnings.append("MALFORMED_ITEM_SKIPPED")
                continue
            candidate = _candidate(item, doi, publication_only=True)
            if doi in seen:
                warnings.append(
                    "DUPLICATE_DOI_CONFLICT"
                    if seen[doi] != candidate.source_hash
                    else "DUPLICATE_DOI_SKIPPED"
                )
                continue
            seen[doi] = candidate.source_hash
            candidates.append(candidate)
        total = message.get("total-results")
        if type(total) is not int or total < 0:
            total = None
            warnings.append("TOTAL_RESULTS_UNAVAILABLE")
        next_cursor: str | None = None
        # Crossref may reuse a token on consecutive full pages. EOF is determined
        # from the upstream raw row count, not filtered candidates or token equality.
        if len(items) == query.limit:
            cursor = message.get("next-cursor")
            if _valid_cursor(cursor):
                next_cursor = cursor
            else:
                warnings.append(
                    "NEXT_CURSOR_UNAVAILABLE" if cursor is None else "NEXT_CURSOR_INVALID"
                )
        return LiteratureSearchPage(
            items=tuple(candidates),
            next_cursor=next_cursor,
            total_results=total,
            source_url=source_url,
            fetched_at=datetime.now(UTC),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def get_paper_by_doi(self, doi: str) -> PaperCandidate | None:
        normalized = normalize_doi(doi)
        try:
            async with self._client() as client:
                response = await client.get(f"works/{quote(normalized, safe='')}")
        except httpx.TimeoutException as exc:
            raise DomainError("PROVIDER_TIMEOUT", "Crossref DOI lookup timed out", 503) from exc
        except httpx.RequestError as exc:
            raise DomainError("PROVIDER_UNAVAILABLE", "Crossref DOI lookup failed", 503) from exc

        if response.status_code == 404:
            return None
        if response.status_code == 429:
            delay = _retry_after(response.headers.get("Retry-After"))
            raise DomainError(
                "PROVIDER_RATE_LIMITED",
                "Crossref rate limit reached",
                429,
                details={"retry_after_seconds": delay} if delay is not None else None,
            )
        if response.status_code != 200:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", f"Crossref returned HTTP {response.status_code}", 503
            )
        try:
            envelope = response.json()
        except ValueError as exc:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Crossref returned invalid JSON", 503
            ) from exc
        if not isinstance(envelope, dict) or not isinstance(envelope.get("message"), dict):
            raise DomainError("PROVIDER_UNAVAILABLE", "Crossref returned invalid metadata", 503)
        message: dict[str, Any] = envelope["message"]
        source_doi = message.get("DOI")
        if not isinstance(source_doi, str):
            raise DomainError("PROVIDER_UNAVAILABLE", "Crossref response has no DOI", 503)
        try:
            returned_doi = validate_doi_name(source_doi)
        except DomainError as exc:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Crossref response has invalid DOI", 503
            ) from exc
        if returned_doi != normalized:
            raise DomainError("PROVIDER_UNAVAILABLE", "Crossref response DOI mismatch", 503)

        return _candidate(message, returned_doi)
