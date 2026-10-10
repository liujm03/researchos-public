"""Bounded deletion of an owner-approved generated text file, never arbitrary paths."""

from dataclasses import dataclass
from typing import Literal, Protocol

MAX_GENERATED_FILE_BYTES = 1_048_576
GeneratedFileKind = Literal["markdown", "storage"]


@dataclass(frozen=True)
class GeneratedFileSnapshot:
    relative_path: str
    exists: bool
    sha256: str | None
    size_bytes: int


@dataclass(frozen=True)
class GeneratedFileDeletionReceipt:
    relative_path: str
    status: Literal["DELETED", "ALREADY_ABSENT"]
    sha256: str
    size_bytes: int


class GeneratedFileDeletionProvider(Protocol):
    """Root and paths come from a frozen server plan, never browser input.

    The synchronous adapter is invoked with ``asyncio.to_thread`` by services.
    An absent retry acknowledges only the current absence, not an earlier success.
    No original PDF, Zotero object, backup or recovery copy belongs to this port.
    """

    def inspect(self, relative_path: str) -> GeneratedFileSnapshot: ...

    def delete_verified(
        self, relative_path: str, expected_sha256: str
    ) -> GeneratedFileDeletionReceipt: ...
