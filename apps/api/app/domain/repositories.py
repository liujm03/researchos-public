"""Provider-neutral public repository identity and frozen metadata receipts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

RepositoryProviderKey = str
RepositoryKind = Literal["code", "model", "dataset", "space"]


@dataclass(frozen=True)
class RepositoryRef:
    provider_key: RepositoryProviderKey
    repo_kind: RepositoryKind
    repo_id: str
    revision: str | None = None


@dataclass(frozen=True)
class RepositoryCandidate:
    provider_key: RepositoryProviderKey
    repo_kind: RepositoryKind
    repo_id: str
    provider_id: str
    canonical_url: str
    name: str
    description: str | None
    license_id: str | None
    default_branch: str | None
    commit_sha: str | None
    stars: int | None
    downloads: int | None
    topics: tuple[str, ...]
    task_hints: tuple[str, ...]
    readme_text: str | None
    readme_sha256: str | None
    source_hash: str
    fetched_at: datetime
    updated_at: datetime | None
    warnings: tuple[str, ...]
    # Bounded, sanitized upstream source metadata; never authentication headers.
    raw_metadata: dict[str, object]


@dataclass(frozen=True)
class RepositoryProviderDescriptor:
    provider_key: RepositoryProviderKey
    label: str
    repo_kinds: tuple[RepositoryKind, ...]
    enabled: bool
    public_only: bool
    metadata_only: bool
    token_configured: bool


class OpenSourceRepositoryProvider(Protocol):
    provider_key: str

    async def get_repository(self, reference: RepositoryRef) -> RepositoryCandidate: ...
