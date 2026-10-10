"""Verify a blank source distribution without running its application."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


def verify(root: Path) -> int:
    manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    seen: set[str] = set()
    for entry in manifest["files"]:
        name = entry["path"]
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or ":" in name
            or name in seen
        ):
            raise ValueError("Invalid manifest path")
        seen.add(name)
        target = root.joinpath(*path.parts)
        for ancestor in [target, *target.parents]:
            if ancestor == root.parent:
                break
            if ancestor.is_symlink() or ancestor.is_junction():
                raise ValueError("Linked package resource refused")
        raw = target.read_bytes()
        if (
            len(raw) != entry["bytes"]
            or hashlib.sha256(raw).hexdigest() != entry["sha256"]
        ):
            raise ValueError(f"Package resource changed: {name}")
    return len(seen)


if __name__ == "__main__":
    count = verify(Path(__file__).resolve().parents[1])
    print(
        f"Verified {count} distribution files. This is a source-integrity check, not a service check."
    )
