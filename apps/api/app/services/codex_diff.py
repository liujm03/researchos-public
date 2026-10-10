"""Bounded, read-only Git patch capture for human review."""

import difflib
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.errors import DomainError

MAX_PATCH_BYTES = 128 * 1024
MAX_SINGLE_PATCH_BYTES = 64 * 1024
MAX_UNTRACKED_BYTES = 32 * 1024
MAX_PATH_LIST_BYTES = 256 * 1024
MAX_FILES = 200
MAX_OMISSION_LINES = 30
SENSITIVE_SUFFIXES = {
    ".key",
    ".pem",
    ".pt",
    ".pth",
    ".ckpt",
    ".p12",
    ".pfx",
    ".onnx",
    ".safetensors",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".zip",
    ".exe",
    ".db",
    ".sqlite",
    ".npy",
}


@dataclass(frozen=True)
class PatchCapture:
    patch: str | None
    truncated: bool
    note: str


def _git_limited(root: Path, args: list[str], limit: int) -> tuple[bytes, bool]:
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if proc.stdout is None:
            raise OSError("Git stdout is unavailable")
        data = proc.stdout.read(limit + 1)
        overflow = len(data) > limit
        if overflow:
            proc.kill()
        code = proc.wait(timeout=10)
        if code != 0 and not overflow:
            raise DomainError("GIT_DIFF_FAILED", "Could not inspect Git changes", 503)
        return data[:limit], overflow
    except (OSError, subprocess.TimeoutExpired) as exc:
        if "proc" in locals() and proc.poll() is None:
            proc.kill()
            proc.wait()
        raise DomainError("GIT_DIFF_FAILED", "Could not inspect Git changes", 503) from exc


def _paths(root: Path, args: list[str]) -> tuple[list[str], bool]:
    raw, overflow = _git_limited(root, args, MAX_PATH_LIST_BYTES)
    chunks = raw.split(b"\x00")
    if chunks and chunks[-1]:
        overflow = True
        chunks = chunks[:-1]
    paths: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        try:
            paths.append(chunk.decode("utf-8"))
        except UnicodeDecodeError:
            overflow = True
    return paths, overflow


def _checked_file(root: Path, rel: str) -> Path | None:
    # Git -z paths are relative to the repository root. Reject drive paths,
    # traversal, control characters, and symlinks before opening any content.
    if not rel or any(ord(ch) < 32 or ord(ch) == 127 for ch in rel):
        return None
    relative = Path(rel)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        return None
    candidate = root / relative
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root.resolve()):
            return None
    except (OSError, ValueError):
        return None
    return candidate


def _sensitive(rel: str) -> bool:
    parts = Path(rel).parts
    lowered = [part.lower() for part in parts]
    name = lowered[-1]
    return (
        ".git" in lowered
        or name == ".env"
        or name.startswith(".env.")
        or any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)
    )


def _ignored(root: Path, rel: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--no-index", "-q", "--", rel],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DomainError("GIT_DIFF_FAILED", "Could not check ignore rules", 503) from exc
    if result.returncode not in (0, 1):
        raise DomainError("GIT_DIFF_FAILED", "Could not check ignore rules", 503)
    return result.returncode == 0


def _new_file_patch(root: Path, rel: str, path: Path) -> tuple[bytes | None, str | None]:
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return None, "not a regular text file"
        if info.st_size > MAX_UNTRACKED_BYTES:
            return None, "new file exceeds per-file size limit"
        if _checked_file(root, rel) != path:
            return None, "path left the workspace"
        with path.open("rb") as stream:
            raw = stream.read(MAX_UNTRACKED_BYTES + 1)
        if len(raw) > MAX_UNTRACKED_BYTES:
            return None, "new file exceeds per-file size limit"
        if b"\x00" in raw:
            return None, "binary file omitted"
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None, "unreadable or non-UTF-8 file"
    header = f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n"
    body = "".join(
        difflib.unified_diff(
            [], text.splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/{rel}"
        )
    )
    encoded = (header + body).encode("utf-8")
    if len(encoded) > MAX_SINGLE_PATCH_BYTES:
        return None, "new file patch exceeds per-file size limit"
    return encoded, None


def capture_review_patch(root: Path, base_commit: str) -> PatchCapture:
    root = root.resolve()
    tracked, tracked_overflow = _paths(
        root,
        [
            "diff",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "--name-only",
            "-z",
            base_commit,
            "--",
        ],
    )
    untracked, untracked_overflow = _paths(
        root, ["ls-files", "--others", "--exclude-standard", "-z"]
    )
    omissions: list[str] = []
    if tracked_overflow or untracked_overflow:
        omissions.append("Git path list exceeded the inspection limit")
    pieces: list[bytes] = []
    used = 0
    inspected = 0
    for rel, is_tracked in [(name, True) for name in tracked] + [
        (name, False) for name in untracked
    ]:
        inspected += 1
        if inspected > MAX_FILES:
            omissions.append("Additional changed files omitted by file-count limit")
            break
        path = _checked_file(root, rel)
        if path is None:
            omissions.append(f"{rel[:160]}: unsafe or escaping path")
            continue
        if _sensitive(rel):
            omissions.append(f"{rel[:160]}: sensitive or binary artifact pattern")
            continue
        if _ignored(root, rel):
            omissions.append(f"{rel[:160]}: ignored by .gitignore")
            continue
        raw: bytes | None
        if is_tracked:
            raw, overflow = _git_limited(
                root,
                [
                    "diff",
                    "--no-renames",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-color",
                    "--patch",
                    base_commit,
                    "--",
                    rel,
                ],
                MAX_SINGLE_PATCH_BYTES,
            )
            if overflow:
                omissions.append(f"{rel[:160]}: tracked patch exceeds per-file size limit")
                continue
            if b"Binary files " in raw or b"GIT binary patch" in raw or b"\x00" in raw:
                omissions.append(f"{rel[:160]}: binary patch omitted")
                continue
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                omissions.append(f"{rel[:160]}: non-UTF-8 patch omitted")
                continue
        else:
            raw, reason = _new_file_patch(root, rel, path)
            if raw is None:
                omissions.append(f"{rel[:160]}: {reason or 'new file omitted'}")
                continue
        if not raw:
            continue
        separator_bytes = 1 if pieces else 0
        if used + separator_bytes + len(raw) > MAX_PATCH_BYTES:
            omissions.append(f"{rel[:160]}: total patch size limit reached")
            continue
        pieces.append(raw)
        used += separator_bytes + len(raw)
    text = b"\n".join(pieces).decode("utf-8") if pieces else None
    note = f"Review patch: {len(pieces)} text file(s), {used} byte(s) captured."
    if omissions:
        shown = omissions[:MAX_OMISSION_LINES]
        note += " Omitted:\n" + "\n".join(f"- {entry}" for entry in shown)
        if len(omissions) > len(shown):
            note += f"\n- {len(omissions) - len(shown)} more omission(s)"
    return PatchCapture(patch=text, truncated=bool(omissions), note=note[:6000])
