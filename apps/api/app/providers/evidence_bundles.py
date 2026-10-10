"""Deterministic text-only writing materials, retaining raw source facts and gaps."""

import hashlib
import io
import json
import zipfile
from typing import Any

from app.domain.evidence_bundles import (
    EvidenceFile,
    RenderedEvidenceBundle,
    evidence_payloads,
    json_text,
)

MAX_BUNDLE_BYTES = 4 * 1024 * 1024
FIXED = {
    "README.md",
    "claims.md",
    "evidence.json",
    "metrics.csv",
    "references.bib",
    "references.json",
    "manifest.json",
    "SHA256SUMS",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class TextEvidenceBundleRenderer:
    def render(self, snapshot: dict[str, Any]) -> RenderedEvidenceBundle:
        texts = evidence_payloads(snapshot)
        files = [
            EvidenceFile(path, value, sha(value.encode()), len(value.encode()))
            for path, value in texts.items()
        ]
        sums = "".join(f"{f.sha256}  {f.path}\n" for f in sorted(files, key=lambda f: f.path))
        files.append(EvidenceFile("SHA256SUMS", sums, sha(sums.encode()), len(sums.encode())))
        manifest = {
            "contract": "researchos-evidence-bundle-v1",
            "snapshot_sha256": sha(
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ),
            "source_artifact_bytes_included": False,
            "execution_authorized": False,
            "files": [
                {"path": f.path, "sha256": f.sha256, "size_bytes": f.size_bytes}
                for f in sorted(files, key=lambda f: f.path)
            ],
        }
        value = json_text(manifest)
        files.append(EvidenceFile("manifest.json", value, sha(value.encode()), len(value.encode())))
        return self.pack(tuple(files))

    def pack(self, files: tuple[EvidenceFile, ...]) -> RenderedEvidenceBundle:
        if {f.path for f in files} != FIXED or len(files) != len(FIXED):
            raise ValueError("Evidence bundle fixed files differ")
        if sum(f.size_bytes for f in files) > MAX_BUNDLE_BYTES:
            raise ValueError("Evidence bundle exceeds 4 MiB; nothing was truncated")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            for f in sorted(files, key=lambda f: f.path):
                raw = f.content.encode()
                if len(raw) != f.size_bytes or sha(raw) != f.sha256:
                    raise ValueError("Frozen evidence file hash differs")
                info = zipfile.ZipInfo(f.path, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, raw)
        raw = buffer.getvalue()
        if len(raw) > MAX_BUNDLE_BYTES:
            raise ValueError("Evidence ZIP exceeds 4 MiB")
        return RenderedEvidenceBundle(
            tuple(sorted(files, key=lambda f: f.path)), raw, sha(raw), len(raw)
        )
