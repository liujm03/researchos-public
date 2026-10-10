"""Exact manifest Git commits, without hooks, a shared index or remote writes.

This adapter deliberately admits UTF-8 code/documentation only. Scientific data,
binary assets and private notes need a separate, explicitly approved storage policy.
"""

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Never

from app.domain.project_archive import (
    LocalProjectVersionReceipt,
    ProjectArchiveExclusion,
    ProjectArchiveFile,
    ProjectVersionManifest,
    RestoredProjectVersion,
)
from app.errors import DomainError

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILES = 2000
BINDING = ".researchos/project.json"
ARCHIVE_REF = "refs/heads/researchos-archive"
REQUIRED = {
    "README.md", "AGENTS.md", "AI_HANDOFF.md", "CHANGELOG.md", "docs/QUICKSTART.md",
    "docs/RESTORE.md", ".env.example", ".gitignore",
}
DEPENDENCIES = {"pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod"}
TEXT_SUFFIXES = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json",
    ".toml", ".yaml", ".yml", ".md", ".txt", ".lock", ".css", ".html",
    ".sh", ".ps1", ".cmd", ".bat", ".sql", ".tex", ".bib", ".rs", ".go",
    ".c", ".h", ".cpp", ".hpp", ".ini", ".cfg", ".xml", ".gitignore", ".mod",
    ".mako", ".dockerfile",
}
# Explicit reviewed public LaTeX implementation resources. This does not admit
# arbitrary manuscripts, new file types elsewhere or runtime/private material.
PUBLIC_TEMPLATE_CODE = frozenset({
    "docker/latex/templates/IEEEtran-1.8b/IEEEtran.cls",
    "docker/latex/templates/IEEEtran-1.8b/IEEEtran.bst",
    "docker/latex/templates/elsarticle-3.5/elsarticle.cls",
    "docker/latex/templates/elsarticle-3.5/elsarticle-num.bst",
    "docker/latex/templates/elsarticle-3.5/elsarticle.dtx",
    "docker/latex/templates/elsarticle-3.5/elsarticle.ins",
})
PRIVATE_DIRS = {
    ".git", ".codex", ".agents", ".aws", ".ssh", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "cache",
    "data", "datasets", "dataset", "weights", "checkpoints", "uploads", "attachments",
    "private", "notes", "logs", "runtime", "backups", "secrets",
}
PRIVATE_SUFFIXES = {
    ".pdf", ".db", ".sqlite", ".sqlite3", ".dump", ".pt", ".pth", ".ckpt",
    ".safetensors", ".onnx", ".pem", ".key", ".p12", ".pfx", ".log", ".zip",
}
VERSION = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*)?\Z")
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"
)
SECRET_FIELD = r"(?:[A-Za-z_]\w*_)?(?:token|password|passwd|secret|api_key|apikey)"
ASSIGNMENT = re.compile(
    rf"(?im)^[ \t]*[\"']?{SECRET_FIELD}[\"']?[ \t]*[:=][ \t]*[\"']?([^\r\n\"'#;,]+)"
)
QUOTED_SECRET = re.compile(
    rf"(?im)^[ \t]*[\"']?{SECRET_FIELD}[\"']?[ \t]*[:=][ \t]*[\"']([^\"'\r\n]+)[\"']"
)
PLACEHOLDERS = {"replace_with_secret", "your_api_key_here", "replace_me_with_secret",
                "your_token_here", "your_password_here", "changeme", "placeholder",
                "researchos-test-only-not-a-credential", "researchos_test_only_not_a_credential"}


def _fail(code: str, message: str, *, path: str | None = None, rule: str | None = None) -> Never:
    details = {"relative_path": path, "rule": rule} if path is not None else None
    raise DomainError(code, message, 409, details=details)


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def manifest_bytes(manifest: ProjectVersionManifest) -> bytes:
    """Hash excludes its own digest, but includes identity and all exclusion decisions."""
    value = asdict(manifest)
    value.pop("sha256")
    return _json(value)


def _safe_relative(value: str) -> None:
    parts = PurePosixPath(value).parts
    if not parts or value.startswith("/") or "\\" in value or ":" in value or any(
        part in {".", ".."} for part in parts
    ) or any(ord(c) < 32 for c in value):
        _fail("ARCHIVE_PATH_INVALID", "Archive contains an unsafe relative path")


def _excluded(value: str) -> str | None:
    path = PurePosixPath(value)
    lower = [part.lower() for part in path.parts]
    # Product source routes (e.g. src/app/datasets) are code, not dataset storage.
    # Only these declared application source roots get this naming exception;
    # PDF/binary/credential exclusions still apply to every path below.
    source_root = lower[:3] in (["apps", "web", "src"], ["apps", "api", "app"])
    scientific_names = {"data", "datasets", "dataset", "weights", "checkpoints", "uploads", "attachments", "private", "notes", "logs", "runtime", "backups"}
    excluded_dirs = PRIVATE_DIRS - scientific_names if source_root else PRIVATE_DIRS
    if any(part in excluded_dirs or part.endswith(".egg-info") for part in lower):
        return "private_or_runtime_directory"
    if lower[:2] == [".github", "workflows"] or path.name == ".gitattributes":
        return "remote_execution_or_checkout_policy"
    if path.name.lower().startswith(".env") and path.name != ".env.example":
        return "credential_file"
    if path.suffix.lower() in PRIVATE_SUFFIXES:
        return "scientific_data_or_private_binary"
    return None


class LocalGitProjectVersionProvider:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()

    def _git(
        self, *args: str, payload: bytes | None = None, extra_env: dict[str, str] | None = None,
        allow_failure: bool = False,
    ) -> bytes:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_TERMINAL_PROMPT": "0"})
        if extra_env:
            env.update(extra_env)
        try:
            result = subprocess.run(
                ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.autocrlf=false",
                 "-c", "core.fsmonitor=false", "-c", "commit.gpgSign=false", "-C", str(self.root), *args],
                input=payload, capture_output=True, env=env, timeout=30, check=False,
            )
        except subprocess.TimeoutExpired:
            _fail("ARCHIVE_GIT_TIMEOUT", "Local Git operation exceeded its time limit")
        except OSError:
            _fail("ARCHIVE_GIT_UNAVAILABLE", "Local Git could not be started")
        if result.returncode and not allow_failure:
            _fail("ARCHIVE_GIT_FAILED", "Local Git operation failed; no remote operation was attempted")
        if result.returncode:
            return b""
        return result.stdout

    def _root(self) -> None:
        self._read_path(self.root)
        if not (self.root / ".git").is_dir() or (self.root / ".git").is_symlink():
            _fail("ARCHIVE_INDEPENDENT_REPO_REQUIRED", "Use a dedicated repository, not a parent repository or worktree")
        for directory, folders, files in os.walk(self.root / ".git", followlinks=False):
            for name in [*folders, *files]:
                details = (Path(directory) / name).lstat()
                if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
                    _fail("ARCHIVE_PATH_INVALID", "Repository metadata cannot contain linked/reparse paths")
        self._read_ancestors(self.root / ".git")
        top = Path(self._git("rev-parse", "--show-toplevel").decode().strip()).resolve()
        if top != self.root.resolve():
            _fail("ARCHIVE_INDEPENDENT_REPO_REQUIRED", "Project must be the independent Git repository root")

    def _read_path(self, path: Path) -> bytes:
        relative = path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) and path != self.root else None
        # All ancestors are checked, including Windows junction/reparse points.
        for part in (path, *path.parents):
            details = part.lstat()
            if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
                _fail("ARCHIVE_PATH_INVALID", "Linked/reparse paths are not publishable", path=relative, rule="linked_or_reparse_source")
        if path == self.root:
            return b""
        if not path.resolve().is_relative_to(self.root.resolve()) or not path.is_file():
            _fail("ARCHIVE_PATH_INVALID", "Archive source must be a contained regular file", path=relative, rule="contained_regular_file_required")
        if path.stat().st_size > MAX_FILE_BYTES:
            _fail("ARCHIVE_FILE_TOO_LARGE", "A source file exceeds the code archive size limit", path=relative, rule="file_byte_limit")
        content = path.read_bytes()
        if len(content) > MAX_FILE_BYTES:
            _fail("ARCHIVE_FILE_TOO_LARGE", "A source file exceeds the code archive size limit", path=relative, rule="file_byte_limit")
        return content

    def _head(self) -> str | None:
        value = self._git("rev-parse", "--verify", ARCHIVE_REF, allow_failure=True).decode().strip()
        return value or None

    def preflight(self, *, owner_id: str, project_id: str, version: str) -> ProjectVersionManifest:
        self._root()
        if not VERSION.fullmatch(version) or not owner_id or not project_id:
            _fail("ARCHIVE_IDENTITY_INVALID", "Archive requires owner, project and a semantic version tag")
        if self._git("rev-parse", "--verify", "refs/tags/" + version, allow_failure=True):
            _fail("ARCHIVE_VERSION_EXISTS", "Published/local version tags are immutable")
        head = self._head()
        binding = _json({"owner_id": owner_id, "project_id": project_id})
        if not head and self._git("rev-parse", "--verify", "HEAD", allow_failure=True):
            _fail("ARCHIVE_PROJECT_MISMATCH", "Adopting existing history requires a separate explicit binding workflow")
        if head and self._git("show", head + ":" + BINDING, allow_failure=True) != binding:
            _fail("ARCHIVE_PROJECT_MISMATCH", "Existing history is not bound to this owner/project")
        tracked = set(self._git("ls-files", "--cached", "-z").decode().split("\0")) - {""}
        untracked = set(self._git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""}
        if len(tracked | untracked) > MAX_FILES:
            _fail("ARCHIVE_TOO_MANY_FILES", "Project exceeds the bounded archive file limit")
        files: list[ProjectArchiveFile] = []
        excluded: list[ProjectArchiveExclusion] = []
        total = 0
        for relative in sorted(tracked | untracked):
            _safe_relative(relative)
            reason = _excluded(relative)
            if reason:
                if relative in tracked:
                    _fail("ARCHIVE_TRACKED_PRIVATE_FILE", "Git tracks an excluded private/runtime file; remove it from the publishable project first", path=relative, rule=reason)
                excluded.append(ProjectArchiveExclusion(relative, reason))
                continue
            if relative.startswith(".researchos/"):
                if relative not in tracked or not head:
                    _fail("ARCHIVE_RESERVED_PATH", "Untracked archive metadata must not be injected")
                if self._read_path(self.root / relative) != self._git("show", head + ":" + relative, allow_failure=True):
                    _fail("ARCHIVE_RESERVED_PATH", "Locally edited archive metadata requires review; it cannot be overwritten")
                continue
            target = self.root / relative
            self._read_ancestors(target.parent)
            if not target.exists() and relative in tracked:
                # Deletions are part of the exact snapshot, but broken links are not.
                if target.is_symlink():
                    _fail("ARCHIVE_PATH_INVALID", "Archive source contains a broken symbolic link")
                continue
            content = self._read_path(target)
            name = PurePosixPath(relative).name
            if relative not in PUBLIC_TEMPLATE_CODE and PurePosixPath(relative).suffix.lower() not in TEXT_SUFFIXES and name not in {
                ".gitignore", ".dockerignore", ".env.example", "Dockerfile", "Makefile", "LICENSE", "LICENSE.md",
            }:
                _fail("ARCHIVE_FILE_TYPE_UNAPPROVED", "Unknown file types require an explicit export policy", path=relative, rule="utf8_code_documentation_allowlist")
            try:
                text = content.decode("utf-8")
            except UnicodeError:
                _fail("ARCHIVE_BINARY_UNAPPROVED", "Binary files require an explicit export policy", path=relative, rule="valid_utf8_required")
            if relative in REQUIRED - {".env.example"} and not text.strip():
                _fail("ARCHIVE_DOCUMENTATION_REQUIRED", "Required usage/handoff documentation cannot be empty", path=relative, rule="required_documentation_nonempty")
            if b"\0" in content or SECRET.search(text):
                _fail("ARCHIVE_SECRET_OR_BINARY", "Source contains a private key/token or binary content", path=relative, rule="private_key_token_or_nul")
            for match in QUOTED_SECRET.finditer(text):
                value = match.group(1).strip()
                if re.fullmatch(r"[A-Za-z0-9_+/=-]+", value) and value.lower() not in PLACEHOLDERS:
                    _fail("ARCHIVE_POSSIBLE_SECRET", "A hard-coded credential literal needs review/removal", path=relative, rule="credential_literal")
            for match in ASSIGNMENT.finditer(text):
                value = match.group(1).strip()
                minimum = 1 if name == ".env.example" else 16
                if re.fullmatch(r"[A-Za-z0-9_+/=-]{" + str(minimum) + r",}", value) and value.lower() not in PLACEHOLDERS:
                    _fail("ARCHIVE_POSSIBLE_SECRET", "A credential-like literal needs review/removal", path=relative, rule="credential_assignment")
            total += len(content)
            if total > MAX_TOTAL_BYTES:
                _fail("ARCHIVE_TOO_LARGE", "Project exceeds the code archive total size limit")
            files.append(ProjectArchiveFile(relative, hashlib.sha256(content).hexdigest(), len(content)))
        names = {item.path for item in files}
        if not REQUIRED.issubset(names) or not names.intersection(DEPENDENCIES):
            _fail("ARCHIVE_DOCUMENTATION_REQUIRED", "Version needs usage, restore, AI handoff, environment and dependency documentation")
        result = ProjectVersionManifest(owner_id, project_id, version, head, tuple(files), tuple(excluded), "")
        return ProjectVersionManifest(owner_id, project_id, version, head, tuple(files), tuple(excluded), hashlib.sha256(manifest_bytes(result)).hexdigest())

    def commit_version(self, manifest: ProjectVersionManifest, *, author_name: str, author_email: str) -> LocalProjectVersionReceipt:
        current = self.preflight(owner_id=manifest.owner_id, project_id=manifest.project_id, version=manifest.version)
        if current != manifest:
            _fail("ARCHIVE_MANIFEST_CHANGED", "Project changed after preflight; create a fresh manifest")
        if not author_name.strip() or not author_email.strip() or any(c in author_name + author_email for c in "\r\n\0"):
            _fail("ARCHIVE_AUTHOR_INVALID", "Commit author identity is required")
        # Capture once; final preflight catches source/index/ref changes before ref publication.
        snapshot = {entry.path: self._read_path(self.root / entry.path) for entry in manifest.files}
        for entry in manifest.files:
            if hashlib.sha256(snapshot[entry.path]).hexdigest() != entry.sha256:
                _fail("ARCHIVE_MANIFEST_CHANGED", "Source changed while capturing exact version bytes")
        snapshot[BINDING] = _json({"owner_id": manifest.owner_id, "project_id": manifest.project_id})
        snapshot[f".researchos/versions/{manifest.version}.json"] = _json(asdict(manifest))
        with tempfile.TemporaryDirectory(prefix="researchos-git-index-") as folder:
            env = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
            self._git("read-tree", "--empty", extra_env=env)
            for path, content in sorted(snapshot.items()):
                oid = self._git("hash-object", "-w", "--stdin", payload=content).decode().strip()
                self._git("update-index", "--add", "--cacheinfo", "100644," + oid + "," + path, extra_env=env)
            tree = self._git("write-tree", extra_env=env).decode().strip()
        env = {"GIT_AUTHOR_NAME": author_name, "GIT_AUTHOR_EMAIL": author_email,
               "GIT_COMMITTER_NAME": author_name, "GIT_COMMITTER_EMAIL": author_email}
        parents = ["-p", manifest.parent_commit] if manifest.parent_commit else []
        commit = self._git("commit-tree", tree, *parents, payload=("ResearchOS " + manifest.version + "\n").encode(), extra_env=env).decode().strip()
        if self.preflight(owner_id=manifest.owner_id, project_id=manifest.project_id, version=manifest.version) != manifest:
            _fail("ARCHIVE_MANIFEST_CHANGED", "Project changed before publishing the local version")
        previous = manifest.parent_commit or "0" * 40
        transaction = f"start\nupdate {ARCHIVE_REF} {commit} {previous}\ncreate refs/tags/{manifest.version} {commit}\nprepare\ncommit\n"
        self._git("update-ref", "--stdin", payload=transaction.encode())
        return LocalProjectVersionReceipt(manifest.owner_id, manifest.project_id, manifest.version, commit, manifest.sha256, manifest.version)

    def restore_version(self, tag: str, destination: str) -> RestoredProjectVersion:
        self._root()
        if not VERSION.fullmatch(tag):
            _fail("ARCHIVE_VERSION_INVALID", "Recovery requires an immutable semantic version tag")
        commit = self._git("rev-parse", "refs/tags/" + tag).decode().strip()
        raw = self._git("show", f"{commit}:.researchos/versions/{tag}.json")
        data: Any = json.loads(raw)
        manifest = ProjectVersionManifest(data["owner_id"], data["project_id"], data["version"], data["parent_commit"], tuple(ProjectArchiveFile(**v) for v in data["files"]), tuple(ProjectArchiveExclusion(**v) for v in data["excluded"]), data["sha256"])
        if manifest.version != tag or hashlib.sha256(manifest_bytes(manifest)).hexdigest() != manifest.sha256:
            _fail("ARCHIVE_RECOVERY_INVALID", "Retained version manifest is inconsistent")
        expected_binding = _json({"owner_id": manifest.owner_id, "project_id": manifest.project_id})
        if self._git("show", commit + ":" + BINDING) != expected_binding:
            _fail("ARCHIVE_RECOVERY_INVALID", "Retained version identity does not match its project binding")
        if len(manifest.files) > MAX_FILES or any(entry.size_bytes < 0 or entry.size_bytes > MAX_FILE_BYTES for entry in manifest.files) or sum(entry.size_bytes for entry in manifest.files) > MAX_TOTAL_BYTES:
            _fail("ARCHIVE_RECOVERY_INVALID", "Retained version exceeds the bounded recovery limits")
        target = Path(destination).absolute()
        if target.exists():
            _fail("ARCHIVE_RECOVERY_DESTINATION_EXISTS", "Recovery requires a new directory; existing files are preserved")
        self._read_ancestors(target.parent)
        # Read blobs directly: no checkout filters, executable hooks or archive extraction.
        recovered: dict[str, bytes] = {}
        for entry in manifest.files:
            _safe_relative(entry.path)
            if _excluded(entry.path):
                _fail("ARCHIVE_RECOVERY_INVALID", "Retained manifest contains an excluded path")
            content = self._git("show", commit + ":" + entry.path)
            if len(content) != entry.size_bytes or hashlib.sha256(content).hexdigest() != entry.sha256:
                _fail("ARCHIVE_RECOVERY_INVALID", "A retained blob does not match its version manifest")
            recovered[entry.path] = content
        target.mkdir()
        for relative, content in recovered.items():
            file = target / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open("xb") as handle:
                handle.write(content)
        receipt = LocalProjectVersionReceipt(manifest.owner_id, manifest.project_id, tag, commit, manifest.sha256, tag)
        return RestoredProjectVersion(str(target), receipt, len(recovered))

    def _read_ancestors(self, path: Path) -> None:
        for part in (path, *path.parents):
            try:
                details = part.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
                _fail("ARCHIVE_PATH_INVALID", "Recovery destination cannot traverse linked paths")
