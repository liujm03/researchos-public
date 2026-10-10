"""Frozen source files and bound scope for independent project initialization."""

import hashlib
import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.domain.github_archive import GitHubPrivateRepository


def managed_root_fingerprint(root: Path) -> str:
    return hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProvisionFile:
    path: str
    content: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ProvisionScope:
    project_id: str
    managed_root_fingerprint: str
    folder_name: str
    repository_name: str
    github_owner: str
    github_owner_id: int
    plan_sha256: str


@dataclass(frozen=True)
class LocalProvisionReceipt:
    workspace_key: str
    root_path: str
    files: tuple[ProvisionFile, ...]
    manifest_sha256: str


class LocalProjectProvisionProvider(Protocol):
    def plan_files(self, project_id: str, name: str) -> tuple[ProvisionFile, ...]: ...

    def create(
        self, scope: ProvisionScope, files: tuple[ProvisionFile, ...]
    ) -> LocalProvisionReceipt: ...

    def inspect(
        self, scope: ProvisionScope, files: tuple[ProvisionFile, ...]
    ) -> LocalProvisionReceipt | None: ...

    def bind_repository(
        self, scope: ProvisionScope, repository: GitHubPrivateRepository
    ) -> LocalProvisionReceipt: ...

    def exclusive(self, scope: ProvisionScope) -> AbstractContextManager[None]: ...
