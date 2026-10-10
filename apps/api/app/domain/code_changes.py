"""Nonexecuting, bounded code-file changes at an already trusted project root."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

MAX_CODE_FILES = 20
MAX_CODE_FILE_BYTES = 256 * 1024
MAX_CODE_TOTAL_BYTES = 1024 * 1024


@dataclass(frozen=True)
class CodeFileSnapshot:
    path: str
    exists: bool
    sha256: str | None
    content: str
    size_bytes: int


@dataclass(frozen=True)
class CodeFileChange:
    path: str
    before_sha256: str | None
    after_text: str


@dataclass(frozen=True)
class CodeFileReceipt:
    path: str
    before_sha256: str | None
    after_sha256: str
    size_bytes: int
    reused: bool


class CodeFileProvider(Protocol):
    def exclusive(self) -> AbstractContextManager[None]: ...

    def begin(self, plan_id: str, proposal_sha256: str, attempt_id: str) -> None: ...

    def complete(self, plan_id: str, proposal_sha256: str, attempt_id: str) -> None: ...

    def assert_no_pending_changes(self) -> None: ...

    def read(self, paths: tuple[str, ...]) -> tuple[CodeFileSnapshot, ...]: ...

    def apply(self, file: CodeFileChange) -> CodeFileReceipt: ...
