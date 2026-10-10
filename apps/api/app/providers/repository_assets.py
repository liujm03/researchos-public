"""Official public repository trees and pinned, digest-verified byte streams."""

import hashlib
import json
import re
from collections import deque
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import cast
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpx

from app.domain.repositories import RepositoryKind
from app.domain.repository_assets import AssetInventory, AssetInventoryFile, AssetRemoteRef
from app.domain.repository_identity import normalize_repository_ref
from app.errors import DomainError
from app.providers.repositories.http import ensure_public

MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_FILES = 10000
MAX_DEPTH = 32
HF_DOWNLOAD_HOSTS = frozenset(
    {
        "huggingface.co",
        "cdn-lfs.huggingface.co",
        "cdn-lfs-us-1.hf.co",
        "cdn-lfs-eu-1.hf.co",
        "cas-bridge.xethub.hf.co",
    }
)
SHA1 = re.compile(r"[a-f0-9]{40}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")


def _invalid() -> DomainError:
    return DomainError(
        "ASSET_METADATA_INVALID",
        "Official asset inventory or identity is invalid or incomplete",
        502,
    )


def safe_asset_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2000
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise _invalid()
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {".", ".."} for part in path.parts)
        or len(path.parts) > MAX_DEPTH
    ):
        raise _invalid()
    return value


def _digest(value: object, *, sha256: bool = False) -> str:
    if not isinstance(value, str) or not (SHA256 if sha256 else SHA1).fullmatch(value):
        raise _invalid()
    return value


def _size(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _ref(reference: AssetRemoteRef, provider: str) -> AssetRemoteRef:
    normalized = normalize_repository_ref(
        reference.repo_id,
        provider_key=reference.provider_key,
        repo_kind=cast(RepositoryKind, reference.repo_kind),
        revision=reference.commit_sha,
    )
    if (
        reference.provider_key != provider
        or normalized.repo_id != reference.repo_id
        or not SHA1.fullmatch(reference.commit_sha)
        or not reference.provider_id
        or len(reference.provider_id) > 320
    ):
        raise _invalid()
    return reference


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _decode(raw: bytes) -> object:
    def invalid_constant(value: str) -> object:
        raise ValueError("nonfinite")

    try:
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _invalid() from None


class _OfficialAssetHTTP:
    def __init__(
        self, host: str, token: str | None, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        if token is not None and (
            not token or len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token)
        ):
            raise DomainError(
                "ASSET_CONFIGURATION_INVALID",
                "Asset credentials are not valid server configuration",
                503,
            )
        self.host, self.token, self.transport = host, token, transport

    def _url(self, value: str, *, download: bool = False) -> str:
        try:
            parsed = urlsplit(value)
            allowed = (
                HF_DOWNLOAD_HOSTS if download and self.host == "huggingface.co" else {self.host}
            )
            valid = (
                parsed.scheme == "https"
                and parsed.hostname in allowed
                and parsed.port is None
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
                and not parsed.path.startswith("//")
            )
        except ValueError:
            valid = False
        if not valid:
            raise DomainError(
                "ASSET_REDIRECT_REJECTED",
                "Asset redirect is outside the official HTTPS allowlist",
                502,
            )
        return value

    def _headers(self, url: str, accept: str) -> dict[str, str]:
        headers = {"Accept": accept, "User-Agent": "ResearchOS/0.1", "Accept-Encoding": "identity"}
        if self.host == "api.github.com":
            headers["X-GitHub-Api-Version"] = "2026-03-10"
        if self.token and urlsplit(url).hostname == self.host:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    @staticmethod
    def _status(response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        if response.status_code == 429 or response.headers.get("X-RateLimit-Remaining") == "0":
            raise DomainError(
                "ASSET_RATE_LIMITED", "Official asset provider rate limit reached", 429
            )
        if response.status_code in {401, 403, 404}:
            raise DomainError(
                "ASSET_ACCESS_DENIED", "Asset or exact revision is not publicly accessible", 403
            )
        raise DomainError(
            "ASSET_PROVIDER_UNAVAILABLE",
            "Official asset provider did not return a usable response",
            503,
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(10, read=30),
        )

    async def metadata(self, path: str) -> tuple[object, httpx.Headers]:
        url = self._url("https://" + self.host + path)
        try:
            async with self.client() as client:
                async with client.stream(
                    "GET", url, headers=self._headers(url, "application/json")
                ) as response:
                    self._status(response)
                    length = response.headers.get("Content-Length")
                    if length is not None and length.isdigit() and int(length) > MAX_METADATA_BYTES:
                        raise DomainError(
                            "ASSET_INVENTORY_LIMIT",
                            "Official inventory exceeded the bounded metadata limit",
                            502,
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_METADATA_BYTES:
                            raise DomainError(
                                "ASSET_INVENTORY_LIMIT",
                                "Official inventory exceeded the bounded metadata limit",
                                502,
                            )
                        raw.extend(chunk)
                    return _decode(bytes(raw)), response.headers
        except httpx.RequestError:
            raise DomainError(
                "ASSET_PROVIDER_UNAVAILABLE", "Official inventory request could not complete", 503
            ) from None

    async def bytes(
        self, path: str, file: AssetInventoryFile, max_bytes: int, *, accept: str
    ) -> AsyncIterator[bytes]:
        if (
            not file.supported
            or file.size_bytes is None
            or file.digest is None
            or file.digest_algorithm not in {"GIT_BLOB_SHA1", "SHA256"}
            or type(max_bytes) is not int
            or not 0 <= file.size_bytes <= max_bytes
        ):
            raise DomainError(
                "ASSET_FILE_UNSUPPORTED",
                "Frozen file cannot be downloaded inside the approved byte scope",
                409,
            )
        safe_asset_path(file.path)
        _digest(file.digest, sha256=file.digest_algorithm == "SHA256")
        url = self._url("https://" + self.host + path, download=True)
        digest = (
            hashlib.sha1(b"blob " + str(file.size_bytes).encode() + b"\0")
            if file.digest_algorithm == "GIT_BLOB_SHA1"
            else hashlib.sha256()
        )
        size, first = 0, bytearray()
        try:
            async with self.client() as client:
                for _ in range(6):
                    async with client.stream(
                        "GET", url, headers=self._headers(url, accept)
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise DomainError(
                                    "ASSET_REDIRECT_REJECTED",
                                    "Asset redirect has no destination",
                                    502,
                                )
                            url = self._url(urljoin(url, location), download=True)
                            continue
                        self._status(response)
                        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                            size += len(chunk)
                            if size > max_bytes or size > file.size_bytes:
                                raise DomainError(
                                    "ASSET_SIZE_MISMATCH",
                                    "Remote file exceeds its frozen size or byte scope",
                                    409,
                                )
                            if len(first) < 4096:
                                first.extend(chunk[: 4096 - len(first)])
                                if (
                                    re.match(
                                        rb"version https://git-lfs.github.com/spec/v1\r?\n", first
                                    )
                                    and re.search(rb"(?:^|\n)oid sha256:[a-f0-9]{64}\r?\n", first)
                                    and re.search(rb"(?:^|\n)size [0-9]+(?:\r?\n|$)", first)
                                ):
                                    raise DomainError(
                                        "ASSET_GIT_LFS_POINTER",
                                        "Git LFS pointer is not the actual payload; explicit payload support is required",
                                        409,
                                    )
                            digest.update(chunk)
                            yield chunk
                        if size != file.size_bytes or digest.hexdigest() != file.digest:
                            raise DomainError(
                                "ASSET_DIGEST_MISMATCH",
                                "Remote bytes do not match the frozen size and digest",
                                409,
                            )
                        return
                raise DomainError(
                    "ASSET_REDIRECT_REJECTED", "Asset exceeded the bounded redirect count", 502
                )
        except httpx.RequestError:
            raise DomainError(
                "ASSET_PROVIDER_UNAVAILABLE", "Pinned asset stream was interrupted", 503
            ) from None


class GitHubAssetProvider:
    provider_key = "github"

    def __init__(
        self,
        *,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_files: int = MAX_FILES,
    ) -> None:
        self.http = _OfficialAssetHTTP("api.github.com", token, transport)
        if type(max_files) is not int or not 1 <= max_files <= MAX_FILES:
            raise DomainError("ASSET_CONFIGURATION_INVALID", "Asset file limit is invalid", 503)
        self.max_files = max_files

    async def _identity(self, ref: AssetRemoteRef) -> str:
        ref = _ref(ref, self.provider_key)
        metadata, _ = await self.http.metadata("/repos/" + ref.repo_id)
        if not isinstance(metadata, dict):
            raise _invalid()
        ensure_public(metadata)
        if (
            type(metadata.get("id")) is not int
            or metadata["id"] <= 0
            or str(metadata["id"]) != ref.provider_id
            or not isinstance(metadata.get("full_name"), str)
            or metadata["full_name"].casefold() != ref.repo_id
        ):
            raise DomainError(
                "ASSET_SOURCE_CHANGED",
                "Repository stable identity differs from the approved source",
                409,
            )
        commit, _ = await self.http.metadata(f"/repos/{ref.repo_id}/git/commits/{ref.commit_sha}")
        if (
            not isinstance(commit, dict)
            or commit.get("sha") != ref.commit_sha
            or not isinstance(commit.get("tree"), dict)
        ):
            raise _invalid()
        return _digest(commit["tree"].get("sha"))

    async def manifest(self, reference: AssetRemoteRef) -> AssetInventory:
        root = await self._identity(reference)
        queue = deque([(root, "", 0)])
        files, seen, count = [], set(), 0
        while queue:
            tree_sha, prefix, depth = queue.popleft()
            if depth > MAX_DEPTH:
                raise DomainError(
                    "ASSET_INVENTORY_LIMIT", "Git tree exceeds the approved depth bound", 409
                )
            data, _ = await self.http.metadata(f"/repos/{reference.repo_id}/git/trees/{tree_sha}")
            if (
                not isinstance(data, dict)
                or data.get("sha") != tree_sha
                or data.get("truncated") is not False
                or not isinstance(data.get("tree"), list)
            ):
                raise DomainError(
                    "ASSET_INVENTORY_INCOMPLETE",
                    "Git tree is missing or truncated; no partial inventory is accepted",
                    502,
                )
            for item in data["tree"]:
                count += 1
                if count > MAX_FILES or not isinstance(item, dict):
                    raise DomainError(
                        "ASSET_INVENTORY_LIMIT",
                        "Repository inventory exceeds its bounded file count",
                        409,
                    )
                path = safe_asset_path(prefix + safe_asset_path(item.get("path")))
                if path in seen:
                    raise _invalid()
                seen.add(path)
                mode, kind, oid = item.get("mode"), item.get("type"), _digest(item.get("sha"))
                if mode == "040000" and kind == "tree":
                    queue.append((oid, path + "/", depth + 1))
                    continue
                size = _size(item.get("size"))
                if mode == "160000" and kind == "commit":
                    files.append(
                        AssetInventoryFile(
                            path, "SUBMODULE", size, None, None, False, "SUBMODULE_NOT_DOWNLOADED"
                        )
                    )
                elif mode == "120000" and kind == "blob":
                    files.append(
                        AssetInventoryFile(
                            path,
                            "SYMLINK",
                            size,
                            "GIT_BLOB_SHA1",
                            oid,
                            False,
                            "SYMLINK_NOT_FOLLOWED",
                        )
                    )
                elif mode in {"100644", "100755"} and kind == "blob":
                    files.append(
                        AssetInventoryFile(
                            path,
                            "REGULAR",
                            size,
                            "GIT_BLOB_SHA1",
                            oid,
                            size is not None,
                            None if size is not None else "SIZE_UNKNOWN",
                        )
                    )
                else:
                    raise _invalid()
                if len(files) > self.max_files:
                    raise DomainError(
                        "ASSET_INVENTORY_LIMIT", "Inventory exceeds the configured file limit", 409
                    )
        return AssetInventory(
            reference,
            tuple(sorted(files, key=lambda file: file.path)),
            True,
            tuple(sorted({file.issue for file in files if file.issue})),
        )

    async def stream_file(
        self, reference: AssetRemoteRef, file: AssetInventoryFile, *, max_bytes: int
    ) -> AsyncIterator[bytes]:
        await self._identity(reference)
        if file.kind != "REGULAR" or file.digest_algorithm != "GIT_BLOB_SHA1":
            raise DomainError(
                "ASSET_FILE_UNSUPPORTED",
                "GitHub byte streams require a regular immutable blob",
                409,
            )
        async for chunk in self.http.bytes(
            f"/repos/{reference.repo_id}/git/blobs/{file.digest}",
            file,
            max_bytes,
            accept="application/vnd.github.raw+json",
        ):
            yield chunk


class HuggingFaceAssetProvider:
    provider_key = "huggingface"
    plurals = {"model": "models", "dataset": "datasets", "space": "spaces"}

    def __init__(
        self,
        *,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_files: int = MAX_FILES,
    ) -> None:
        self.http = _OfficialAssetHTTP("huggingface.co", token, transport)
        if type(max_files) is not int or not 1 <= max_files <= MAX_FILES:
            raise DomainError("ASSET_CONFIGURATION_INVALID", "Asset file limit is invalid", 503)
        self.max_files = max_files

    async def _identity(self, reference: AssetRemoteRef) -> None:
        ref = _ref(reference, self.provider_key)
        if ref.repo_kind not in self.plurals:
            raise _invalid()
        data, _ = await self.http.metadata(
            f"/api/{self.plurals[ref.repo_kind]}/{ref.repo_id}/revision/{ref.commit_sha}"
        )
        if not isinstance(data, dict):
            raise _invalid()
        ensure_public(data)
        if data.get("gated") is not None and data.get("gated") is not False:
            raise DomainError(
                "ASSET_GATED_UNSUPPORTED",
                "Gated repository payloads require a separate access policy",
                403,
            )
        identifier = data.get("_id") or data.get("id") or data.get("modelId")
        canonical = data.get("id") or data.get("modelId")
        if (
            identifier != ref.provider_id
            or canonical != ref.repo_id
            or data.get("sha") != ref.commit_sha
        ):
            raise DomainError(
                "ASSET_SOURCE_CHANGED",
                "HF stable identity or exact revision differs from the approved source",
                409,
            )

    async def manifest(self, reference: AssetRemoteRef) -> AssetInventory:
        await self._identity(reference)
        base = f"/api/{self.plurals[reference.repo_kind]}/{reference.repo_id}/tree/{reference.commit_sha}"
        path = base + "?recursive=true&expand=false"
        seen_pages: set[str] = set()
        seen_paths: set[str] = set()
        files: list[AssetInventoryFile] = []
        for _ in range(1000):
            if path in seen_pages:
                raise DomainError(
                    "ASSET_INVENTORY_INCOMPLETE",
                    "HF pagination repeated; complete inventory cannot be proved",
                    502,
                )
            seen_pages.add(path)
            data, headers = await self.http.metadata(path)
            if not isinstance(data, list):
                raise _invalid()
            for row in data:
                if not isinstance(row, dict):
                    raise _invalid()
                name = safe_asset_path(row.get("path"))
                if name in seen_paths or len(seen_paths) >= MAX_FILES:
                    raise DomainError(
                        "ASSET_INVENTORY_LIMIT",
                        "HF inventory contains duplicates or exceeds its bounded count",
                        502,
                    )
                seen_paths.add(name)
                if row.get("type") == "directory":
                    continue
                if row.get("type") != "file":
                    raise _invalid()
                blob = _digest(row.get("oid"))
                size = _size(row.get("size"))
                lfs = row.get("lfs")
                if lfs is not None:
                    if not isinstance(lfs, dict) or _size(lfs.get("size")) != size:
                        raise _invalid()
                    files.append(
                        AssetInventoryFile(
                            name,
                            "LFS",
                            size,
                            "SHA256",
                            _digest(lfs.get("oid"), sha256=True),
                            size is not None,
                            None if size is not None else "SIZE_UNKNOWN",
                        )
                    )
                elif row.get("mode") in {"120000", "160000"}:
                    files.append(
                        AssetInventoryFile(
                            name,
                            "SYMLINK" if row["mode"] == "120000" else "SUBMODULE",
                            size,
                            "GIT_BLOB_SHA1",
                            blob,
                            False,
                            "UNSUPPORTED_GIT_MODE",
                        )
                    )
                else:
                    files.append(
                        AssetInventoryFile(
                            name,
                            "REGULAR",
                            size,
                            "GIT_BLOB_SHA1",
                            blob,
                            size is not None,
                            None if size is not None else "SIZE_UNKNOWN",
                        )
                    )
                if len(files) > self.max_files:
                    raise DomainError(
                        "ASSET_INVENTORY_LIMIT", "Inventory exceeds the configured file limit", 409
                    )
            matches = re.findall(r'<([^>]+)>\s*;\s*rel="next"', headers.get("Link", ""))
            if not matches:
                if "next" in headers.get("Link", ""):
                    raise _invalid()
                return AssetInventory(
                    reference,
                    tuple(sorted(files, key=lambda file: file.path)),
                    True,
                    tuple(sorted({file.issue for file in files if file.issue})),
                )
            if len(matches) != 1:
                raise _invalid()
            next_url = self.http._url(urljoin("https://huggingface.co" + path, matches[0]))
            parsed = urlsplit(next_url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if (
                parsed.path != base
                or len(parsed.query) > 8192
                or set(query) - {"cursor", "recursive", "expand", "limit"}
                or any(len(values) != 1 for values in query.values())
                or query.get("recursive", ["true"]) != ["true"]
                or query.get("expand", ["false"]) != ["false"]
                or "cursor" not in query
            ):
                raise DomainError(
                    "ASSET_INVENTORY_INCOMPLETE",
                    "HF next page changed the exact inventory scope",
                    502,
                )
            path = (
                base + "?recursive=true&expand=false&cursor=" + quote(query["cursor"][0], safe="")
            )
        raise DomainError(
            "ASSET_INVENTORY_LIMIT", "HF inventory exceeded its bounded page count", 502
        )

    async def stream_file(
        self, reference: AssetRemoteRef, file: AssetInventoryFile, *, max_bytes: int
    ) -> AsyncIterator[bytes]:
        await self._identity(reference)
        prefix = "" if reference.repo_kind == "model" else "/" + self.plurals[reference.repo_kind]
        path = f"{prefix}/{reference.repo_id}/resolve/{reference.commit_sha}/{quote(safe_asset_path(file.path), safe='/')}"
        async for chunk in self.http.bytes(
            path, file, max_bytes, accept="application/octet-stream"
        ):
            yield chunk
