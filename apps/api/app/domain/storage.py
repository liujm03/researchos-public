from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str
    mime_type: str


@dataclass(frozen=True)
class StorageStat:
    key: str
    size_bytes: int


class StorageReader(Protocol):
    """Opened object snapshot; callers close it even if streaming never begins."""

    size_bytes: int

    def iter_bytes(self, *, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]:
        """Read [start, end), with end exclusive; None reads through object end."""
        ...

    async def close(self) -> None:
        """Release resources; repeated calls remain safe."""
        ...


class StorageProvider(Protocol):
    provider_key: str

    async def save(
        self,
        content: AsyncIterator[bytes],
        *,
        mime_type: str,
        max_bytes: int,
        allow_empty: bool = False,
    ) -> StoredObject: ...

    async def stat(self, key: str) -> StorageStat: ...

    async def open(self, key: str) -> StorageReader: ...

    def load(self, key: str, *, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> None: ...

    async def list(self, prefix: str = "") -> list[str]: ...

    def get_url(self, key: str) -> str: ...
