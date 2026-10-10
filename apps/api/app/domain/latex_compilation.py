"""Bounded document compilation port, carrying bytes rather than host file authority."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, Protocol

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PDF_BYTES = 16 * 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024
ISOLATION_CONTRACT = "DOCKER_DOCUMENT_ONLY_V1"
ENGINE = "xelatex"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class LatexSourceFile:
    path: str
    content: bytes
    sha256: str


def source_manifest_sha(files: tuple[LatexSourceFile, ...], entrypoint: str = "main.tex") -> str:
    manifest = {
        "entrypoint": entrypoint,
        "files": [
            {"path": item.path, "sha256": item.sha256, "size_bytes": len(item.content)}
            for item in sorted(files, key=lambda item: item.path)
        ],
    }
    return sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    )


@dataclass(frozen=True)
class LatexCompileRequest:
    files: tuple[LatexSourceFile, ...]
    source_sha256: str
    entrypoint: str = "main.tex"


def validate_request(request: LatexCompileRequest) -> None:
    if request.entrypoint != "main.tex" or not 1 <= len(request.files) <= 50:
        raise ValueError("The fixed entrypoint is main.tex; select 1 to 50 files")
    names: set[str] = set()
    folded: set[str] = set()
    extensions = {
        ".tex",
        ".bib",
        ".bst",
        ".cls",
        ".sty",
        ".png",
        ".jpg",
        ".jpeg",
        ".pdf",
        ".json",
        ".md",
        ".csv",
        ".txt",
    }
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    for item in request.files:
        path = PurePosixPath(item.path)
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,239}", item.path)
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in item.path.split("/"))
            or path.suffix.lower() not in extensions
            or any(part.startswith(".") for part in path.parts)
            or any(part.split(".", 1)[0].upper() in reserved for part in path.parts)
            or item.path in names
            or item.path.casefold() in folded
            or len(item.content) > MAX_FILE_BYTES
            or sha256(item.content) != item.sha256
        ):
            raise ValueError("Source path, byte bound or SHA is invalid")
        names.add(item.path)
        folded.add(item.path.casefold())
    if (
        "main.tex" not in names
        or sum(len(item.content) for item in request.files) > MAX_SOURCE_BYTES
    ):
        raise ValueError("The complete source must contain main.tex and be at most 16 MiB")
    if source_manifest_sha(request.files, request.entrypoint) != request.source_sha256:
        raise ValueError("The frozen source manifest SHA differs")


@dataclass(frozen=True)
class LatexCompilerCapabilities:
    available: bool
    reason: str
    image_id: str | None
    engine: str = ENGINE
    isolation_contract: str = ISOLATION_CONTRACT
    packages: tuple[str, ...] = ("fontspec", "graphicx", "hyperref", "longtable")
    chinese_font: str = "Noto Serif CJK SC"


@dataclass(frozen=True)
class LatexCompileResult:
    status: Literal["READY", "FAILED", "UNAVAILABLE", "TIMED_OUT", "NEEDS_ATTENTION"]
    source_sha256: str
    image_id: str | None
    pdf: bytes | None
    pdf_sha256: str | None
    log: bytes
    log_sha256: str
    exit_code: int | None
    observations: tuple[dict[str, object], ...]
    engine: str = ENGINE
    isolation_contract: str = ISOLATION_CONTRACT


class LatexCompilationProvider(Protocol):
    def probe(self) -> LatexCompilerCapabilities: ...
    def compile(self, request: LatexCompileRequest) -> LatexCompileResult: ...
