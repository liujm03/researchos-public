"""Private project publishing identity port; no credentials or Git execution in receipts."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class GitHubAccount:
    login: str
    user_id: int


@dataclass(frozen=True)
class GitHubPublicationReceipt:
    repository_id: int
    repository_full_name: str
    private: bool
    branch_commit: str
    tag_commit: str
    version: str
    manifest_sha256: str


@dataclass(frozen=True)
class GitHubPrivateRepository:
    repository_id: int
    owner_login: str
    owner_id: int
    name: str
    default_branch: str
    push_allowed: bool
    private: Literal[True] = True

    @property
    def full_name(self) -> str:
        return f"{self.owner_login}/{self.name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.full_name}.git"


@dataclass(frozen=True)
class GitHubRefState:
    ref: str
    sha: str
    object_type: Literal["commit", "tag"]


@dataclass(frozen=True)
class CreatePrivateRepositoryResult:
    repository: GitHubPrivateRepository
    # An observed repository after a lost response is not proof this call created it.
    # The caller must surface reconciliation and explicitly bind the observed ID.
    reconciled_after_unknown: bool


class ProjectArchiveProvider(Protocol):
    async def inspect_authenticated_account(
        self, expected_login: str, expected_user_id: int,
    ) -> GitHubAccount: ...

    async def get_private_owned_repository(
        self, owner: str, name: str, *, expected_owner_id: int,
        expected_repository_id: int | None = None,
    ) -> GitHubPrivateRepository: ...

    async def create_private_repository(
        self, owner: str, name: str, *, expected_owner_id: int,
        description: str | None = None,
    ) -> CreatePrivateRepositoryResult: ...

    async def inspect_ref(
        self, repository: GitHubPrivateRepository, ref: str,
    ) -> GitHubRefState | None: ...
