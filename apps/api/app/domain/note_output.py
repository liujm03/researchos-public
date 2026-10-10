"""Canonical note file output port; models never receive filesystem write access."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NoteFileState:
    path: str
    sha256: str | None
    size_bytes: int


@dataclass(frozen=True)
class SavedNoteFile:
    path: str
    sha256: str
    size_bytes: int
    previous_sha256: str | None = None
    revision_path: str | None = None


class NoteOutputProvider(Protocol):
    def inspect(self, relative_path: str) -> NoteFileState: ...

    def save(self, relative_path: str, content: bytes, *, expected_current_sha256: str | None) -> SavedNoteFile: ...
