"""Data-only ports for receiving lab-server evidence candidates."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ParsedServerResultArtifact:
    path: str
    content: bytes | None
    mime_type: str
    actual_sha256: str | None
    actual_size_bytes: int | None
    verification: str


@dataclass(frozen=True)
class ParsedServerResultBundle:
    envelope: dict[str, object]
    canonical_receipt: bytes
    receipt_sha256: str
    input_sha256: str
    artifacts: tuple[ParsedServerResultArtifact, ...]
    gaps: tuple[str, ...]


class ServerResultBundleParser(Protocol):
    def parse(
        self, content: bytes, max_bytes: int = 32 * 1024 * 1024
    ) -> ParsedServerResultBundle: ...


@dataclass(frozen=True)
class ServerReceiptAuthenticationResult:
    origin_verification: str
    gaps: tuple[str, ...]


class ServerReceiptAuthentication(Protocol):
    provider_key: str

    @property
    def configured_server_id(self) -> str | None: ...

    @property
    def configured(self) -> bool: ...

    def verify(
        self, *, canonical_receipt: bytes, server_id: str | None, signature: str | None
    ) -> ServerReceiptAuthenticationResult: ...
