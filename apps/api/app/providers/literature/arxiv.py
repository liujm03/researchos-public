"""Bounded metadata-only query against the official arXiv Atom API."""

import hashlib
import math
import xml.etree.ElementTree as ET
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.domain.literature import PaperCandidate
from app.domain.literature_identity import ArxivIdentity, parse_arxiv_identity, validate_doi
from app.errors import DomainError
from app.providers.literature.arxiv_rate_limit import ArxivRateGate

_API_URL = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_MAX_BYTES = 1024 * 1024


class RateGate(Protocol):
    def slot(self) -> AbstractAsyncContextManager[None]: ...


def _text(entry: ET.Element, name: str) -> str | None:
    element = entry.find(name)
    if element is None:
        return None
    return " ".join("".join(element.itertext()).split()) or None


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


def _parse(payload: bytes, requested: ArxivIdentity) -> PaperCandidate | None:
    try:
        xml = payload.decode("utf-8-sig")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise ValueError("DTD and entities are forbidden")
        feed = ET.fromstring(xml)
    except (UnicodeDecodeError, ValueError, ET.ParseError) as exc:
        raise DomainError("PROVIDER_UNAVAILABLE", "arXiv returned invalid XML", 503) from exc
    if feed.tag != _ATOM + "feed" or sum(1 for _ in feed.iter()) > 10_000:
        raise DomainError("PROVIDER_UNAVAILABLE", "arXiv returned invalid Atom metadata", 503)
    entries = feed.findall(_ATOM + "entry")
    if not entries:
        return None
    if len(entries) != 1:
        raise DomainError("PROVIDER_UNAVAILABLE", "arXiv returned unexpected entries", 503)
    entry = entries[0]
    returned_id = _text(entry, _ATOM + "id")
    try:
        returned = parse_arxiv_identity(returned_id or "")
    except DomainError as exc:
        raise DomainError(
            "PROVIDER_UNAVAILABLE", "arXiv returned invalid article identity", 503
        ) from exc
    if (
        returned.canonical_id != requested.canonical_id
        or returned.version is None
        or (requested.version is not None and requested.version != returned.version)
    ):
        raise DomainError("PROVIDER_UNAVAILABLE", "arXiv response identity/version mismatch", 503)
    raw_doi = _text(entry, _ARXIV + "doi")
    try:
        doi = validate_doi(raw_doi) if raw_doi else None
    except DomainError as exc:
        raise DomainError("PROVIDER_UNAVAILABLE", "arXiv returned invalid DOI", 503) from exc
    published = _timestamp(_text(entry, _ATOM + "published"))
    authors = tuple(
        name
        for author in entry.findall(_ATOM + "author")
        if (name := _text(author, _ATOM + "name"))
    )
    pdf_url = None
    for link in entry.findall(_ATOM + "link"):
        if link.get("type") == "application/pdf" or link.get("title") == "pdf":
            try:
                linked = parse_arxiv_identity(link.get("href") or "")
            except DomainError as exc:
                raise DomainError(
                    "PROVIDER_UNAVAILABLE", "arXiv returned invalid PDF identity", 503
                ) from exc
            if linked != returned:
                raise DomainError(
                    "PROVIDER_UNAVAILABLE", "arXiv PDF identity/version mismatch", 503
                )
            pdf_url = f"https://arxiv.org/pdf/{returned.query_id}"
    # Exclude query/feed timestamps: the provenance is the exact returned article entry.
    source_hash = hashlib.sha256(
        ET.canonicalize(ET.tostring(entry, encoding="unicode")).encode("utf-8")
    ).hexdigest()
    return PaperCandidate(
        provider_key="arxiv",
        provider_id=returned.query_id,
        doi=doi,
        title=_text(entry, _ATOM + "title"),
        authors=authors,
        year=published.year if published else None,
        venue=_text(entry, _ARXIV + "journal_ref"),
        paper_type="preprint",
        abstract=_text(entry, _ATOM + "summary"),
        url=f"https://arxiv.org/abs/{returned.query_id}",
        source_hash=source_hash,
        source_updated_at=_timestamp(_text(entry, _ATOM + "updated")),
        arxiv_id=returned.canonical_id,
        source_version=returned.version,
        pdf_url=pdf_url,
    )


class ArxivAdapter:
    provider_key = "arxiv"
    capabilities = frozenset({"get_paper_by_id"})

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        rate_gate: RateGate | None = None,
    ) -> None:
        self._transport = transport
        self._rate_gate = rate_gate or ArxivRateGate()

    async def get_paper_by_id(self, paper_id: str) -> PaperCandidate | None:
        requested = parse_arxiv_identity(paper_id)
        try:
            async with self._rate_gate.slot():
                async with httpx.AsyncClient(
                    headers={
                        "User-Agent": "ResearchOS/0.1 (personal metadata lookup)",
                        "Accept": "application/atom+xml",
                    },
                    timeout=httpx.Timeout(10.0, read=30.0),
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "GET", _API_URL, params={"id_list": requested.query_id, "max_results": 1}
                    ) as response:
                        if response.status_code == 404:
                            return None
                        if response.status_code in {429, 503}:
                            delay = 3
                            try:
                                seconds = float(response.headers.get("Retry-After", "3"))
                                if math.isfinite(seconds) and seconds >= 0:
                                    delay = max(3, min(math.ceil(seconds), 3600))
                            except ValueError:
                                pass
                            raise DomainError(
                                "PROVIDER_RATE_LIMITED"
                                if response.status_code == 429
                                else "PROVIDER_UNAVAILABLE",
                                "arXiv is rate limited or temporarily unavailable",
                                response.status_code,
                                details={"retry_after_seconds": delay},
                            )
                        if response.status_code != 200:
                            raise DomainError(
                                "PROVIDER_UNAVAILABLE",
                                f"arXiv returned HTTP {response.status_code}",
                                503,
                            )
                        payload = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(payload) + len(chunk) > _MAX_BYTES:
                                raise DomainError(
                                    "PROVIDER_UNAVAILABLE",
                                    "arXiv metadata response exceeds the size limit",
                                    503,
                                )
                            payload.extend(chunk)
        except httpx.TimeoutException as exc:
            raise DomainError("PROVIDER_TIMEOUT", "arXiv lookup timed out", 503) from exc
        except httpx.RequestError as exc:
            raise DomainError("PROVIDER_UNAVAILABLE", "arXiv lookup failed", 503) from exc
        return _parse(bytes(payload), requested)
