"""Private version publication requires exact destination and post-transfer receipts."""
from pathlib import Path
from typing import Protocol

from app.domain.github_archive import GitHubPrivateRepository, ProjectArchiveProvider
from app.domain.github_archive import GitHubPublicationReceipt as GitHubPublicationReceipt
from app.domain.project_archive import LocalProjectVersionReceipt
from app.errors import DomainError


class GitVersionTransport(Protocol):
    def push(self, root: Path, repository: GitHubPrivateRepository, receipt: LocalProjectVersionReceipt) -> None: ...


async def publish_version(root: Path, repository: GitHubPrivateRepository, version: LocalProjectVersionReceipt, *, provider: ProjectArchiveProvider, transport: GitVersionTransport) -> GitHubPublicationReceipt:
    if version.owner_id != "github:" + str(repository.owner_id):
        raise DomainError("PROJECT_ARCHIVE_OWNER_MISMATCH", "Local version belongs to another owner; no remote operation started", 409)
    await provider.inspect_authenticated_account(repository.owner_login, repository.owner_id)
    current = await provider.get_private_owned_repository(repository.owner_login, repository.name, expected_owner_id=repository.owner_id, expected_repository_id=repository.repository_id)
    branch = await provider.inspect_ref(current, "heads/researchos-archive")
    tag = await provider.inspect_ref(current, "tags/" + version.tag)
    if tag is not None and (tag.object_type != "commit" or tag.sha != version.commit_sha):
        raise DomainError("PROJECT_ARCHIVE_VERSION_CONFLICT", "Existing remote version differs; immutable tags cannot be overwritten", 409)
    if branch is None or tag is None or branch.sha != version.commit_sha:
        try:
            transport.push(root, current, version)
        except DomainError as failure:
            if failure.code not in {"PROJECT_ARCHIVE_PUSH_UNKNOWN", "PROJECT_ARCHIVE_PUSH_UNCONFIRMED"}:
                raise
            # A single read reconciliation is safe; never repeat a push blindly.
    verified = await provider.get_private_owned_repository(current.owner_login, current.name, expected_owner_id=current.owner_id, expected_repository_id=current.repository_id)
    branch = await provider.inspect_ref(verified, "heads/researchos-archive")
    tag = await provider.inspect_ref(verified, "tags/" + version.tag)
    if branch is None or tag is None or branch.sha != version.commit_sha or tag.sha != version.commit_sha or tag.object_type != "commit":
        raise DomainError("PROJECT_ARCHIVE_REMOTE_UNCONFIRMED", "Remote branch/tag do not prove this exact version; retain local result", 503)
    return GitHubPublicationReceipt(verified.repository_id, verified.full_name, True, branch.sha, tag.sha, version.tag, version.manifest_sha256)
