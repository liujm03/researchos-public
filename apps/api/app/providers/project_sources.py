"""Copy approved original bytes to a marked, ignored, nonexecuting project cache."""

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from app.domain.project_sources import (
    PROJECT_SOURCE_MANIFEST_NAME,
    ProjectSourceFile,
    ProjectSourceFileReceipt,
    ProjectSourceManifestReceipt,
    ProjectSourceScope,
)
from app.domain.provisioning import managed_root_fingerprint
from app.errors import DomainError
from app.providers.project_archives.catalog import LocalArchiveCatalogProvider
from app.providers.project_archives.execution import _unix_lock

MARKER = ".researchos-source-scope.json"
MANIFEST = PROJECT_SOURCE_MANIFEST_NAME
MAX_BYTES = 1024 * 1024 * 1024
MAX_FILES = 10000
MAX_METADATA_BYTES = 32 * 1024 * 1024


def _fail(code: str = "PROJECT_SOURCE_WORKSPACE_CONFLICT") -> DomainError:
    return DomainError(
        code, "Approved source workspace failed verification; existing files are preserved", 409
    )


def _path(path: Path, *, directory: bool = False) -> None:
    try:
        for part in (path, *path.parents):
            try:
                info = part.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise _fail()
        if directory and not path.is_dir():
            raise _fail()
    except OSError:
        raise _fail() from None


def _parts(value: str) -> tuple[str, ...]:
    reserved = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"} | {
        f"{prefix}{number}"
        for prefix in ("COM", "LPT")
        for number in (*range(1, 10), "¹", "²", "³")
    }
    parts = value.split("/")
    if not value or len(value) > 2000 or len(parts) > 64:
        raise _fail()
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or len(part) > 255
            or part.endswith((".", " "))
            or any(c in part for c in '<>:"\\|?*')
            or any(ord(c) < 32 or ord(c) == 127 for c in part)
            or part.split(".")[0].upper() in reserved
            or part.casefold() in {MARKER, MANIFEST}
        ):
            raise _fail()
    return tuple(parts)


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode


class LocalProjectSourceWorkspaceProvider:
    def __init__(
        self,
        root: Path,
        *,
        managed_root: Path,
        max_bytes: int = MAX_BYTES,
        max_files: int = MAX_FILES,
    ) -> None:
        # Check raw ancestry before normalization can erase a linked component.
        if ".." in root.parts or ".." in managed_root.parts:
            raise _fail()
        _path(root, directory=True)
        _path(managed_root, directory=True)
        self.root = Path(os.path.abspath(root))
        self.managed_root = Path(os.path.abspath(managed_root))
        if self.root == self.managed_root or not self.root.is_relative_to(self.managed_root):
            raise _fail()
        self.catalog = LocalArchiveCatalogProvider(self.root)
        if not 0 < max_bytes <= MAX_BYTES or not 0 < max_files <= MAX_FILES:
            raise _fail()
        self.max_bytes, self.max_files = max_bytes, max_files
        self._locked: str | None = None
        self._binding_bytes: bytes | None = None
        self._binding_identity: tuple[int, int, int, int] | None = None
        self._binding_repository: tuple[str, object] | None = None
        self._marker_state: tuple[int, int, int, int, int] | None = None
        self._marker_files: set[ProjectSourceFile] | None = None
        self._marker_scope: ProjectSourceScope | None = None

    def _scope(self, scope: ProjectSourceScope) -> Path:
        _path(self.root, directory=True)
        _path(self.managed_root, directory=True)
        if (
            scope.root_fingerprint != managed_root_fingerprint(self.root)
            or scope.source_root_fingerprint != managed_root_fingerprint(self.managed_root)
            or scope.relative_path != f".researchos/cache/sources/{scope.plan_id}"
            or (
                scope.managed_root_fingerprint is not None
                and scope.managed_root_fingerprint != managed_root_fingerprint(self.managed_root)
            )
            or (
                scope.managed_folder_name is not None
                and self.root != self.managed_root / scope.managed_folder_name
            )
            or any(
                not re.fullmatch(r"[a-f0-9]{64}", value)
                for value in (scope.plan_sha256, scope.asset_manifest_sha256)
            )
        ):
            raise _fail()
        try:
            binding = self.root / ".git/researchos/binding.json"
            identity = (
                self.root.stat().st_dev,
                self.root.stat().st_ino,
                (self.root / ".git").stat().st_dev,
                (self.root / ".git").stat().st_ino,
            )
            content = self._read(binding)
            if self._locked is not None and self._binding_repository is not None:
                if content != self._binding_bytes or identity != self._binding_identity:
                    raise _fail()
                project, cached = self._binding_repository
                # The cache stores only the actual validated immutable DTO.
                from app.domain.github_archive import GitHubPrivateRepository

                if not isinstance(cached, GitHubPrivateRepository):
                    raise _fail()
                repository = cached
            else:
                project, repository = self.catalog._bound()
                if self._read(binding) != content:
                    raise _fail()
                self._binding_bytes, self._binding_identity = content, identity
                self._binding_repository = project, repository
        except (DomainError, OSError, ValueError, TypeError):
            raise _fail() from None
        expected = scope.repository
        if (
            project != scope.local_project_id
            or not repository.private
            or not expected.private
            or (
                repository.repository_id,
                repository.owner_id,
                repository.owner_login.casefold(),
                repository.name.casefold(),
            )
            != (
                expected.repository_id,
                expected.owner_id,
                expected.owner_login.casefold(),
                expected.name.casefold(),
            )
        ):
            raise _fail()
        target = self.root.joinpath(*scope.relative_path.split("/"))
        _path(target)
        return target

    def _files(self, files: tuple[ProjectSourceFile, ...]) -> None:
        if (
            not files
            or len(files) > self.max_files
            or sum(file.size_bytes for file in files) > self.max_bytes
        ):
            raise _fail()
        names: dict[tuple[str, ...], tuple[str, ...]] = {}
        leaves: set[tuple[str, ...]] = set()
        for file in files:
            parts = _parts(file.path)
            if (
                type(file.size_bytes) is not int
                or not 0 <= file.size_bytes <= self.max_bytes
                or not re.fullmatch(r"[a-f0-9]{64}", file.sha256)
            ):
                raise _fail()
            folded = tuple(part.casefold() for part in parts)
            if folded in leaves:
                raise _fail()
            leaves.add(folded)
            for length in range(1, len(parts) + 1):
                key, original = folded[:length], parts[:length]
                if key in names and names[key] != original:
                    raise _fail() from None
                names[key] = original
        if any(any(path[:length] in leaves for length in range(1, len(path))) for path in leaves):
            raise _fail()

    def _marker(self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]) -> bytes:
        return _json(
            {
                "schema": "project-source-cache-v1",
                "owner_id": str(scope.owner_id),
                "project_id": str(scope.project_id),
                "plan_id": str(scope.plan_id),
                "archive_binding_id": str(scope.archive_binding_id),
                "asset_snapshot_id": str(scope.asset_snapshot_id),
                "asset_manifest_sha256": scope.asset_manifest_sha256,
                "plan_sha256": scope.plan_sha256,
                "root_fingerprint": scope.root_fingerprint,
                "source_root_fingerprint": scope.source_root_fingerprint,
                "relative_path": scope.relative_path,
                "local_project_id": scope.local_project_id,
                "repository": asdict(scope.repository),
                "files": [asdict(file) for file in sorted(files, key=lambda file: file.path)],
            }
        )

    def _read(self, path: Path) -> bytes:
        _path(path)
        if not path.is_file() or path.stat().st_size > MAX_METADATA_BYTES:
            raise _fail()
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            content = stream.read(MAX_METADATA_BYTES + 1)
            after = os.fstat(stream.fileno())
        _path(path)
        if (
            len(content) > MAX_METADATA_BYTES
            or _signature(before) != _signature(after)
            or _signature(after) != _signature(path.stat())
        ):
            raise _fail()
        return content

    def _ignore(self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]) -> None:
        cache = self.root / ".researchos/cache"
        _path(cache)
        ignore = cache / ".gitignore"
        _path(ignore)
        if ignore.exists() and not ignore.is_file():
            raise _fail()
        if self.catalog.local._git("ls-files", "-z", "--", ".researchos/cache"):
            raise _fail("PROJECT_SOURCE_CACHE_TRACKED")
        if not ignore.exists():
            # Readonly preview promises this precise mechanical ignore creation.
            # prepare must establish it before any source bytes are copied.
            return
        paths = [scope.relative_path + "/" + file.path for file in files]
        paths.extend((scope.relative_path + "/" + MARKER, scope.relative_path + "/" + MANIFEST))
        payload = b"\0".join(path.encode() for path in paths) + b"\0"
        ignored = self.catalog.local._git(
            "check-ignore", "--no-index", "-z", "--stdin", payload=payload, allow_failure=True
        ).split(b"\0")
        if set(ignored) - {b""} != {path.encode() for path in paths}:
            raise _fail("PROJECT_SOURCE_CACHE_NOT_IGNORED")

    def readiness(self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]) -> None:
        target = self._scope(scope)
        self._files(files)
        if len(self._marker(scope, files)) > MAX_METADATA_BYTES:
            raise _fail()
        self._ignore(scope, files)
        if target.exists():
            _path(target, directory=True)
            if self._read(target / MARKER) != self._marker(scope, files):
                raise _fail()
            permitted = {file.path for file in files} | {MARKER, MANIFEST}
            directories = {
                "/".join(file.path.split("/")[:length])
                for file in files
                for length in range(1, len(file.path.split("/")))
            }
            for directory, folders, entries in os.walk(target, followlinks=False):
                for name in (*folders, *entries):
                    actual = Path(directory) / name
                    _path(actual)
                    relative = actual.relative_to(target).as_posix()
                    if actual.is_file() and relative not in permitted:
                        raise _fail()
                    if actual.is_dir() and relative not in directories:
                        raise _fail()
        for file in files:
            destination = target.joinpath(*_parts(file.path))
            _path(destination)
            if destination.exists() and self._inspect_file(file, destination) is None:
                raise _fail()

    def _require_lock(self, scope: ProjectSourceScope) -> None:
        if self._locked != str(scope.plan_id):
            raise _fail("PROJECT_SOURCE_LOCK_REQUIRED")

    @contextmanager
    def exclusive(self, scope: ProjectSourceScope) -> Iterator[None]:
        self._scope(scope)
        if self._locked is not None:
            raise _fail("PROJECT_SOURCE_BUSY")
        lock = self.root / ".git/researchos/source-cache.lock"
        _path(lock)
        fd: int | None = None
        acquired = False
        try:
            fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            _path(lock)
            opened, current = os.fstat(fd), lock.stat()
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                current.st_dev,
                current.st_ino,
            ):
                raise _fail()
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                _unix_lock(fd)
            acquired = True
            self._scope(scope)
            self._locked = str(scope.plan_id)
            yield
        except OSError:
            raise _fail("PROJECT_SOURCE_BUSY") from None
        finally:
            self._locked = None
            self._marker_state = self._marker_files = self._marker_scope = None
            if fd is not None:
                if acquired:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        _unix_lock(fd, release=True)
                os.close(fd)

    def _atomic(self, path: Path, content: bytes) -> None:
        _path(path)
        if path.exists():
            if self._read(path) != content:
                raise _fail()
            return
        fd, temporary = tempfile.mkstemp(prefix=".researchos-write-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            _path(path)
            try:
                os.link(temporary, path)
            except FileExistsError:
                if self._read(path) != content:
                    raise _fail() from None
        finally:
            os.unlink(temporary)

    def prepare(self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]) -> None:
        self._require_lock(scope)
        self.readiness(scope, files)
        cache = self.root / ".researchos/cache"
        cache.mkdir(parents=True, exist_ok=True)
        _path(cache, directory=True)
        if not (cache / ".gitignore").exists():
            self._atomic(cache / ".gitignore", b"*\n")
        self._ignore(scope, files)
        target = self._scope(scope)
        if not target.exists():
            target.mkdir(parents=True, exist_ok=False)
            _path(target, directory=True)
            self._atomic(target / MARKER, self._marker(scope, files))
        self.readiness(scope, files)

    def _allowed(self, scope: ProjectSourceScope, file: ProjectSourceFile) -> Path:
        target = self._scope(scope)
        self._files((file,))
        marker_path = target / MARKER
        _path(marker_path)
        marker_state = _signature(marker_path.stat())
        if (
            self._locked is not None
            and self._marker_scope == scope
            and self._marker_state == marker_state
            and self._marker_files is not None
        ):
            if file not in self._marker_files:
                raise _fail()
            destination = target.joinpath(*_parts(file.path))
            _path(destination)
            return destination
        try:
            marker = json.loads(self._read(marker_path))
        except (ValueError, UnicodeError, RecursionError):
            raise _fail() from None
        if (
            not isinstance(marker, dict)
            or marker.get("plan_sha256") != scope.plan_sha256
            or asdict(file) not in marker.get("files", [])
        ):
            raise _fail()
        # Recompute full marker, not just its plan hash, to prevent identity edits.
        try:
            files = tuple(ProjectSourceFile(**entry) for entry in marker["files"])
            self._files(files)
            if self._read(target / MARKER) != self._marker(scope, files):
                raise _fail()
            self._marker_scope, self._marker_state, self._marker_files = (
                scope,
                marker_state,
                set(files),
            )
        except (TypeError, KeyError, ValueError):
            raise _fail() from None
        destination = target.joinpath(*_parts(file.path))
        _path(destination)
        return destination

    def _inspect_file(self, file: ProjectSourceFile, path: Path) -> ProjectSourceFileReceipt | None:
        _path(path)
        if not path.exists():
            return None
        if not path.is_file() or path.stat().st_size != file.size_bytes:
            raise _fail("PROJECT_SOURCE_FILE_CHANGED")
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            while chunk := stream.read(65536):
                size += len(chunk)
                if size > file.size_bytes:
                    raise _fail("PROJECT_SOURCE_FILE_CHANGED")
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        _path(path)
        if (
            _signature(before) != _signature(after)
            or _signature(after) != _signature(path.stat())
            or (size, digest.hexdigest()) != (file.size_bytes, file.sha256)
        ):
            raise _fail("PROJECT_SOURCE_FILE_CHANGED")
        return ProjectSourceFileReceipt(file.path, digest.hexdigest(), size, True)

    def inspect(
        self, scope: ProjectSourceScope, file: ProjectSourceFile
    ) -> ProjectSourceFileReceipt | None:
        self._files((file,))
        if not self._scope(scope).exists():
            return None
        return self._inspect_file(file, self._allowed(scope, file))

    async def copy(
        self, scope: ProjectSourceScope, file: ProjectSourceFile, content: AsyncIterator[bytes]
    ) -> ProjectSourceFileReceipt:
        self._require_lock(scope)
        destination = self._allowed(scope, file)
        if receipt := self._inspect_file(file, destination):
            return receipt
        destination.parent.mkdir(parents=True, exist_ok=True)
        _path(destination.parent, directory=True)
        fd, temporary = tempfile.mkstemp(prefix=".researchos-write-", dir=destination.parent)
        digest, size = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, "wb") as stream:
                async for chunk in content:
                    if not isinstance(chunk, bytes):
                        raise _fail()
                    size += len(chunk)
                    if size > file.size_bytes:
                        raise _fail("PROJECT_SOURCE_SOURCE_CHANGED")
                    digest.update(chunk)
                    stream.write(chunk)
                if (size, digest.hexdigest()) != (file.size_bytes, file.sha256):
                    raise _fail("PROJECT_SOURCE_SOURCE_CHANGED")
                stream.flush()
                os.fsync(stream.fileno())
            self._allowed(scope, file)
            _path(destination)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                receipt = self._inspect_file(file, destination)
                if receipt is None:
                    raise _fail() from None
                return receipt
            receipt = self._inspect_file(file, destination)
            if receipt is None:
                raise _fail()
            return ProjectSourceFileReceipt(receipt.path, receipt.sha256, receipt.size_bytes)
        finally:
            os.unlink(temporary)

    def _manifest_content(
        self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]
    ) -> tuple[bytes, tuple[ProjectSourceFileReceipt, ...]]:
        self.readiness(scope, files)
        receipts = tuple(
            self.inspect(scope, file) for file in sorted(files, key=lambda file: file.path)
        )
        if any(receipt is None for receipt in receipts):
            raise _fail("PROJECT_SOURCE_FILES_MISSING")
        verified = tuple(receipt for receipt in receipts if receipt is not None)
        content = _json(
            {
                "scope_sha256": hashlib.sha256(self._marker(scope, files)).hexdigest(),
                "files": [
                    {
                        "path": receipt.path,
                        "sha256": receipt.sha256,
                        "size_bytes": receipt.size_bytes,
                    }
                    for receipt in verified
                ],
            }
        )
        return content, verified

    def finalize(
        self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]
    ) -> ProjectSourceManifestReceipt:
        self._require_lock(scope)
        content, verified = self._manifest_content(scope, files)
        self._atomic(self._scope(scope) / MANIFEST, content)
        return ProjectSourceManifestReceipt(
            scope.relative_path + "/" + MANIFEST, hashlib.sha256(content).hexdigest(), verified
        )

    def inspect_manifest(
        self, scope: ProjectSourceScope, files: tuple[ProjectSourceFile, ...]
    ) -> ProjectSourceManifestReceipt | None:
        target = self._scope(scope)
        _path(target / MANIFEST)
        if not (target / MANIFEST).exists():
            return None
        content, verified = self._manifest_content(scope, files)
        if self._read(target / MANIFEST) != content:
            raise _fail("PROJECT_SOURCE_MANIFEST_CHANGED")
        return ProjectSourceManifestReceipt(
            scope.relative_path + "/" + MANIFEST, hashlib.sha256(content).hexdigest(), verified
        )
