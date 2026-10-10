"""Standalone stdlib collector. It only reads selected reports/artifacts; never runs research.

Copy this script to the lab server. Report uses receipt wire field names, plus
artifacts[].path/included/mime_type; included files are hashed from artifacts-root.
Excluded files require their declared sha256 and size_bytes in the report.
"""

import argparse
import hashlib
import hmac
import io
import json
import math
import os
import re
import stat
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_BYTES = 32 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_MANIFEST = 512 * 1024
MIMES = {
    "application/pdf",
    "application/json",
    "application/octet-stream",
    "text/plain",
    "text/csv",
    "image/png",
    "image/jpeg",
}
HASH = re.compile(r"[0-9a-f]{64}")
RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)
CREDENTIAL = re.compile(
    r"(?:^|[_.-])(?:credentials?|id_rsa|id_ed25519|auth|secrets?|tokens?|passwords?)(?:[_.-]|$)",
    re.I,
)
SECRET = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})|\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@",
    re.I,
)
SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:api[_-]?key|password|secret|access[_-]?token|auth[_-]?token|private[_-]?key)\s*[:=]\s*\S+"
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safe_path(value: str) -> None:
    if (
        not value
        or len(value) > 240
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or any(ord(c) < 32 or c in '<>"|?*' for c in value)
        or any(
            p in {"", ".", ".."}
            or p.startswith(".")
            or p.endswith((" ", "."))
            or RESERVED.match(p)
            or CREDENTIAL.search(p)
            for p in value.split("/")
        )
    ):
        raise ValueError("Unsafe or credential artifact path")


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def load_json(content: bytes) -> dict[str, Any]:
    value = json.loads(
        content.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant
    )
    if not isinstance(value, dict):
        raise ValueError("Report must be a JSON object")
    return value


def read_bounded(path: Path, limit: int) -> bytes:
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError("Input missing or exceeds byte limit")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("Input identity changed before reading")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = path.stat(follow_symlinks=False)
    if (
        len(data) > limit
        or len(data) != before.st_size
        or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns)
        or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    ):
        raise ValueError("Input exceeded bound or changed during reading")
    return data


def package_facts(content: bytes) -> tuple[str, str]:
    """Recompute the application's exact package preview hash from frozen ZIP files."""
    if len(content) > 2 * 1024 * 1024:
        raise ValueError("Handoff ZIP exceeds its bound")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) > 32 or sum(x.file_size for x in members) > 2 * 1024 * 1024:
            raise ValueError("Handoff ZIP expanded bound")
        names = [v.filename for v in members]
        if len({v.casefold() for v in names}) != len(names):
            raise ValueError("Duplicate handoff member")
        for member in members:
            if member.orig_filename != member.filename:
                raise ValueError("Unsafe normalized handoff path")
            # Handoff templates may contain .env.example; never read them as environment.
            safe_path(member.filename.replace(".env.example", "env-example"))
            mode = member.external_attr >> 16
            if (
                member.is_dir()
                or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                or mode & 0o111
                or member.flag_bits & 1
                or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or member.file_size > max(member.compress_size, 1) * 200
            ):
                raise ValueError("Unsafe handoff member")
        manifest = load_json(archive.read("manifest.json"))
        if (
            manifest.get("contract") != "researchos-server-task-package-v1"
            or manifest.get("execution_authorized") is not False
            or manifest.get("delivery_status") != "LOCAL_ONLY"
        ):
            raise ValueError("Not a ResearchOS local-only handoff")
        declared = {x["path"]: x for x in manifest["files"]}
        if len(declared) != len(manifest["files"]) or set(names) != set(declared) | {
            "manifest.json"
        }:
            raise ValueError("Handoff file manifest mismatch")
        files = []
        for name in sorted(names):
            data = archive.read(name)
            role = "MANIFEST" if name == "manifest.json" else declared[name]["role"]
            if name != "manifest.json" and (
                declared[name]["sha256"] != digest(data)
                or declared[name]["size_bytes"] != len(data)
            ):
                raise ValueError("Handoff file hash mismatch")
            files.append(
                {
                    "path": name,
                    "content": data.decode("utf-8"),
                    "role": role,
                    "sha256": digest(data),
                    "size_bytes": len(data),
                }
            )
        bundle_sha = digest(content)
        preview = {
            "source_sha256": digest(canonical(manifest["source_manifest"])),
            "selection": manifest["selection"],
            "files": files,
            "bundle_sha256": bundle_sha,
            "readiness": manifest["readiness"],
            "gaps": manifest["gaps"],
        }
        return bundle_sha, digest(canonical(preview))


def validate_receipt(receipt: dict[str, Any]) -> None:
    allowed = {
        "contract",
        "receipt_id",
        "server_id",
        "package_id",
        "package_bundle_sha256",
        "package_preview_sha256",
        "claimed_run_status",
        "claimed_job_id",
        "git_commit",
        "protocol_sha256",
        "config_sha256",
        "dataset_sha256",
        "started_at",
        "ended_at",
        "metrics",
        "artifacts",
        "notes",
    }
    if set(receipt) - allowed:
        raise ValueError("Unknown report fields; use documented receipt wire fields")
    if receipt.get("contract") != "researchos-server-result-v1":
        raise ValueError("Invalid result contract")
    if not isinstance(receipt.get("receipt_id"), str) or not 1 <= len(receipt["receipt_id"]) <= 120:
        raise ValueError("Invalid receipt identity")
    uuid.UUID(receipt["package_id"])
    for name in (
        "package_bundle_sha256",
        "package_preview_sha256",
        "protocol_sha256",
        "config_sha256",
        "dataset_sha256",
    ):
        value = receipt.get(name)
        if value is not None and (not isinstance(value, str) or not HASH.fullmatch(value)):
            raise ValueError("Invalid report fingerprint")
    if receipt.get("claimed_run_status") not in {
        "COMPLETED",
        "FAILED",
        "STOPPED",
        "RUNNING",
        "UNKNOWN",
    }:
        raise ValueError("Run status must be an explicit declaration")
    server = receipt.get("server_id")
    if server is not None and (
        not isinstance(server, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", server) is None
    ):
        raise ValueError("Invalid server identity")
    commit = receipt.get("git_commit")
    if commit is not None and (
        not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None
    ):
        raise ValueError("Invalid Git commit declaration")
    dates = []
    for name in ("started_at", "ended_at"):
        value = receipt.get(name)
        when = datetime.fromisoformat(value) if value is not None else None
        if when is not None and when.utcoffset() is None:
            raise ValueError("Run time needs timezone")
        dates.append(when)
    if dates[0] is not None and dates[1] is not None and dates[1] < dates[0]:
        raise ValueError("Run end precedes start")
    for name, maximum in (("claimed_job_id", 160), ("notes", 40000)):
        value = receipt.get(name)
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            raise ValueError("Invalid bounded report text")
    metrics = receipt.get("metrics", [])
    if not isinstance(metrics, list) or len(metrics) > 100:
        raise ValueError("Metric bound exceeded")
    seen = set()
    for metric in metrics:
        if not isinstance(metric, dict) or set(metric) - {
            "name",
            "value",
            "unit",
            "split",
            "evaluation_protocol",
        }:
            raise ValueError("Invalid metric fields")
        value = metric.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Metric must be finite numeric")
        if not isinstance(metric.get("name"), str) or not 1 <= len(metric["name"]) <= 120:
            raise ValueError("Invalid metric name")
        for name, maximum in (("unit", 80), ("split", 80), ("evaluation_protocol", 4000)):
            text = metric.get(name)
            if text is not None and (not isinstance(text, str) or len(text) > maximum):
                raise ValueError("Invalid metric text")
        identity = (metric["name"], metric.get("split"))
        if identity in seen:
            raise ValueError("Duplicate metric identity")
        seen.add(identity)
    if SECRET.search(canonical(receipt).decode("utf-8")):
        raise ValueError("Report contains credential material")
    for text in (receipt.get("notes"), receipt.get("claimed_job_id")):
        if isinstance(text, str) and SECRET_ASSIGNMENT.search(text):
            raise ValueError("Report contains a credential assignment")


def collect(
    *,
    package_zip: Path,
    report: dict[str, Any],
    artifacts_root: Path,
    package_id: str | None = None,
    server_id: str | None = None,
    signing_key: str | None = None,
) -> bytes:
    bundle_sha, preview_sha = package_facts(read_bounded(package_zip, 2 * 1024 * 1024))
    match = re.fullmatch(r"server-task-([0-9a-f-]{36})\.zip", package_zip.name)
    identifier = str(uuid.UUID(package_id or (match.group(1) if match else "")))
    receipt = dict(report)
    for source, destination in (("run_status", "claimed_run_status"), ("job_id", "claimed_job_id")):
        if source in receipt:
            if destination in receipt and receipt[destination] != receipt[source]:
                raise ValueError("Conflicting report declarations")
            receipt[destination] = receipt.pop(source)
    receipt.update(
        contract="researchos-server-result-v1",
        package_id=identifier,
        package_bundle_sha256=bundle_sha,
        package_preview_sha256=preview_sha,
    )
    receipt.setdefault("receipt_id", str(uuid.uuid4()))
    if server_id is not None:
        receipt["server_id"] = server_id
    declarations = report.get("artifacts", [])
    if not isinstance(declarations, list) or len(declarations) > 50:
        raise ValueError("Artifact count exceeds bound")
    root = artifacts_root.absolute()
    if any(parent.is_symlink() or parent.is_junction() for parent in (root, *root.parents)):
        raise ValueError("Artifact root cannot be a link")
    resolved_root = root.resolve(strict=True)
    artifact_bytes: dict[str, bytes] = {}
    collected_size = 0
    artifacts = []
    seen = set()
    for declared in declarations:
        if not isinstance(declared, dict) or set(declared) - {
            "path",
            "mime_type",
            "included",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("Unknown artifact fields")
        path = declared["path"]
        safe_path(path)
        if path.casefold() in seen:
            raise ValueError("Duplicate artifact path")
        seen.add(path.casefold())
        included = declared.get("included", True)
        if not isinstance(included, bool) or declared["mime_type"] not in MIMES:
            raise ValueError("Invalid artifact inclusion or MIME")
        value = dict(declared, included=included)
        if included:
            selected = root
            for component in path.split("/"):
                selected /= component
                if selected.is_symlink() or selected.is_junction():
                    raise ValueError("Selected artifact cannot traverse a link")
            resolved = selected.resolve(strict=True)
            if not resolved.is_relative_to(resolved_root):
                raise ValueError("Artifact escapes declared root")
            if selected.stat().st_mode & 0o111 and os.name != "nt":
                raise ValueError("Executable artifact is unsupported")
            remaining = MAX_BYTES - MAX_MANIFEST - collected_size
            data = read_bounded(selected, min(MAX_FILE, remaining))
            if selected.resolve(strict=True) != resolved or any(
                parent.is_symlink() or parent.is_junction()
                for parent in (selected, *selected.parents)
            ):
                raise ValueError("Selected artifact path changed during reading")
            value.update(sha256=digest(data), size_bytes=len(data))
            collected_size += len(data)
            artifact_bytes["artifacts/" + path] = data
        if (
            not isinstance(value.get("sha256"), str)
            or not HASH.fullmatch(value["sha256"])
            or type(value.get("size_bytes")) is not int
            or not 0 <= value["size_bytes"] <= 2**63 - 1
        ):
            raise ValueError("Excluded artifacts require actual declared hash and size")
        artifacts.append(value)
    receipt["artifacts"] = artifacts
    validate_receipt(receipt)
    if signing_key is not None and (
        len(signing_key.encode("utf-8")) < 32 or not receipt.get("server_id")
    ):
        raise ValueError("Signing needs server identity and at least 32 key bytes")
    signature = (
        hmac.new(signing_key.encode("utf-8"), canonical(receipt), hashlib.sha256).hexdigest()
        if signing_key is not None
        else None
    )
    manifest = canonical({"receipt": receipt, "signature": signature})
    if (
        len(manifest) > MAX_MANIFEST
        or sum(map(len, artifact_bytes.values())) + len(manifest) > MAX_BYTES
    ):
        raise ValueError("Result expanded size exceeds bound")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, data in sorted({"result_manifest.json": manifest, **artifact_bytes}.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    content = output.getvalue()
    if len(content) > MAX_BYTES:
        raise ValueError("Result ZIP exceeds bound")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-zip", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package-id")
    parser.add_argument("--server-id")
    args = parser.parse_args()
    try:
        data = collect(
            package_zip=args.package_zip,
            report=load_json(read_bounded(args.report, MAX_MANIFEST)),
            artifacts_root=args.artifacts_root,
            package_id=args.package_id,
            server_id=args.server_id,
            signing_key=os.environ.get("RESEARCHOS_SERVER_RESULT_HMAC_KEY"),
        )
        # Explicitly refuse overwriting a prior receipt or any input report.
        with args.output.open("xb") as stream:
            stream.write(data)
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, OverflowError) as exc:
        parser.exit(
            2, "Result collection failed: " + type(exc).__name__ + ". Check inputs and bounds.\n"
        )
    print(
        "Saved selected result evidence ZIP; this does not certify execution or scientific conclusions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
