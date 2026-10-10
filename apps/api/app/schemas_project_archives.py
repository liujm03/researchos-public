"""Read-only archive inventory and explicit local-receipt import contract."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ArchiveImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_key: str = Field(min_length=1, max_length=80)


class ArchiveBindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    workspace_key: str
    local_project_id: str
    github_owner: str
    github_owner_id: int
    github_repository: str
    github_repository_id: int
    created_at: datetime
    verified_at: datetime
    managed_folder_name: str | None = None
    managed_root_fingerprint: str | None = None


class ArchiveVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    binding_id: uuid.UUID
    tag: str
    commit_sha: str
    manifest_sha256: str
    parent_commit: str | None
    file_count: int
    total_bytes: int
    remote_tag_commit: str | None
    remote_verified_at: datetime | None
    created_at: datetime
    status: Literal["LOCAL_ONLY", "VERIFIED_REMOTE"]


class ArchiveFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    path: str
    sha256: str
    size_bytes: int


class ArchiveWorkspaceOut(BaseModel):
    key: str
    label: str


class ArchiveStatusOut(BaseModel):
    enabled: bool
    write_enabled: bool = False
    write_detail: str = "后台归档写入尚未启用"
    workspaces: list[ArchiveWorkspaceOut]
    detail: str


class ArchiveInventoryOut(BaseModel):
    binding: ArchiveBindingOut | None
    versions: list[ArchiveVersionOut]
