"""Frozen public repository inventories and bounded payload streams."""

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class AssetRemoteRef:
    provider_key: str
    repo_kind: str
    repo_id: str
    provider_id: str
    commit_sha: str


@dataclass(frozen=True)
class AssetInventoryFile:
    path: str
    kind: Literal["REGULAR", "LFS", "SYMLINK", "SUBMODULE"]
    size_bytes: int | None
    digest_algorithm: Literal["GIT_BLOB_SHA1", "SHA256"] | None
    digest: str | None
    supported: bool
    issue: str | None = None


@dataclass(frozen=True)
class AssetInventory:
    ref: AssetRemoteRef
    files: tuple[AssetInventoryFile, ...]
    complete: bool
    gaps: tuple[str, ...] = ()


def asset_inventory_sha256(inventory: AssetInventory) -> str:
    value = {
        "ref": asdict(inventory.ref),
        "files": [asdict(file) for file in sorted(inventory.files, key=lambda file: file.path)],
        "complete": inventory.complete,
        "gaps": list(inventory.gaps),
    }
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class RemoteAssetProvider(Protocol):
    async def manifest(self, reference: AssetRemoteRef) -> AssetInventory: ...

    def stream_file(
        self, reference: AssetRemoteRef, file: AssetInventoryFile, *, max_bytes: int
    ) -> AsyncIterator[bytes]: ...
