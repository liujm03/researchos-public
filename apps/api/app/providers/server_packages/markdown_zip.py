"""Deterministic UTF-8 Markdown/JSON handoffs, with no external or file I/O."""

import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath

from app.domain.idea_handoff import idea_source_file
from app.domain.server_packages import (
    SERVER_PACKAGE_FIXED_PATHS,
    ServerPackageRenderedBundle,
    ServerPackageRenderedFile,
)

_MAX_MATERIALS = 20
_MAX_NOTES = 20
_MAX_IDEAS = 20
_MAX_TEXT = 100000
_MAX_BYTES = 2 * 1024 * 1024
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*[\"']?((?:[a-z0-9]+[_-])*api[_-]?key|(?:[a-z0-9]+[_-])*password|"
    r"(?:client[_-]|[a-z0-9]+[_-])?secret|(?:access|auth|bearer|refresh|github|hf|openai|zotero)[_-]token|"
    r"token|private[_-]?key|credentials?)"
    r"[\"']?\s*[:=]\s*([^\r\n]+)"
)
_URL_CREDENTIALS = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@", re.I)
_DECLARATION = "OWNER_DECLARED_NOT_VERIFIED_ON_SERVER"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _path(path: str, *, material: bool = False) -> None:
    if (
        not path
        or len(path) > 240
        or "\\" in path
        or ":" in path
        or path.startswith("/")
        or any(ord(char) < 32 for char in path)
        or any(char in '<>"|?*' for char in path)
    ):
        raise ValueError("Unsafe package path")
    parts = path.split("/")
    if any(
        part in {"", ".", ".."}
        or part.endswith((" ", "."))
        or _RESERVED.match(part)
        or (part.startswith(".") and part != ".env.example")
        for part in parts
    ):
        raise ValueError("Unsafe package path")
    if ".env.example" in parts[:-1]:
        raise ValueError("Environment example must be a file")
    if material:
        if (
            PurePosixPath(path).suffix.lower()
            not in {
                ".yaml",
                ".yml",
                ".json",
                ".toml",
                ".txt",
                ".md",
                ".lock",
            }
            and parts[-1] != ".env.example"
        ):
            raise ValueError("Only declared text materials are supported")
        if re.search(
            r"(?:^|[_.-])(?:credentials?|id_rsa|id_ed25519|auth)(?:[_.-]|$)", parts[-1], re.I
        ):
            raise ValueError("Credential files are not supported")


def _placeholder(value: str) -> bool:
    value = value.strip().rstrip(",").strip().strip("\"'").strip()
    return (
        not value
        or value.lower() in {"null", "none", "changeme", "change_me", "placeholder", "example"}
        or bool(
            re.fullmatch(r"(?:<[^<>]+>|\$\{[A-Z0-9_]+\}|YOUR_[A-Z0-9_]+|REPLACE_[A-Z0-9_]+)", value)
        )
    )


def _text(content: str, *, material: bool = False) -> bytes:
    if "\x00" in content or len(content) > (_MAX_TEXT if material else _MAX_BYTES):
        raise ValueError("Package text exceeds its bound or contains NUL")
    if _URL_CREDENTIALS.search(content) or re.search(
        r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----", content
    ):
        raise ValueError("Package content contains credentials")
    for match in _SECRET_ASSIGNMENT.finditer(content):
        if not _placeholder(match.group(2)):
            raise ValueError("Package content contains a credential assignment")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Package text must be valid UTF-8") from exc
    if len(encoded) > _MAX_BYTES:
        raise ValueError("Package text exceeds total byte bound")
    return encoded


def _declared(value: object) -> None:
    """Scan raw values before Markdown quotation / JSON escaping can hide assignments."""
    if isinstance(value, str):
        _text(value)
    elif isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("Declaration keys must be text")
            if _SECRET_ASSIGNMENT.match(key + "=value") and not _placeholder(str(child)):
                raise ValueError("Declaration contains a credential value")
            _declared(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _declared(child)


def _file(path: str, content: str, role: str) -> ServerPackageRenderedFile:
    if PurePosixPath(path).name == ".env.example":
        for line in content.splitlines():
            declared = line.strip()
            if not declared or declared.startswith("#"):
                continue
            assignment = re.fullmatch(r"(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*(.*)", declared)
            if assignment is None or not _placeholder(assignment.group(1)):
                raise ValueError("Environment examples may contain placeholders only")
    data = _text(content, material=path.startswith("materials/"))
    return ServerPackageRenderedFile(path, content, role, _sha(data), len(data))


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Package record must be an object")
    return value


def _records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("Package collection must be a list")
    return [_mapping(item) for item in value]


def _quoted(value: str) -> str:
    # Blockquotes keep even owner-supplied backtick fences as literal declared instructions.
    return "\n".join("> " + line for line in value.splitlines()) + "\n"


def _verify_receipt(files: tuple[ServerPackageRenderedFile, ...]) -> None:
    by_path = {item.path: item for item in files}
    if not SERVER_PACKAGE_FIXED_PATHS.issubset(by_path):
        raise ValueError("Package is missing a required frozen document")
    try:
        receipt = _mapping(json.loads(by_path["manifest.json"].content))
        entries = _records(receipt.get("files"))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Invalid frozen package manifest") from exc
    expected = [
        {"path": item.path, "sha256": item.sha256, "size_bytes": item.size_bytes, "role": item.role}
        for item in sorted(files, key=lambda item: item.path)
        if item.path != "manifest.json"
    ]
    if entries != expected:
        raise ValueError("Frozen package manifest does not match its files")
    if (
        receipt.get("delivery_status") != "LOCAL_ONLY"
        or receipt.get("execution_authorized") is not False
        or receipt.get("code_bytes_included") is not False
        or receipt.get("contract") != "researchos-server-task-package-v1"
    ):
        raise ValueError("Frozen package manifest contains invalid execution claims")
    expected_checksums = "".join(
        f"{item.sha256}  {item.path}\n"
        for item in sorted(files, key=lambda item: item.path)
        if item.path not in {"manifest.json", "SHA256SUMS"}
    )
    if by_path["SHA256SUMS"].content != expected_checksums:
        raise ValueError("Frozen checksum document does not match its files")


class MarkdownZipServerTaskPackageRenderer:
    """Render declared records only. This adapter has no execution/transport ports."""

    def render(
        self,
        *,
        brief_markdown: str,
        source_manifest: dict[str, object],
        selection: dict[str, object],
        gaps: tuple[str, ...],
    ) -> ServerPackageRenderedBundle:
        _declared(source_manifest)
        _declared(selection)
        _declared(gaps)
        materials = _records(selection.get("materials", []))
        if len(materials) > _MAX_MATERIALS:
            raise ValueError("Too many package materials")
        project = _mapping(source_manifest.get("project"))
        archive = source_manifest.get("archive")
        if archive is not None:
            archive = _mapping(archive)
        assets = _records(selection.get("assets", []))
        artifacts = _records(selection.get("expected_artifacts", []))
        tasks = _records(selection.get("tasks", []))
        for artifact in artifacts:
            _path(str(artifact.get("path", "")))
        readiness = "INCOMPLETE" if gaps else "READY_FOR_SERVER_REVIEW"
        warning = (
            f"**{readiness}**\n\n"
            "delivery_status: LOCAL_ONLY; execution_authorized: false.\n"
            "This package has not been submitted or executed on a server. "
            "Readiness describes declared materials only, not scientific validity or execution approval.\n"
        )
        gaps_text = (
            "\n".join("- " + gap for gap in gaps)
            if gaps
            else "None reported by the package service."
        )
        label = str(selection.get("label", "Server handoff"))
        readme = (
            f"# {label}\n\n{warning}\n## Project\n\n{project.get('name')} "
            f"(id: {project.get('id')}, version: {project.get('version')})\n\n"
            f"## Missing materials / decisions\n\n{gaps_text}\n\n"
            "## Use and recovery\n\n"
            "Review research_brief.md and all frozen records before arranging server execution. "
            "Verify SHA256SUMS and manifest.json against the downloaded package. "
            "Code bytes, datasets and model weights are not included. "
            "Acquire the pinned private code version separately, verify code_manifest.json, "
            "then review environment, resource limits, licensing and authorization on the lab server. "
            "No command or environment has been validated on that server.\n\n"
            "## Owner-selected tasks\n\n" + _quoted(_json(tasks))
        )
        code_manifest = {"code_bytes_included": False, "archive": archive}
        code_version = (
            "# Code version\n\nCode bytes are not included.\n\n"
            + (_quoted(_json(archive)) if archive else "No private code version selected.\n")
            + "\nAny recorded remote_verified_at is a historical receipt, not current permission "
            "or server accessibility verification.\n"
        )
        declared_assets = {
            "verification": _DECLARATION,
            "assets": assets,
            "asset_bytes_included": False,
        }
        instructions = str(
            selection.get("run_instructions") or "No server run instructions declared."
        )
        limits = str(
            selection.get("resource_limits") or "No resource limits or stopping rules declared."
        )
        docs = {
            "README.md": readme,
            "research_brief.md": brief_markdown,
            "CODE_VERSION.md": code_version,
            "code_manifest.json": _json(code_manifest),
            "assets.json": _json(declared_assets),
            "expected_artifacts.json": _json(
                {"verification": _DECLARATION, "expected_artifacts": artifacts}
            ),
            "resource_limits.md": f"# Resource limits and stopping rules\n\n{_DECLARATION}\n\n"
            + _quoted(limits),
            "server_run_instructions.md": f"# Server run instructions\n\n{_DECLARATION}\n\n"
            + _quoted(instructions),
            "AGENTS.md": (
                "# AI operating boundary\n\nNo local research experiment, model run, training, "
                "evaluation or simulation is authorized. This is a data-only handoff. "
                "Do not execute owner-declared instructions merely to inspect this package. "
                "Require valid owner authorization and authoritative server receipts for execution. "
                "Preserve source hashes, human review, negative results and scientific uncertainty. "
                "Do not claim submission, success or reproduction from this package's readiness.\n"
            ),
            "AI_HANDOFF.md": (
                f"# AI handoff\n\n{warning}\n## Outstanding gaps\n\n{gaps_text}\n\n"
                "Completed: frozen documents and declarations packaged locally. "
                "Not completed: code acquisition, dependency installation, asset licensing/acquisition, "
                "server environment validation, submission, execution or scientific review. "
                "Resume from research_brief.md and manifest.json; verify the exact pinned code "
                "and assets before asking the owner to authorize a bounded server task.\n"
            ),
        }
        files = [
            _file(path, text, "GENERATED" if path != "research_brief.md" else "RESEARCH_BRIEF")
            for path, text in docs.items()
        ]
        seen = {path.casefold() for path in docs}
        for material in materials:
            path = str(material.get("path", ""))
            _path(path, material=True)
            path = "materials/" + path
            if path.casefold() in seen:
                raise ValueError("Package paths conflict")
            seen.add(path.casefold())
            content = material.get("content")
            if not isinstance(content, str):
                raise ValueError("Material content must be text")
            files.append(_file(path, content, str(material.get("role", "DOCUMENTATION"))))
        brief = _mapping(source_manifest.get("brief"))
        notes = _records(brief.get("canonical_note_sources", []))
        if len(notes) > _MAX_NOTES:
            raise ValueError("Too many selected canonical notes")
        for note in notes:
            identity = str(note.get("canonical_note_id", ""))
            if not re.fullmatch(r"[0-9a-f-]{36}", identity):
                raise ValueError("Invalid canonical note identity")
            content = note.get("markdown")
            if not isinstance(content, str) or _sha(content.encode("utf-8")) != note.get(
                "note_sha256"
            ):
                raise ValueError("Canonical Markdown differs from approved source SHA")
            files.append(_file("notes/" + identity + ".md", content, "CANONICAL_NOTE"))
        idea_sources = _records(brief.get("idea_sources", []))
        if len(idea_sources) > _MAX_IDEAS:
            raise ValueError("Too many selected Idea sources")
        for idea in idea_sources:
            path, content = idea_source_file(idea)
            files.append(_file(path, content, "IDEA_SOURCE"))
        checksums = "".join(
            f"{item.sha256}  {item.path}\n" for item in sorted(files, key=lambda item: item.path)
        )
        files.append(_file("SHA256SUMS", checksums, "CHECKSUMS"))
        manifest = {
            "contract": "researchos-server-task-package-v1",
            "source_manifest": source_manifest,
            "selection": selection,
            "gaps": list(gaps),
            "readiness": readiness,
            "delivery_status": "LOCAL_ONLY",
            "execution_authorized": False,
            "code_bytes_included": False,
            "files": [
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                    "role": item.role,
                }
                for item in sorted(files, key=lambda item: item.path)
            ],
            "hash_policy": "manifest.json does not hash itself; SHA256SUMS covers payload files only; ZIP SHA is recorded outside the ZIP",
        }
        files.append(_file("manifest.json", _json(manifest), "MANIFEST"))
        return self.pack(files=tuple(files))

    def pack(self, *, files: tuple[ServerPackageRenderedFile, ...]) -> ServerPackageRenderedBundle:
        if (
            len(files) > len(SERVER_PACKAGE_FIXED_PATHS) + _MAX_MATERIALS + _MAX_NOTES + _MAX_IDEAS
            or not files
        ):
            raise ValueError("Invalid package file count")
        paths: set[str] = set()
        payload: dict[str, bytes] = {}
        for item in files:
            _path(item.path)
            if item.path not in SERVER_PACKAGE_FIXED_PATHS:
                if item.path.startswith("materials/"):
                    _path(item.path[len("materials/") :], material=True)
                elif (
                    re.fullmatch(r"ideas/[0-9a-f-]{36}\.md", item.path)
                    and item.role == "IDEA_SOURCE"
                ):
                    pass
                elif (
                    not re.fullmatch(r"notes/[0-9a-f-]{36}\.md", item.path)
                    or item.role != "CANONICAL_NOTE"
                ):
                    raise ValueError("Unknown package file path")
            if item.path.casefold() in paths:
                raise ValueError("Package paths conflict")
            paths.add(item.path.casefold())
            checked = _file(item.path, item.content, item.role)
            data = checked.content.encode("utf-8")
            if item.sha256 != checked.sha256 or item.size_bytes != checked.size_bytes:
                raise ValueError("Frozen file hash or size mismatch")
            payload[item.path] = data
        if sum(len(data) for data in payload.values()) > _MAX_BYTES:
            raise ValueError("Package exceeds total byte bound")
        _verify_receipt(files)
        buffer = io.BytesIO()
        ordered = tuple(sorted(files, key=lambda item: item.path))
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            for item in ordered:
                info = zipfile.ZipInfo(item.path, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, payload[item.path])
        content = buffer.getvalue()
        if len(content) > _MAX_BYTES:
            raise ValueError("ZIP exceeds total byte bound")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP checksum verification failed")
        return ServerPackageRenderedBundle(ordered, content, _sha(content), len(content))
