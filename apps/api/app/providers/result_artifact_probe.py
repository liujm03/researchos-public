"""Bounded, stable file hashing; never exposes output text or filesystem errors."""

import hashlib
import os
import re
import stat
from pathlib import Path, PurePosixPath

from app.domain.result_artifact_probe import FileProbeReceipt

MAX_NOTE_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"} | {
    prefix + suffix
    for prefix in ("COM", "LPT")
    for suffix in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "¹", "²", "³")
}


class _UnsafePath(Exception):
    pass


class LocalResultArtifactProbe:
    @staticmethod
    def _path(output_root: Path, relative_path: str) -> Path:
        if (
            not output_root.is_absolute()
            or ".." in output_root.parts
            or not isinstance(relative_path, str)
            or not relative_path
            or len(relative_path) > 2000
            or "\\" in relative_path
            or ":" in relative_path
            or any(ord(character) < 32 or ord(character) == 127 for character in relative_path)
        ):
            raise _UnsafePath
        relative = PurePosixPath(relative_path)
        if (
            relative.is_absolute()
            or relative.as_posix() != relative_path
            or any(
                part in {".", ".."}
                or part.endswith((".", " "))
                or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED
                or any(character in '<>"|?*' for character in part)
                for part in relative.parts
            )
        ):
            raise _UnsafePath
        target = output_root / relative_path
        if not target.is_relative_to(output_root):
            raise _UnsafePath
        return target

    @staticmethod
    def _record(info: os.stat_result, *, leaf: bool) -> tuple[int, int, int, int, int, int]:
        # Windows lstat/fstat disagree on ctime's creation/write interpretation.
        return (
            info.st_dev,
            info.st_ino,
            info.st_size if leaf else 0,
            info.st_mtime_ns if leaf else 0,
            info.st_ctime_ns if leaf and os.name != "nt" else 0,
            info.st_mode,
        )

    def _chain(self, target: Path) -> tuple[tuple[int, int, int, int, int, int], ...]:
        records = []
        # Inspect ancestors first so a missing leaf cannot conceal an unsafe link.
        for path in reversed((target, *target.parents)):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise _UnsafePath
            if path != target and not stat.S_ISDIR(info.st_mode):
                raise _UnsafePath
            if path == target and not stat.S_ISREG(info.st_mode):
                raise _UnsafePath
            records.append(self._record(info, leaf=path == target))
        return tuple(records)

    def inspect(
        self, output_root: Path, relative_path: str, expected_sha256: str, expected_size_bytes: int
    ) -> FileProbeReceipt:
        if (
            not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
            or type(expected_size_bytes) is not int
            or not 0 <= expected_size_bytes <= MAX_NOTE_BYTES
        ):
            return FileProbeReceipt("UNAVAILABLE")
        try:
            target = self._path(output_root, relative_path)
            before = self._chain(target)
            if before[-1][2] > MAX_NOTE_BYTES:
                if self._chain(target) != before:
                    return FileProbeReceipt("UNAVAILABLE")
                return FileProbeReceipt("CHANGED", actual_size_bytes=before[-1][2])
            fd = os.open(
                target, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            with os.fdopen(fd, "rb") as stream:
                if (
                    self._record(os.fstat(stream.fileno()), leaf=True) != before[-1]
                    or self._chain(target) != before
                ):
                    return FileProbeReceipt("UNAVAILABLE")
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = stream.read(min(READ_CHUNK_BYTES, MAX_NOTE_BYTES + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_NOTE_BYTES:
                        # The file grew beyond the size observed before opening.
                        return FileProbeReceipt("UNAVAILABLE")
                    digest.update(chunk)
                if (
                    self._record(os.fstat(stream.fileno()), leaf=True) != before[-1]
                    or self._chain(target) != before
                    or size != before[-1][2]
                ):
                    return FileProbeReceipt("UNAVAILABLE")
            actual = digest.hexdigest()
            return FileProbeReceipt(
                "VERIFIED"
                if (actual, size) == (expected_sha256, expected_size_bytes)
                else "CHANGED",
                actual,
                size,
            )
        except _UnsafePath:
            return FileProbeReceipt("UNSAFE_PATH")
        except FileNotFoundError:
            return FileProbeReceipt("MISSING")
        except (OSError, ValueError, UnicodeError):
            return FileProbeReceipt("UNAVAILABLE")
