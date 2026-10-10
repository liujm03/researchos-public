"""Create only frozen, resumable stdlib project scaffolds in a managed container."""

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from app.domain.github_archive import GitHubPrivateRepository
from app.domain.provisioning import (
    LocalProvisionReceipt,
    ProvisionFile,
    ProvisionScope,
    managed_root_fingerprint,
)
from app.errors import DomainError
from app.providers.project_archives.catalog import _decode, _repository
from app.providers.project_archives.execution import _unix_lock
from app.providers.project_archives.local_git import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    LocalGitProjectVersionProvider,
)

TEMPLATE_KEY = "python-context-v1"
MARKER = ".researchos/provisioning.json"
CONTEXT = "research_project/context.json"


def _fail() -> DomainError:
    return DomainError(
        "PROJECT_PROVISIONING_CONFLICT",
        "Project initialization scope or frozen source differs; existing files are preserved",
        409,
    )


def _component(value: str) -> None:
    reserved = (
        {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
        | {f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)}
        | {prefix + number for prefix in ("COM", "LPT") for number in ("¹", "²", "³")}
    )
    if (
        not value
        or len(value) > 120
        or value != value.strip()
        or any(c in value for c in '.<>:"/\\|?*')
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or value.upper() in reserved
    ):
        raise _fail()


def _path(path: Path, *, directory: bool = False) -> None:
    try:
        for part in (path, *path.parents):
            if not part.exists() and not part.is_symlink():
                continue
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise _fail()
        if directory and not path.is_dir():
            raise _fail()
    except OSError:
        raise _fail() from None


def _bytes(path: Path) -> bytes:
    _path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise _fail()
    content = path.read_bytes()
    if len(content) > MAX_FILE_BYTES:
        raise _fail()
    return content


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _manifest(files: tuple[ProvisionFile, ...]) -> str:
    return hashlib.sha256(
        _json(
            [
                {"path": file.path, "sha256": file.sha256, "size_bytes": file.size_bytes}
                for file in files
            ]
        )
    ).hexdigest()


class ManagedProjectProvisionProvider:
    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root))
        self._locked_project: str | None = None
        _path(self.root, directory=True)

    def _scope(self, scope: ProvisionScope) -> Path:
        _path(self.root, directory=True)
        try:
            identity = uuid.UUID(scope.project_id)
        except (ValueError, AttributeError):
            raise _fail() from None
        if (
            str(identity) != scope.project_id
            or scope.managed_root_fingerprint != managed_root_fingerprint(self.root)
            or not re.fullmatch(r"[a-f0-9]{64}", scope.plan_sha256)
            or not re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", scope.github_owner
            )
            or "--" in scope.github_owner
            or type(scope.github_owner_id) is not int
            or not 0 < scope.github_owner_id <= 2**63 - 1
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", scope.repository_name)
            or scope.repository_name in {".", ".."}
        ):
            raise _fail()
        _component(scope.folder_name)
        target = self.root / scope.folder_name
        _path(target)
        return target

    def _require_lock(self, scope: ProvisionScope) -> None:
        if self._locked_project != scope.project_id:
            raise DomainError(
                "PROJECT_PROVISIONING_LOCK_REQUIRED",
                "Initialization writes require the exclusive project lock",
                409,
            )

    def plan_files(self, project_id: str, name: str) -> tuple[ProvisionFile, ...]:
        try:
            identity = uuid.UUID(project_id)
        except (ValueError, AttributeError):
            raise _fail() from None
        if (
            str(identity) != project_id
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > 320
            or "\0" in name
        ):
            raise _fail()
        context = {
            "project_id": project_id,
            "name": name,
            "template_key": TEMPLATE_KEY,
            "scientific_implementation": "NOT_STARTED",
        }
        rendered_context = json.dumps(context, ensure_ascii=False, indent=2) + "\n"
        visible_context = rendered_context.replace("`", "\\u0060")
        common = "Python 3.12+ and Git are required. The doctor and tests use only the Python standard library.\n"
        sources = {
            CONTEXT: rendered_context,
            "research_project/__init__.py": '''"""Project identity and scaffold checks; scientific methods are not implemented."""
import json
from pathlib import Path


def project_context():
    return json.loads(Path(__file__).with_name("context.json").read_text(encoding="utf-8"))


def doctor():
    root = Path(__file__).resolve().parent.parent
    required = ("README.md", "AGENTS.md", "AI_HANDOFF.md", "CHANGELOG.md", "docs/QUICKSTART.md", "docs/RESTORE.md", ".env.example", ".gitignore", "pyproject.toml")
    checks = {name: (root / name).is_file() for name in required}
    checks["independent_git_directory"] = (root / ".git").is_dir()
    return {"context": project_context(), "checks": checks, "ready": all(checks.values()), "training_implemented": False, "evaluation_implemented": False}
''',
            "research_project/__main__.py": """import argparse
import json
import sys
from . import doctor, project_context


def main():
    parser = argparse.ArgumentParser(description="Inspect this project scaffold; no training or network calls.")
    parser.add_argument("--doctor", action="store_true")
    arguments = parser.parse_args()
    result = doctor() if arguments.doctor else project_context()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not arguments.doctor or result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
""",
            "tests/test_context.py": """import unittest
from research_project import doctor, project_context


class ContextTest(unittest.TestCase):
    def test_context_has_stable_identity(self):
        self.assertEqual(project_context()["template_key"], "python-context-v1")
        self.assertTrue(project_context()["project_id"])

    def test_scaffold_and_scientific_status_are_honest(self):
        report = doctor()
        self.assertTrue(report["ready"])
        self.assertFalse(report["training_implemented"])
        self.assertFalse(report["evaluation_implemented"])
""",
            "README.md": "# Research project workspace\n\n```json\n"
            + visible_context
            + "```\n\n"
            + common
            + "\n## Run\n\nFrom this directory:\n\n```shell\npython -m research_project --doctor\npython -m unittest discover -s tests -v\n```\n\nThis version contains identity metadata, a doctor and scaffold tests. It does not implement training, evaluation, a model, dataset downloads or claimed research results. Creating the files does not itself run these checks.\n\nSee docs/QUICKSTART.md, docs/RESTORE.md and AI_HANDOFF.md. Research data and secrets are stored separately from the private code archive.\n",
            "AGENTS.md": "# Project working instructions\n\nRead README.md and AI_HANDOFF.md before changing this independent project. Preserve the project identity in research_project/context.json. Record actual tests and known limitations; do not invent research results. Keep datasets, PDFs, weights, credentials, databases and private notes out of Git. Use the ResearchOS bound private archive workflow for version publication; do not force-push, replace tags, change destinations or enable remote CI. Scientific execution and external data transfers require the owner's configured scope.\n",
            "AI_HANDOFF.md": "# AI handoff\n\n## Implemented\n\nAn independent Python standard-library scaffold records project identity and inspects documentation. No scientific algorithm, model, training or evaluation is implemented.\n\n## Verification\n\nInitialization does not execute the doctor or tests. Run the README commands and record actual output before claiming a verified version.\n\n## Next work\n\nObtain the owner's research question, selected sources, data access and desired implementation. Create a reproducible method and configuration, then document executed validation and limitations. Preserve this project's identity and existing human edits.\n",
            "CHANGELOG.md": "# Changelog\n\n## Initial scaffold\n\nAdded project context, standard-library doctor, scaffold tests and usage/recovery/handoff instructions. Scientific work and actual project test results are not yet recorded. Archive tags and exact version receipts are managed by ResearchOS.\n",
            "docs/QUICKSTART.md": "# Quickstart\n\n"
            + common
            + "\n1. Open a terminal in this project directory.\n2. Run `python -m research_project --doctor`.\n3. Run `python -m unittest discover -s tests -v`.\n\nNo package installation is required for these commands. `pyproject.toml` declares the project metadata; no ML dependencies are installed by initialization. Choose and pin research dependencies when a real implementation is approved. `.env.example` contains no credentials, and `.env` stays local.\n",
            "docs/RESTORE.md": "# Restore an exact code version\n\nUse the owner-bound private GitHub repository and a verified immutable tag shown in ResearchOS. Authenticate using the host credential manager. Clone that repository into a NEW empty destination, then run `git switch --detach <verified-tag>` with the actual recorded tag. Check `git rev-parse HEAD` against the recorded commit. Never reset or clean an existing project.\n\nThe commit contains `.researchos/project.json` and `.researchos/versions/<verified-tag>.json`; verify project/owner identity and source SHA-256/size against the version manifest. The ResearchOS `scripts/archive_project.py restore` command performs those file checks when run with its configured runtime. Then run the README doctor and test commands.\n\nPrivate PDFs, notes, databases, data, checkpoints and credentials are separate backups. Code cloning alone does not restore them. The local initialization marker and CLI state are not published; reconnect an existing restored project through the explicit archive binding workflow rather than re-running new-project initialization.\n",
            ".env.example": "# Optional future project environment; keep credentials local.\n",
            ".gitignore": ".env\n.env.*\n!.env.example\n.researchos/\n.venv/\nvenv/\n__pycache__/\n*.pyc\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\ndata/\ndatasets/\nweights/\ncheckpoints/\nuploads/\nattachments/\nnotes/\nprivate/\nlogs/\nbackups/\n*.pdf\n*.db\n*.sqlite*\n*.dump\n*.pt\n*.pth\n*.ckpt\n*.safetensors\n",
            "pyproject.toml": '[project]\nname = "research-project-'
            + identity.hex
            + '"\nversion = "0.1.0"\ndescription = "Independent research workspace scaffold"\nrequires-python = ">=3.12"\ndependencies = []\n',
        }
        return tuple(
            ProvisionFile(
                path,
                text,
                hashlib.sha256(text.encode("utf-8")).hexdigest(),
                len(text.encode("utf-8")),
            )
            for path, text in sorted(sources.items())
        )

    def _files(self, scope: ProvisionScope, files: tuple[ProvisionFile, ...]) -> str:
        if (
            not files
            or len(files) > MAX_FILES
            or sum(file.size_bytes for file in files) > MAX_TOTAL_BYTES
        ):
            raise _fail()
        for file in files:
            path = PurePosixPath(file.path)
            if (
                path.as_posix() != file.path
                or path.is_absolute()
                or any(part in {".", ".."} for part in path.parts)
                or "\\" in file.path
                or ":" in file.path
                or not 0 <= file.size_bytes <= MAX_FILE_BYTES
            ):
                raise _fail()
            content = file.content.encode("utf-8")
            if (
                len(content) != file.size_bytes
                or hashlib.sha256(content).hexdigest() != file.sha256
                or b"\0" in content
            ):
                raise _fail()
        context_file = next((file for file in files if file.path == CONTEXT), None)
        if context_file is None:
            raise _fail()
        context = _decode(context_file.content.encode("utf-8"))
        name = context.get("name")
        if not isinstance(name, str) or files != self.plan_files(scope.project_id, name):
            raise _fail()
        return _manifest(files)

    def _marker(self, scope: ProvisionScope, files: tuple[ProvisionFile, ...]) -> bytes:
        return _json(
            {
                "format": TEMPLATE_KEY,
                "scope": asdict(scope),
                "manifest_sha256": self._files(scope, files),
                "files": [
                    {"path": file.path, "sha256": file.sha256, "size_bytes": file.size_bytes}
                    for file in files
                ],
            }
        )

    def _receipt(
        self, scope: ProvisionScope, files: tuple[ProvisionFile, ...]
    ) -> LocalProvisionReceipt:
        return LocalProvisionReceipt(
            "provision-" + uuid.UUID(scope.project_id).hex,
            str(self._scope(scope)),
            files,
            _manifest(files),
        )

    def _tree(self, target: Path) -> None:
        _path(target, directory=True)
        for directory, folders, files in os.walk(target, followlinks=False):
            for name in [*folders, *files]:
                _path(Path(directory) / name)

    def _atomic(self, target: Path, content: bytes, state: Path) -> None:
        _path(target)
        _path(state, directory=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        _path(target.parent, directory=True)
        if target.exists():
            if _bytes(target) != content:
                raise _fail()
            return
        fd, name = tempfile.mkstemp(prefix="pending-", suffix=".tmp", dir=state)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            _path(target.parent, directory=True)
            try:
                os.link(temporary, target)
            except FileExistsError:
                if _bytes(target) != content:
                    raise _fail() from None
        finally:
            temporary.unlink(missing_ok=True)

    def inspect(
        self, scope: ProvisionScope, files: tuple[ProvisionFile, ...]
    ) -> LocalProvisionReceipt | None:
        target = self._scope(scope)
        marker = self._marker(scope, files)
        if not target.exists():
            return None
        self._tree(target)
        if _bytes(target / MARKER) != marker:
            raise _fail()
        complete = True
        for file in files:
            path = target / file.path
            if path.exists():
                if _bytes(path) != file.content.encode("utf-8"):
                    raise _fail()
            else:
                complete = False
        if (target / ".git").exists():
            LocalGitProjectVersionProvider(target)._root()
        else:
            complete = False
        return self._receipt(scope, files) if complete else None

    def create(
        self, scope: ProvisionScope, files: tuple[ProvisionFile, ...]
    ) -> LocalProvisionReceipt:
        target = self._scope(scope)
        marker = self._marker(scope, files)
        self._require_lock(scope)
        existing = self.inspect(scope, files)
        if existing is not None:
            return existing
        if not target.exists():
            target.mkdir()
            (target / ".researchos").mkdir()
            self._atomic(target / MARKER, marker, target / ".researchos")
        state = target / ".researchos"
        for file in files:
            self._atomic(target / file.path, file.content.encode("utf-8"), state)
        if not (target / ".git").exists():
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith("GIT_")
            }
            environment.update(
                {
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_TERMINAL_PROMPT": "0",
                }
            )
            try:
                result = subprocess.run(
                    [
                        "git",
                        "-c",
                        "core.hooksPath=" + os.devnull,
                        "-c",
                        "init.templateDir=",
                        "-C",
                        str(target),
                        "init",
                        "-b",
                        "main",
                    ],
                    capture_output=True,
                    env=environment,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise DomainError(
                    "PROJECT_PROVISIONING_GIT_UNAVAILABLE",
                    "Independent Git initialization could not complete",
                    503,
                ) from None
            if result.returncode:
                raise DomainError(
                    "PROJECT_PROVISIONING_GIT_UNAVAILABLE",
                    "Independent Git initialization could not complete",
                    503,
                )
        receipt = self.inspect(scope, files)
        if receipt is None:
            raise _fail()
        return receipt

    def bind_repository(
        self, scope: ProvisionScope, repository: GitHubPrivateRepository
    ) -> LocalProvisionReceipt:
        target = self._scope(scope)
        self._require_lock(scope)
        repository = _repository(asdict(repository))
        if (
            repository.owner_login.casefold() != scope.github_owner.casefold()
            or repository.owner_id != scope.github_owner_id
            or repository.name.casefold() != scope.repository_name.casefold()
        ):
            raise _fail()
        marker = _decode(_bytes(target / MARKER))
        if marker.get("scope") != asdict(scope):
            raise _fail()
        context = _decode(_bytes(target / CONTEXT))
        name = context.get("name")
        if not isinstance(name, str):
            raise _fail()
        frozen = self.plan_files(scope.project_id, name)
        receipt = self.inspect(scope, frozen)
        if receipt is None:
            raise _fail()
        state = target / ".git/researchos"
        state.mkdir(exist_ok=True)
        self._atomic(
            state / "binding.json",
            _json({"project_id": scope.project_id, "repository": asdict(repository)}),
            state,
        )
        return receipt

    @contextmanager
    def exclusive(self, scope: ProvisionScope) -> Iterator[None]:
        self._scope(scope)
        if self._locked_project is not None:
            raise DomainError(
                "PROJECT_PROVISIONING_BUSY", "Another initialization owns this provider lock", 409
            )
        directory = self.root / ".researchos-provisioning-locks"
        _path(directory)
        directory.mkdir(exist_ok=True)
        _path(directory, directory=True)
        target = directory / (uuid.UUID(scope.project_id).hex + ".lock")
        _path(target)
        fd = os.open(target, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        acquired = False
        try:
            _path(target)
            info, observed = os.fstat(fd), target.lstat()
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (
                observed.st_dev,
                observed.st_ino,
            ):
                raise _fail()
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    _unix_lock(fd)
            except OSError:
                raise DomainError(
                    "PROJECT_PROVISIONING_BUSY",
                    "Another initialization holds this project lock",
                    409,
                ) from None
            acquired = True
            if info.st_size == 0:
                os.write(fd, b"\0")
                os.fsync(fd)
            self._locked_project = scope.project_id
            self._scope(scope)
            yield
        finally:
            self._locked_project = None
            if acquired:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    _unix_lock(fd, release=True)
            os.close(fd)
