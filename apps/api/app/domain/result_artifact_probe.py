"""Readonly evidence for one explicitly approved output artifact."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class FileProbeReceipt:
    status: Literal["VERIFIED", "MISSING", "CHANGED", "UNAVAILABLE", "UNSAFE_PATH"]
    actual_sha256: str | None = None
    actual_size_bytes: int | None = None


class ResultArtifactProbe(Protocol):
    def inspect(
        self, output_root: Path, relative_path: str, expected_sha256: str, expected_size_bytes: int
    ) -> FileProbeReceipt: ...
