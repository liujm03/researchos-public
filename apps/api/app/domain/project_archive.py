"""Provider-neutral, exact-content independent project version receipts."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProjectArchiveFile:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ProjectArchiveExclusion:
    path: str
    reason: str


@dataclass(frozen=True)
class ProjectVersionManifest:
    owner_id: str
    project_id: str
    version: str
    parent_commit: str | None
    files: tuple[ProjectArchiveFile, ...]
    excluded: tuple[ProjectArchiveExclusion, ...]
    sha256: str


@dataclass(frozen=True)
class LocalProjectVersionReceipt:
    owner_id: str
    project_id: str
    version: str
    commit_sha: str
    manifest_sha256: str
    tag: str


@dataclass(frozen=True)
class RestoredProjectVersion:
    path: str
    receipt: LocalProjectVersionReceipt
    verified_file_count: int


class LocalProjectVersionProvider(Protocol):
    def preflight(
        self, *, owner_id: str, project_id: str, version: str
    ) -> ProjectVersionManifest: ...

    def commit_version(
        self,
        manifest: ProjectVersionManifest,
        *,
        author_name: str,
        author_email: str,
    ) -> LocalProjectVersionReceipt: ...

    def restore_version(self, tag: str, destination: str) -> RestoredProjectVersion: ...
