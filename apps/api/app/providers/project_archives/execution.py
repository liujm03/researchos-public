"""Host archive operations fenced by a bound scope and an OS advisory lock."""

import asyncio
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, cast

from app.domain.archive_catalog import ArchiveCatalogVersion
from app.domain.archive_execution import ArchiveExecutionScope
from app.domain.github_archive import (
    GitHubPrivateRepository,
    GitHubPublicationReceipt,
    ProjectArchiveProvider,
)
from app.domain.project_archive import LocalProjectVersionReceipt, ProjectVersionManifest
from app.errors import DomainError
from app.providers.code_changes.local import LocalCodeFileProvider
from app.providers.project_archives.catalog import (
    LocalArchiveCatalogProvider,
    _decode,
    _receipt,
    _sha,
    _version,
)
from app.providers.project_archives.git_transport import GitHubGitTransport
from app.providers.project_archives.local_git import ARCHIVE_REF, manifest_bytes
from app.services.project_archive_publish import GitVersionTransport, publish_version


def _conflict() -> DomainError:
    return DomainError("ARCHIVE_EXECUTION_SCOPE_CHANGED", "Project archive binding no longer matches the frozen execution scope", 409)


class _UnixFileLock(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int) -> None: ...


def _unix_lock(fd: int, *, release: bool = False) -> None:
    # Windows typing stubs omit Unix attributes; this branch runs only on Unix.
    import fcntl
    library = cast(_UnixFileLock, fcntl)
    library.flock(fd, library.LOCK_UN if release else library.LOCK_EX | library.LOCK_NB)


class HostArchiveExecutionProvider:
    def __init__(self, root: Path, scope: ArchiveExecutionScope, remote: ProjectArchiveProvider, transport: GitVersionTransport | None = None) -> None:
        self.catalog = LocalArchiveCatalogProvider(root)
        self.local = self.catalog.local
        self.scope = scope
        self.remote = remote
        self.transport = transport if transport is not None else GitHubGitTransport()
        self._locked = False
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", scope.workspace_key) or not re.fullmatch(r"[a-f0-9]{64}", scope.workspace_fingerprint):
            raise _conflict()

    def _repository_matches(self, repository: GitHubPrivateRepository) -> bool:
        expected = self.scope.repository
        return repository.private is True and repository.push_allowed is True and (
            repository.repository_id, repository.owner_id,
            repository.owner_login.casefold(), repository.name.casefold(),
        ) == (expected.repository_id, expected.owner_id, expected.owner_login.casefold(), expected.name.casefold()) and expected.private is True and expected.push_allowed is True

    def _binding(self) -> None:
        """Check current binding independently of the inventory's history bound."""
        try:
            project, repository = self.catalog._bound()
        except DomainError as error:
            raise DomainError(error.code, error.message, error.status_code) from None
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
            raise DomainError("ARCHIVE_CATALOG_INVALID", "Local archive binding failed verification", 409) from None
        if project != self.scope.local_project_id or not self._repository_matches(repository):
            raise _conflict()

    def _require_lock(self) -> None:
        if not self._locked:
            raise DomainError("ARCHIVE_EXECUTION_LOCK_REQUIRED", "Archive mutations and receipt repair require the exclusive workspace lock", 409)

    def _manifest_identity(self, manifest: ProjectVersionManifest) -> None:
        if (manifest.owner_id, manifest.project_id) != (f"github:{self.scope.repository.owner_id}", self.scope.local_project_id) or hashlib.sha256(manifest_bytes(manifest)).hexdigest() != manifest.sha256:
            raise _conflict()
        _version(manifest.version)

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        if self._locked:
            raise DomainError("ARCHIVE_EXECUTION_BUSY", "Another archive operation holds this workspace lock", 409)
        self._binding()
        guard = LocalCodeFileProvider(self.local.root)
        try:
            with guard.exclusive():
                guard.assert_no_pending_changes()
                self._locked = True
                try:
                    self._binding()
                    yield
                finally:
                    self._locked = False
        except DomainError as error:
            if error.code == "CODE_FILE_BUSY":
                raise DomainError("ARCHIVE_EXECUTION_BUSY", "Another operation holds this project lock", 409) from None
            raise

    def preflight(self, tag: str) -> ProjectVersionManifest:
        self._binding()
        return self.local.preflight(owner_id=f"github:{self.scope.repository.owner_id}", project_id=self.scope.local_project_id, version=_version(tag))

    def is_unchanged(self, manifest: ProjectVersionManifest) -> bool:
        self._binding()
        self._manifest_identity(manifest)
        if manifest.parent_commit is None:
            return False
        _sha(manifest.parent_commit)
        current = self.catalog._git("rev-parse", "--verify", ARCHIVE_REF).decode("ascii").strip()
        if current != manifest.parent_commit:
            raise DomainError("ARCHIVE_MANIFEST_CHANGED", "Archive parent changed after preflight", 409)
        if self.local.preflight(owner_id=manifest.owner_id, project_id=manifest.project_id, version=manifest.version) != manifest:
            raise DomainError("ARCHIVE_MANIFEST_CHANGED", "Project contents changed after preflight", 409)
        names = self.catalog._git("ls-tree", "-r", "--name-only", "-z", manifest.parent_commit, "--", ".researchos/versions").split(b"\0")
        if len(names) != 2 or names[-1] != b"":
            raise DomainError("ARCHIVE_CATALOG_INVALID", "Previous archive commit has no unique managed version manifest", 409)
        path = names[0].decode("utf-8")
        prefix = ".researchos/versions/"
        if not path.startswith(prefix) or not path.endswith(".json"):
            raise DomainError("ARCHIVE_CATALOG_INVALID", "Previous archive version manifest failed verification", 409)
        tag = _version(path[len(prefix):-len(".json")])
        previous = self._version_from_commit(tag, manifest.parent_commit)
        if previous.manifest.files != manifest.files or previous.manifest.excluded != manifest.excluded:
            return False
        # A local-only version must not cause the durable worker to skip upload.
        # Worker invokes this sync port in a thread; do not leak a coroutine when
        # a caller incorrectly invokes it from an active event loop.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise DomainError("ARCHIVE_EXECUTION_CONTEXT_INVALID", "Remote archive comparison must run outside the active event loop", 409)
        return asyncio.run(self.inspect_remote(previous.receipt)) is not None

    def _save_receipt(self, receipt: LocalProjectVersionReceipt) -> None:
        self._require_lock()
        self._binding()
        state = self.local.root / ".git/researchos"
        directory = state / "versions"
        directory.mkdir(exist_ok=True)
        target = directory / (receipt.tag + ".json")
        body = (json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        if target.exists():
            if _decode(self.local._read_path(target)) != asdict(receipt):
                raise DomainError("ARCHIVE_RECEIPT_CONFLICT", "Existing local version receipt differs and will not be overwritten", 409)
            return
        fd, temporary_name = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=state)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            self.local._root()
            try:
                os.link(temporary, target)
            except FileExistsError:
                if _decode(self.local._read_path(target)) != asdict(receipt):
                    raise DomainError("ARCHIVE_RECEIPT_CONFLICT", "Existing local version receipt differs and will not be overwritten", 409) from None
            if os.name != "nt":
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def commit(self, manifest: ProjectVersionManifest) -> LocalProjectVersionReceipt:
        self._require_lock()
        self._binding()
        self._manifest_identity(manifest)
        repository = self.scope.repository
        receipt = self.local.commit_version(manifest, author_name=repository.owner_login, author_email=f"{repository.owner_id}+{repository.owner_login}@users.noreply.github.com")
        self.catalog.verify_receipt(receipt)
        self._save_receipt(receipt)
        return receipt

    def inspect_local(self, tag: str, expected_manifest_sha256: str | None) -> ArchiveCatalogVersion | None:
        self._binding()
        tag = _version(tag)
        if expected_manifest_sha256 is not None:
            _sha(expected_manifest_sha256, digest=True)
        path = self.local.root / ".git/researchos/versions" / (tag + ".json")
        if path.exists():
            record = _decode(self.local._read_path(path))
            receipt = _receipt(record, self.scope.local_project_id, f"github:{self.scope.repository.owner_id}", path.name)
            version = self.catalog.verify_receipt(receipt)
        else:
            # Atomic tag creation can precede its CLI state receipt across a crash.
            commit = self.local._git("rev-parse", "--verify", "refs/tags/" + tag, allow_failure=True, extra_env={"GIT_NO_REPLACE_OBJECTS": "1"}).decode("ascii").strip()
            if not commit:
                return None
            _sha(commit)
            version = self._version_from_commit(tag, commit)
            receipt = version.receipt
            if expected_manifest_sha256 is not None and receipt.manifest_sha256 != expected_manifest_sha256:
                raise DomainError("ARCHIVE_RECEIPT_CONFLICT", "Retained immutable version differs from the expected manifest", 409)
            self._save_receipt(receipt)
        if expected_manifest_sha256 is not None and version.receipt.manifest_sha256 != expected_manifest_sha256:
            raise DomainError("ARCHIVE_RECEIPT_CONFLICT", "Retained immutable version differs from the expected manifest", 409)
        return version

    def _version_from_commit(self, tag: str, commit: str) -> ArchiveCatalogVersion:
        """Prove only one retained immutable version, without scanning receipts."""
        _sha(commit)
        tag = _version(tag)
        manifest_path = f".researchos/versions/{tag}.json"
        blob = self.catalog._git("rev-parse", "--verify", commit + ":" + manifest_path).decode("ascii").strip()
        meta = self.catalog._blobs({_sha(blob)}, {})
        manifest = _decode(meta[blob])
        receipt = LocalProjectVersionReceipt(f"github:{self.scope.repository.owner_id}", self.scope.local_project_id, tag, commit, _sha(manifest.get("sha256"), digest=True), tag)
        return self.catalog.verify_receipt(receipt)

    async def _remote_repository(self) -> GitHubPrivateRepository:
        expected = self.scope.repository
        account = await self.remote.inspect_authenticated_account(expected.owner_login, expected.owner_id)
        if account.user_id != expected.owner_id or account.login.casefold() != expected.owner_login.casefold():
            raise _conflict()
        current = await self.remote.get_private_owned_repository(expected.owner_login, expected.name, expected_owner_id=expected.owner_id, expected_repository_id=expected.repository_id)
        if not self._repository_matches(current):
            raise _conflict()
        return current

    def _verify_local_receipt(self, receipt: LocalProjectVersionReceipt) -> None:
        self._binding()
        if (receipt.owner_id, receipt.project_id) != (f"github:{self.scope.repository.owner_id}", self.scope.local_project_id):
            raise _conflict()
        self.catalog.verify_receipt(receipt)

    async def publish(self, receipt: LocalProjectVersionReceipt) -> GitHubPublicationReceipt:
        self._require_lock()
        self._verify_local_receipt(receipt)
        current = await self._remote_repository()
        return await publish_version(self.local.root, current, receipt, provider=self.remote, transport=self.transport)

    async def inspect_remote(self, receipt: LocalProjectVersionReceipt) -> GitHubPublicationReceipt | None:
        self._verify_local_receipt(receipt)
        current = await self._remote_repository()
        tag = await self.remote.inspect_ref(current, "tags/" + receipt.tag)
        branch = await self.remote.inspect_ref(current, "heads/researchos-archive")
        if tag is None:
            return None
        if tag.object_type != "commit" or tag.sha != receipt.commit_sha:
            raise DomainError("PROJECT_ARCHIVE_VERSION_CONFLICT", "Remote immutable version does not match the local receipt", 409)
        if branch is None:
            return None
        if branch.object_type != "commit":
            raise DomainError("PROJECT_ARCHIVE_REMOTE_UNCONFIRMED", "Archive branch does not provide commit evidence", 503)
        _sha(branch.sha)
        return GitHubPublicationReceipt(current.repository_id, current.full_name, True, branch.sha, tag.sha, receipt.tag, receipt.manifest_sha256)
