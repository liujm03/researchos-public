"""Review and confirmation contracts for public repository metadata imports."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.repositories import RepositoryKind, RepositoryProviderKey

TargetKind = Literal["code_repository", "model", "dataset"]


class Record(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class RepositoryPreviewRequest(Record):
    provider_key: RepositoryProviderKey = Field(min_length=1, max_length=40)
    repo_kind: RepositoryKind
    repository: str = Field(min_length=1, max_length=2000)
    revision: str | None = Field(default=None, min_length=1, max_length=160)


class RepositoryConfirmRequest(Record):
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str | None = Field(default=None, min_length=1, max_length=240)
    task: str | None = Field(default=None, min_length=1, max_length=120)
    modalities: list[str] | None = Field(default=None, max_length=16)
    existing_entity_id: uuid.UUID | None = None


class RepositoryCandidateOut(Record):
    provider_key: RepositoryProviderKey = Field(min_length=1, max_length=40)
    repo_kind: RepositoryKind
    repo_id: str = Field(min_length=1, max_length=320)
    provider_id: str = Field(min_length=1, max_length=320)
    canonical_url: str = Field(min_length=1, max_length=2000)
    name: str = Field(min_length=1, max_length=320)
    description: str | None = Field(max_length=20_000)
    license_id: str | None = Field(max_length=500)
    default_branch: str | None = Field(max_length=160)
    commit_sha: str | None = Field(pattern=r"^[a-fA-F0-9]{7,64}$")
    stars: int | None = Field(ge=0)
    downloads: int | None = Field(ge=0)
    topics: list[str] = Field(max_length=1000)
    task_hints: list[str] = Field(max_length=100)
    readme_text: str | None = Field(max_length=262_144)
    readme_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fetched_at: AwareDatetime
    updated_at: AwareDatetime | None
    warnings: list[str] = Field(max_length=100)


class RepositoryCandidateSnapshot(RepositoryCandidateOut):
    # Immutable public-source audit envelope, not registry business fields.
    raw_metadata: dict[str, object]


class RepositoryBindingOut(Record):
    id: uuid.UUID
    provider_key: RepositoryProviderKey
    repo_kind: RepositoryKind
    repo_id: str
    provider_id: str
    entity_id: uuid.UUID
    entity_kind: TargetKind
    code_repository_id: uuid.UUID | None
    entity_name: str
    task: str | None
    modalities: list[str]
    created_at: datetime


class RepositorySourceOut(Record):
    id: uuid.UUID
    binding_id: uuid.UUID
    target_entity_id: uuid.UUID
    target_entity_kind: TargetKind
    provider_key: RepositoryProviderKey
    repo_kind: RepositoryKind
    repo_id: str
    provider_id: str
    source_hash: str
    snapshot_sha256: str
    revision: str | None
    canonical_url: str
    commit_sha: str | None
    model_version_id: uuid.UUID | None
    dataset_version_id: uuid.UUID | None
    code_repository_id: uuid.UUID | None
    created_at: datetime
    candidate: RepositoryCandidateOut


class RepositoryImportOut(Record):
    id: uuid.UUID
    provider_key: RepositoryProviderKey
    repo_kind: RepositoryKind
    repo_id: str
    provider_id: str
    revision: str | None
    canonical_url: str
    source_hash: str
    snapshot_sha256: str
    status: Literal["PENDING", "CONFIRMED"]
    created_at: datetime
    confirmed_at: datetime | None
    candidate: RepositoryCandidateOut
    existing_binding: RepositoryBindingOut | None
    target_entity_id: uuid.UUID | None
    target_entity_kind: TargetKind | None
    model_version_id: uuid.UUID | None
    dataset_version_id: uuid.UUID | None
    code_repository_id: uuid.UUID | None
    source_snapshot_id: uuid.UUID | None
    warnings: list[str]


class RepositoryImportPage(BaseModel):
    items: list[RepositoryImportOut]
    total: int
    limit: int
    offset: int


class RepositoryProviderOut(Record):
    provider_key: str
    label: str
    repo_kinds: list[RepositoryKind]
    enabled: bool
    public_only: bool
    metadata_only: bool
    token_configured: bool


class RepositoryProviderCatalogOut(BaseModel):
    items: list[RepositoryProviderOut]
