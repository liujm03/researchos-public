"""Readonly catalog port for already frozen local project archive versions."""

from dataclasses import dataclass
from typing import Protocol

from app.domain.github_archive import GitHubPrivateRepository
from app.domain.project_archive import LocalProjectVersionReceipt, ProjectVersionManifest


@dataclass(frozen=True)
class ArchiveCatalogVersion:
    receipt: LocalProjectVersionReceipt
    manifest: ProjectVersionManifest


@dataclass(frozen=True)
class ArchiveCatalogSnapshot:
    local_project_id: str
    repository: GitHubPrivateRepository
    versions: tuple[ArchiveCatalogVersion, ...]


class ArchiveCatalogProvider(Protocol):
    def snapshot(self) -> ArchiveCatalogSnapshot: ...
