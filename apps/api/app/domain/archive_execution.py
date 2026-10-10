"""Bound project archive execution ports; no browser-supplied filesystem paths."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from app.domain.archive_catalog import ArchiveCatalogVersion
from app.domain.github_archive import GitHubPrivateRepository, GitHubPublicationReceipt
from app.domain.project_archive import LocalProjectVersionReceipt, ProjectVersionManifest


@dataclass(frozen=True)
class ArchiveExecutionScope:
    workspace_key: str
    workspace_fingerprint: str
    local_project_id: str
    repository: GitHubPrivateRepository
    managed_folder_name: str | None = None
    managed_root_fingerprint: str | None = None


class ArchiveExecutionProvider(Protocol):
    def exclusive(self) -> AbstractContextManager[None]: ...

    def preflight(self, tag: str) -> ProjectVersionManifest: ...

    def is_unchanged(self, manifest: ProjectVersionManifest) -> bool: ...

    def commit(self, manifest: ProjectVersionManifest) -> LocalProjectVersionReceipt: ...

    def inspect_local(self, tag: str, expected_manifest_sha256: str | None) -> ArchiveCatalogVersion | None: ...

    async def publish(self, receipt: LocalProjectVersionReceipt) -> GitHubPublicationReceipt: ...

    async def inspect_remote(self, receipt: LocalProjectVersionReceipt) -> GitHubPublicationReceipt | None: ...
