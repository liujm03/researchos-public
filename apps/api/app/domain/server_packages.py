"""Pure, provider-neutral server handoff rendering contracts."""

from dataclasses import dataclass
from typing import Protocol

SERVER_PACKAGE_FIXED_PATHS = frozenset(
    {
        "README.md",
        "research_brief.md",
        "CODE_VERSION.md",
        "code_manifest.json",
        "assets.json",
        "expected_artifacts.json",
        "resource_limits.md",
        "server_run_instructions.md",
        "AGENTS.md",
        "AI_HANDOFF.md",
        "SHA256SUMS",
        "manifest.json",
    }
)


@dataclass(frozen=True)
class ServerPackageRenderedFile:
    path: str
    content: str
    role: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ServerPackageRenderedBundle:
    files: tuple[ServerPackageRenderedFile, ...]
    content: bytes
    sha256: str
    size_bytes: int


class ServerTaskPackageRenderer(Protocol):
    def render(
        self,
        *,
        brief_markdown: str,
        source_manifest: dict[str, object],
        selection: dict[str, object],
        gaps: tuple[str, ...],
    ) -> ServerPackageRenderedBundle: ...

    def pack(
        self, *, files: tuple[ServerPackageRenderedFile, ...]
    ) -> ServerPackageRenderedBundle: ...
