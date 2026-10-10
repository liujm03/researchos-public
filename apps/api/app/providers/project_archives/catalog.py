"""Inspect immutable Git archive bytes without consulting worktree source files."""

import hashlib
import json
import re
from dataclasses import asdict, fields
from pathlib import Path, PurePosixPath
from typing import Never

from app.domain.archive_catalog import ArchiveCatalogSnapshot, ArchiveCatalogVersion
from app.domain.github_archive import GitHubPrivateRepository
from app.domain.project_archive import (
    LocalProjectVersionReceipt,
    ProjectArchiveExclusion,
    ProjectArchiveFile,
    ProjectVersionManifest,
)
from app.errors import DomainError
from app.providers.project_archives.local_git import (
    BINDING,
    DEPENDENCIES,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    PUBLIC_TEMPLATE_CODE,
    REQUIRED,
    SECRET,
    TEXT_SUFFIXES,
    VERSION,
    LocalGitProjectVersionProvider,
    _excluded,
    _safe_relative,
    manifest_bytes,
)

MAX_VERSIONS = 100
SHA = re.compile(r"[a-f0-9]{40}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")


def _invalid() -> Never:
    raise DomainError(
        "ARCHIVE_CATALOG_INVALID",
        "Local archive metadata or immutable content failed verification",
        409,
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _constant(value: str) -> Never:
    _invalid()


def _decode(content: bytes) -> dict[str, object]:
    if len(content) > MAX_FILE_BYTES:
        _invalid()
    try:
        value: object = json.loads(content, object_pairs_hook=_unique, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        _invalid()
    if not isinstance(value, dict):
        _invalid()
    return value


def _keys(value: dict[str, object], names: set[str]) -> None:
    if set(value) != names:
        _invalid()


def _text(value: object, *, limit: int = 320) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        _invalid()
    return value


def _integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid()
    return value


def _sha(value: object, *, digest: bool = False) -> str:
    text = _text(value, limit=64)
    if not (DIGEST if digest else SHA).fullmatch(text):
        _invalid()
    return text


def _version(value: object) -> str:
    text = _text(value, limit=160)
    if not VERSION.fullmatch(text):
        _invalid()
    return text


def _repository(value: object) -> GitHubPrivateRepository:
    if not isinstance(value, dict):
        _invalid()
    _keys(value, {field.name for field in fields(GitHubPrivateRepository)})
    owner = _text(value["owner_login"])
    name = _text(value["name"])
    branch = _text(value["default_branch"])
    if (
        not LOGIN.fullmatch(owner)
        or "--" in owner
        or not NAME.fullmatch(name)
        or name in {".", ".."}
        or value["private"] is not True
        or value["push_allowed"] is not True
    ):
        _invalid()
    return GitHubPrivateRepository(
        _integer(value["repository_id"], minimum=1, maximum=2**63 - 1),
        owner,
        _integer(value["owner_id"], minimum=1, maximum=2**63 - 1),
        name,
        branch,
        True,
    )


def _receipt(
    value: dict[str, object], project: str, owner: str, filename: str
) -> LocalProjectVersionReceipt:
    _keys(value, {field.name for field in fields(LocalProjectVersionReceipt)})
    version = _version(value["version"])
    if (
        value["owner_id"] != owner
        or value["project_id"] != project
        or value["tag"] != version
        or filename != version + ".json"
    ):
        _invalid()
    return LocalProjectVersionReceipt(
        owner,
        project,
        version,
        _sha(value["commit_sha"]),
        _sha(value["manifest_sha256"], digest=True),
        version,
    )


def _manifest(
    value: dict[str, object], receipt: LocalProjectVersionReceipt
) -> ProjectVersionManifest:
    _keys(value, {field.name for field in fields(ProjectVersionManifest)})
    if (value["owner_id"], value["project_id"], value["version"], value["sha256"]) != (
        receipt.owner_id,
        receipt.project_id,
        receipt.version,
        receipt.manifest_sha256,
    ):
        _invalid()
    parent = _sha(value["parent_commit"]) if value["parent_commit"] is not None else None
    rows, excluded_rows = value["files"], value["excluded"]
    if (
        not isinstance(rows, list)
        or not isinstance(excluded_rows, list)
        or len(rows) + len(excluded_rows) > MAX_FILES
    ):
        _invalid()
    archive_files: list[ProjectArchiveFile] = []
    exclusions: list[ProjectArchiveExclusion] = []
    paths: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            _invalid()
        _keys(row, {"path", "sha256", "size_bytes"})
        path = _text(row["path"], limit=2000)
        _safe_relative(path)
        posix = PurePosixPath(path)
        if (
            posix.as_posix() != path
            or path in paths
            or _excluded(path)
            or path.startswith(".researchos/")
        ):
            _invalid()
        if path not in PUBLIC_TEMPLATE_CODE and posix.suffix.lower() not in TEXT_SUFFIXES and posix.name not in {
            ".gitignore",
            ".dockerignore",
            ".env.example",
            "Dockerfile",
            "Makefile",
            "LICENSE",
            "LICENSE.md",
        }:
            _invalid()
        paths.add(path)
        archive_files.append(
            ProjectArchiveFile(
                path,
                _sha(row["sha256"], digest=True),
                _integer(row["size_bytes"], minimum=0, maximum=MAX_FILE_BYTES),
            )
        )
    if (
        not REQUIRED.issubset(paths)
        or not paths.intersection(DEPENDENCIES)
        or sum(row.size_bytes for row in archive_files) > MAX_TOTAL_BYTES
    ):
        _invalid()
    for row in excluded_rows:
        if not isinstance(row, dict):
            _invalid()
        _keys(row, {"path", "reason"})
        path = _text(row["path"], limit=2000)
        _safe_relative(path)
        reason = _text(row["reason"])
        if PurePosixPath(path).as_posix() != path or path in paths or _excluded(path) != reason:
            _invalid()
        paths.add(path)
        exclusions.append(ProjectArchiveExclusion(path, reason))
    manifest = ProjectVersionManifest(
        receipt.owner_id,
        receipt.project_id,
        receipt.version,
        parent,
        tuple(archive_files),
        tuple(exclusions),
        receipt.manifest_sha256,
    )
    if hashlib.sha256(manifest_bytes(manifest)).hexdigest() != manifest.sha256:
        _invalid()
    return manifest


class LocalArchiveCatalogProvider:
    def __init__(self, root: Path) -> None:
        self.local = LocalGitProjectVersionProvider(root)

    def _git(self, *args: str, payload: bytes | None = None) -> bytes:
        return self.local._git(*args, payload=payload, extra_env={"GIT_NO_REPLACE_OBJECTS": "1"})

    def _blobs(self, oids: set[str], cache: dict[str, tuple[str, int, bool]]) -> dict[str, bytes]:
        """Two bounded Git batch operations per version, never one process per file."""
        ordered = sorted(oids)
        if (
            not ordered
            or len(ordered) > MAX_FILES + 2
            or any(not SHA.fullmatch(oid) for oid in ordered)
        ):
            _invalid()
        payload = ("\n".join(ordered) + "\n").encode("ascii")
        metadata = self._git("cat-file", "--batch-check", payload=payload).splitlines()
        if len(metadata) != len(ordered):
            _invalid()
        sizes: dict[str, int] = {}
        for oid, line in zip(ordered, metadata, strict=True):
            parts = line.split()
            if (
                len(parts) != 3
                or parts[0] != oid.encode()
                or parts[1] != b"blob"
                or not parts[2].isdigit()
            ):
                _invalid()
            size = int(parts[2])
            if size > MAX_FILE_BYTES:
                _invalid()
            sizes[oid] = size
        if sum(sizes.values()) > MAX_TOTAL_BYTES + 2 * MAX_FILE_BYTES:
            _invalid()
        needed = [oid for oid in ordered if oid not in cache]
        if not needed:
            return {}
        raw = self._git("cat-file", "--batch", payload=("\n".join(needed) + "\n").encode("ascii"))
        cursor = 0
        result: dict[str, bytes] = {}
        for oid in needed:
            end = raw.find(b"\n", cursor)
            if end < 0 or raw[cursor:end] != f"{oid} blob {sizes[oid]}".encode():
                _invalid()
            cursor = end + 1
            content = raw[cursor : cursor + sizes[oid]]
            cursor += sizes[oid]
            if len(content) != sizes[oid] or raw[cursor : cursor + 1] != b"\n":
                _invalid()
            cursor += 1
            text = content.decode("utf-8")
            if b"\0" in content or SECRET.search(text):
                _invalid()
            result[oid] = content
            cache[oid] = hashlib.sha256(content).hexdigest(), len(content), bool(text.strip())
        if cursor != len(raw):
            _invalid()
        return result

    def snapshot(self) -> ArchiveCatalogSnapshot:
        try:
            return self._snapshot()
        except DomainError as error:
            # Relative filenames in low-level diagnostics are untrusted metadata.
            raise DomainError(error.code, error.message, error.status_code) from None
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
            _invalid()

    def _bound(self) -> tuple[str, GitHubPrivateRepository]:
        self.local._root()
        if any(
            (self.local.root / ".git" / path).exists()
            for path in ("objects/info/alternates", "info/grafts", "shallow")
        ):
            _invalid()
        state = self.local.root / ".git/researchos"
        binding = _decode(self.local._read_path(state / "binding.json"))
        _keys(binding, {"project_id", "repository"})
        project = _text(binding["project_id"])
        repository = _repository(binding["repository"])
        return project, repository

    def _snapshot(self) -> ArchiveCatalogSnapshot:
        project, repository = self._bound()
        owner = f"github:{repository.owner_id}"
        state = self.local.root / ".git/researchos"
        version_dir = state / "versions"
        if not version_dir.exists():
            return ArchiveCatalogSnapshot(project, repository, ())
        if not version_dir.is_dir():
            _invalid()
        records = list(version_dir.iterdir())
        if len(records) > MAX_VERSIONS:
            raise DomainError(
                "ARCHIVE_CATALOG_TOO_MANY_VERSIONS",
                "Archive catalog exceeds its version bound; narrow the registered archive scope",
                409,
            )
        result: list[ArchiveCatalogVersion] = []
        cache: dict[str, tuple[str, int, bool]] = {}
        for path in sorted(records):
            receipt = _receipt(_decode(self.local._read_path(path)), project, owner, path.name)
            result.append(self._verify_receipt(receipt, cache))
        return ArchiveCatalogSnapshot(project, repository, tuple(result))

    def verify_receipt(self, receipt: LocalProjectVersionReceipt) -> ArchiveCatalogVersion:
        """Prove one existing Git version even if a CLI receipt write was interrupted."""
        try:
            project, repository = self._bound()
            _receipt(asdict(receipt), project, f"github:{repository.owner_id}", receipt.tag + ".json")
            return self._verify_receipt(receipt, {})
        except DomainError as error:
            raise DomainError(error.code, error.message, error.status_code) from None
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
            _invalid()

    def _verify_receipt(self, receipt: LocalProjectVersionReceipt, cache: dict[str, tuple[str, int, bool]]) -> ArchiveCatalogVersion:
        owner, project = receipt.owner_id, receipt.project_id
        commit = (
            self._git("rev-parse", "--verify", "refs/tags/" + receipt.tag)
            .decode("ascii")
            .strip()
        )
        if commit != receipt.commit_sha:
            _invalid()
        tree = self._git("ls-tree", "-r", "-z", commit)
        entries = tree.split(b"\0")
        if entries[-1] != b"" or len(entries) > MAX_FILES + 3:
            _invalid()
        tree_oids: dict[str, str] = {}
        for entry in entries[:-1]:
            metadata, name = entry.split(b"\t", 1)
            mode, kind, tree_oid = metadata.split(b" ")
            relative = name.decode("utf-8")
            _safe_relative(relative)
            if mode != b"100644" or kind != b"blob" or relative in tree_oids:
                _invalid()
            tree_oids[relative] = _sha(tree_oid.decode("ascii"))
        manifest_path = f".researchos/versions/{receipt.tag}.json"
        if BINDING not in tree_oids or manifest_path not in tree_oids:
            _invalid()
        # Metadata must always be decoded, while repeated code blobs reuse proof.
        meta_oids = {tree_oids[BINDING], tree_oids[manifest_path]}
        meta = self._blobs(meta_oids, {})
        if _decode(meta[tree_oids[BINDING]]) != {"owner_id": owner, "project_id": project}:
            _invalid()
        manifest = _manifest(_decode(meta[tree_oids[manifest_path]]), receipt)
        if set(tree_oids) != {row.path for row in manifest.files} | {BINDING, manifest_path}:
            _invalid()
        parents = (
            self._git("rev-list", "--parents", "-n", "1", commit)
            .decode("ascii")
            .strip()
            .split()
        )
        if parents != [commit] + ([manifest.parent_commit] if manifest.parent_commit else []):
            _invalid()
        self._blobs({tree_oids[row.path] for row in manifest.files}, cache)
        for row in manifest.files:
            oid = tree_oids[row.path]
            if cache[oid][:2] != (row.sha256, row.size_bytes):
                _invalid()
            if row.path in REQUIRED - {".env.example"} and not cache[oid][2]:
                _invalid()
        # Ref races invalidate this snapshot rather than changing its identity.
        if (
            self._git("rev-parse", "--verify", "refs/tags/" + receipt.tag)
            .decode("ascii")
            .strip()
            != commit
        ):
            _invalid()
        return ArchiveCatalogVersion(receipt, manifest)
