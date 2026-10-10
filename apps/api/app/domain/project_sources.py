"""Approved source-cache workspace ports; no executable or network authority."""

import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from app.domain.github_archive import GitHubPrivateRepository

PROJECT_SOURCE_MANIFEST_NAME = ".researchos-source-manifest.json"


@dataclass(frozen=True)
class ProjectSourceScope:
    owner_id: uuid.UUID
    project_id: uuid.UUID
    plan_id: uuid.UUID
    asset_snapshot_id: uuid.UUID
    asset_manifest_sha256: str
    plan_sha256: str
    archive_binding_id: uuid.UUID
    workspace_key: str
    root_fingerprint: str
    source_root_fingerprint: str
    relative_path: str
    local_project_id: str
    repository: GitHubPrivateRepository
    managed_folder_name: str | None = None
    managed_root_fingerprint: str | None = None


@dataclass(frozen=True)
class ProjectSourceFile:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ProjectSourceFileReceipt:
    path: str
    sha256: str
    size_bytes: int
    reused: bool = False


@dataclass(frozen=True)
class ProjectSourceManifestReceipt:
    relative_path: str
    manifest_sha256: str
    files: tuple[ProjectSourceFileReceipt, ...]


class ProjectSourceWorkspaceProvider(Protocol):
    def readiness(
        self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]
    ) -> None: ...

    def exclusive(self, scope: ProjectSourceScope) -> AbstractContextManager[None]: ...

    def prepare(self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]) -> None: ...

    def inspect(
        self, scope: ProjectSourceScope, file: ProjectSourceFile
    ) -> ProjectSourceFileReceipt | None: ...

    async def copy(
        self, scope: ProjectSourceScope, file: ProjectSourceFile, content: AsyncIterator[bytes]
    ) -> ProjectSourceFileReceipt: ...

    def finalize(
        self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]
    ) -> ProjectSourceManifestReceipt: ...

    def inspect_manifest(
        self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]
    ) -> ProjectSourceManifestReceipt | None: ...
