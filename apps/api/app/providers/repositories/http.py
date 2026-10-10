"""Bounded GET transport restricted to one official HTTPS authority."""

import hashlib
import json
import math
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx

from app.errors import DomainError

METADATA_MAX_BYTES = 512 * 1024
README_MAX_BYTES = 256 * 1024


def source_hash(provider: str, kind: str, repo_id: str, commit: str | None, metadata: dict[str, object], readme_hash: str | None) -> str:
    payload = {"provider": provider, "kind": kind, "repo_id": repo_id, "commit_sha": commit, "metadata": metadata, "readme_sha256": readme_hash}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict.fromkeys(item for item in value if isinstance(item, str) and item.strip()))


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def decode_json(body: bytes) -> dict[str, object]:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value: str) -> object:
        raise ValueError("Non-finite JSON value")

    try:
        value: object = json.loads(body, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise DomainError("REPOSITORY_INVALID_RESPONSE", "Repository API returned invalid JSON", 502) from None
    if not isinstance(value, dict):
        raise DomainError("REPOSITORY_INVALID_RESPONSE", "Repository API returned invalid metadata", 502)
    return value


def ensure_public(metadata: dict[str, object]) -> None:
    visibility = metadata.get("visibility")
    if visibility is not None and (
        not isinstance(visibility, str) or visibility not in {"public", "private", "internal"}
    ):
        raise DomainError("REPOSITORY_INVALID_RESPONSE", "Repository API returned invalid visibility", 502)
    if metadata.get("private") is True or visibility in {"private", "internal"}:
        raise DomainError("REPOSITORY_PRIVATE_UNSUPPORTED", "Private repositories are not included in public metadata import", 403)
    if metadata.get("private") is not False:
        raise DomainError("REPOSITORY_PRIVACY_UNKNOWN", "Repository API did not confirm public visibility", 502)


def _retry_after(headers: httpx.Headers) -> int | None:
    value = headers.get("Retry-After")
    try:
        seconds = float(value) if value is not None else float(headers["X-RateLimit-Reset"]) - datetime.now(UTC).timestamp()
    except (KeyError, ValueError):
        return None
    return min(86400, max(0, math.ceil(seconds))) if math.isfinite(seconds) else None


class OfficialRepositoryHTTP:
    def __init__(self, host: str, *, token: str | None, transport: httpx.AsyncBaseTransport | None = None, headers: dict[str, str] | None = None) -> None:
        if host not in {"api.github.com", "huggingface.co"}:
            raise DomainError("CONFIGURATION_ERROR", "Unsupported repository API authority", 503)
        if token is not None and (not isinstance(token, str) or len(token) > 8192 or any(ord(char) < 33 or ord(char) > 126 for char in token)):
            raise DomainError("CONFIGURATION_ERROR", "Invalid repository API token configuration", 503)
        self.host, self.token, self.transport = host, token, transport
        self.headers = {"User-Agent": "ResearchOS/0.1", "Accept": "application/json", **(headers or {})}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _validate_url(self, value: str) -> None:
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme == "https" and parsed.hostname == self.host and parsed.port is None and parsed.username is None and parsed.password is None and not parsed.fragment and not parsed.path.startswith("//")
        except ValueError:
            valid = False
        if not valid:
            raise DomainError("REPOSITORY_REDIRECT_REJECTED", "Repository request may only use its official HTTPS API authority", 502)

    async def get(self, path: str, *, limit: int = METADATA_MAX_BYTES, accept: str | None = None) -> bytes:
        url = f"https://{self.host}{path}"
        self._validate_url(url)
        headers = self.headers | ({"Accept": accept} if accept else {})
        try:
            async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(10.0, read=30.0), follow_redirects=False, trust_env=False, transport=self.transport) as client:
                for _ in range(4):
                    async with client.stream("GET", url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise DomainError("REPOSITORY_REDIRECT_REJECTED", "Repository redirect has no official destination", 502)
                            url = urljoin(url, location)
                            self._validate_url(url)
                            continue
                        chunks = bytearray()
                        declared = response.headers.get("Content-Length")
                        if declared is not None:
                            try:
                                oversized = int(declared) > limit or int(declared) < 0
                            except ValueError:
                                oversized = False
                            if oversized:
                                raise DomainError("REPOSITORY_RESPONSE_TOO_LARGE", "Repository response exceeds the configured byte limit", 502)
                        async for chunk in response.aiter_bytes():
                            if len(chunks) + len(chunk) > limit:
                                raise DomainError("REPOSITORY_RESPONSE_TOO_LARGE", "Repository response exceeds the configured byte limit", 502)
                            chunks.extend(chunk)
                        status = response.status_code
                        if status == 429 or (status == 403 and (response.headers.get("X-RateLimit-Remaining") == "0" or response.headers.get("Retry-After") or b"rate limit" in bytes(chunks).lower())):
                            delay = _retry_after(response.headers)
                            raise DomainError("REPOSITORY_RATE_LIMITED", "Official repository API rate limit reached", 429, details={"retry_after_seconds": delay} if delay is not None else None)
                        if status == 404:
                            raise DomainError("REPOSITORY_NOT_FOUND", "Repository or revision was not found or is not publicly accessible", 404)
                        if status in {401, 403}:
                            raise DomainError("REPOSITORY_ACCESS_DENIED", "Official repository API denied metadata access", 403)
                        if status != 200:
                            raise DomainError("REPOSITORY_PROVIDER_UNAVAILABLE", f"Official repository API returned HTTP {status}", 503)
                        return bytes(chunks)
                raise DomainError("REPOSITORY_REDIRECT_REJECTED", "Repository API exceeded the redirect limit", 502)
        except httpx.TimeoutException:
            raise DomainError("REPOSITORY_TIMEOUT", "Official repository metadata request timed out", 503) from None
        except httpx.RequestError:
            raise DomainError("REPOSITORY_PROVIDER_UNAVAILABLE", "Official repository metadata request failed", 503) from None

    async def json(self, path: str) -> dict[str, object]:
        return decode_json(await self.get(path))

    async def readme(self, path: str, *, accept: str | None = None) -> tuple[str | None, str | None, tuple[str, ...]]:
        try:
            body = await self.get(path, limit=README_MAX_BYTES, accept=accept)
            decoded = body.decode("utf-8")
        except UnicodeError:
            return None, None, ("README_UNAVAILABLE: card is not valid UTF-8; no partial text was retained",)
        except DomainError as error:
            if error.code == "REPOSITORY_RATE_LIMITED":
                raise
            return None, None, (f"README_UNAVAILABLE: {error.code}; no partial text was retained",)
        return decoded, hashlib.sha256(body).hexdigest(), ()
