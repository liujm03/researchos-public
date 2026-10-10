"""Bounded in-memory ZIP/JSON parsing. Never extracts files or loads model objects."""

import hashlib
import io
import json
import math
import re
import stat
import zipfile
from typing import Any

from pydantic import ValidationError

from app.domain.server_results import ParsedServerResultArtifact, ParsedServerResultBundle
from app.schemas_server_results import ServerResultEnvelope

MAX_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
SAFE_MIMES = frozenset(
    {
        "application/pdf",
        "application/json",
        "application/octet-stream",
        "text/plain",
        "text/csv",
        "image/png",
        "image/jpeg",
    }
)
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)
_CREDENTIAL_FILE = re.compile(
    r"(?:^|[_.-])(?:credentials?|id_rsa|id_ed25519|auth|secrets?|tokens?|passwords?)(?:[_.-]|$)",
    re.I,
)
_SECRET = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})|"
    r"\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@",
    re.I,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:api[_-]?key|password|secret|access[_-]?token|auth[_-]?token|private[_-]?key)\s*[:=]\s*\S+"
)


def safe_path(path: str) -> None:
    if (
        not path
        or len(path) > 240
        or "\\" in path
        or ":" in path
        or path.startswith("/")
        or any(ord(c) < 32 for c in path)
        or any(c in '<>"|?*' for c in path)
    ):
        raise ValueError("Unsafe artifact path")
    if any(
        part in {"", ".", ".."}
        or part.startswith(".")
        or part.endswith((" ", "."))
        or _RESERVED.match(part)
        or _CREDENTIAL_FILE.search(part)
        for part in path.split("/")
    ):
        raise ValueError("Unsafe or credential artifact path")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _finite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite JSON number")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)
    elif isinstance(value, str) and (_SECRET.search(value) or _SECRET_ASSIGNMENT.search(value)):
        raise ValueError("Receipt contains credential material")


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


class ZipJSONServerResultBundleParser:
    provider_key = "zip_json_v1"

    def parse(self, content: bytes, max_bytes: int = MAX_BYTES) -> ParsedServerResultBundle:
        limit = min(max_bytes, MAX_BYTES)
        if limit <= 0 or not content or len(content) > limit:
            raise ValueError("Result ZIP exceeds byte bound")
        try:
            return self._parse(content, limit)
        except (
            zipfile.BadZipFile,
            RuntimeError,
            UnicodeError,
            ValidationError,
            KeyError,
            TypeError,
            RecursionError,
            OverflowError,
        ) as exc:
            raise ValueError("Invalid server result ZIP or receipt") from exc

    def _parse(self, content: bytes, limit: int) -> ParsedServerResultBundle:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 51 or not members or sum(v.file_size for v in members) > limit:
                raise ValueError("Result ZIP file count or expanded size exceeds bound")
            names: dict[str, zipfile.ZipInfo] = {}
            for member in members:
                if member.orig_filename != member.filename:
                    raise ValueError("ZIP path was normalized or contains NUL")
                safe_path(member.filename)
                mode = member.external_attr >> 16
                if (
                    member.filename.casefold() in names
                    or member.is_dir()
                    or member.flag_bits & 1
                    or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                    or mode & 0o111
                    or member.file_size
                    > (
                        MAX_MANIFEST_BYTES
                        if member.filename == "result_manifest.json"
                        else MAX_ARTIFACT_BYTES
                    )
                    or member.file_size > max(member.compress_size, 1) * 200
                ):
                    raise ValueError("Unsafe, duplicate or oversized ZIP member")
                names[member.filename.casefold()] = member
            manifest = names.get("result_manifest.json")
            if manifest is None or manifest.filename != "result_manifest.json":
                raise ValueError("Missing exact result manifest")
            raw = archive.read(manifest)
            envelope = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
            )
            _finite(envelope)
            ServerResultEnvelope.model_validate(envelope)
            receipt = envelope["receipt"]
            canonical = canonical_json(receipt)
            artifacts: list[ParsedServerResultArtifact] = []
            gaps: list[str] = []
            expected_names = {"result_manifest.json"}
            for declaration in receipt["artifacts"] if "artifacts" in receipt else []:
                path = declaration["path"]
                safe_path(path)
                mime = declaration["mime_type"]
                if mime not in SAFE_MIMES:
                    raise ValueError("Unsupported artifact MIME")
                included = declaration.get("included", True)
                if not isinstance(included, bool):
                    raise ValueError("Artifact included must be boolean")
                entry_name = "artifacts/" + path
                artifact_member = names.get(entry_name.casefold())
                if artifact_member is not None and artifact_member.filename != entry_name:
                    raise ValueError("ZIP member casing differs from declaration")
                if not included:
                    if artifact_member is not None:
                        raise ValueError("Excluded artifact bytes were supplied")
                    verification, data, digest, size = "DECLARED_NOT_INCLUDED", None, None, None
                    gaps.append("ARTIFACT_NOT_INCLUDED:" + path)
                elif artifact_member is None:
                    verification, data, digest, size = "MISSING", None, None, None
                    gaps.append("ARTIFACT_MISSING:" + path)
                else:
                    expected_names.add(entry_name)
                    data = archive.read(artifact_member)
                    size = len(data)
                    digest = hashlib.sha256(data).hexdigest()
                    verification = "BYTES_VERIFIED"
                    if digest != declaration["sha256"] or size != declaration["size_bytes"]:
                        verification = "MISMATCH"
                        gaps.append("ARTIFACT_MISMATCH:" + path)
                artifacts.append(
                    ParsedServerResultArtifact(path, data, mime, digest, size, verification)
                )
            if set(v.filename for v in members) != expected_names:
                raise ValueError("Undeclared ZIP member")
            return ParsedServerResultBundle(
                envelope,
                canonical,
                hashlib.sha256(canonical).hexdigest(),
                hashlib.sha256(content).hexdigest(),
                tuple(artifacts),
                tuple(gaps),
            )
