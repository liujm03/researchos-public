"""Win32 same-handle deletion inside a fixed, server-approved generated-file root.

Every ancestor is held without FILE_SHARE_DELETE. The leaf denies all other
readers/writers/deleters, is opened with OPEN_REPARSE_POINT and DELETE access,
and its verified handle is used for FileDispositionInfo. There is no pathname
unlink, recursive deletion, shell, recycle copy or weak POSIX fallback.
"""

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.domain.generated_file_deletion import (
    MAX_GENERATED_FILE_BYTES,
    GeneratedFileDeletionReceipt,
    GeneratedFileKind,
    GeneratedFileSnapshot,
)
from app.errors import DomainError

_DEVICES = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in (*range(1, 10), "¹", "²", "³")
}
_SHA = re.compile(r"[a-f0-9]{64}")
_STORAGE_KEY = re.compile(r"[a-f0-9]{2}/[a-f0-9]{32}\.txt")
_REVISION = re.compile(r"\.researchos-revisions/([a-f0-9]{2})/([a-f0-9]{64})\.md")


def _error(code: str = "GENERATED_FILE_UNSAFE", message: str = "Generated file failed safe filesystem verification", status: int = 409) -> DomainError:
    return DomainError(code, message, status)


def validate_generated_file_path(value: str, kind: GeneratedFileKind) -> tuple[str, ...]:
    """Only relative Unicode Markdown paths or the local opaque TXT storage key."""
    if kind not in ("markdown", "storage"):
        raise _error(status=422)
    if kind == "storage":
        if not _STORAGE_KEY.fullmatch(value):
            raise _error(status=422)
        return tuple(value.split("/"))
    revision = _REVISION.fullmatch(value)
    if revision is not None:
        if revision[1] != revision[2][:2]:
            raise _error(status=422)
        return tuple(value.split("/"))
    parts = value.split("/")
    if not value or len(value) > 1000 or len(parts) > 32:
        raise _error(status=422)
    for part in parts:
        if (not part or part.startswith(".") or len(part) > 255 or part.endswith((".", " "))
            or any(character in part for character in '<>:"\\|?*')
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            or part.split(".")[0].upper() in _DEVICES):
            raise _error(status=422)
    if Path(parts[-1]).suffix.casefold() != ".md":
        raise _error(status=422)
    return tuple(parts)


def _windows_open(path: Path, *, directory: bool, delete: bool = False) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    library = ctypes.WinDLL("kernel32", use_last_error=True)
    create = library.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = library.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    access = 0x80000000 | (0x00010000 if delete else 0)
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = create(str(path), access, 3 if directory else 0, None, 3, flags, None)
    if handle == wintypes.HANDLE(-1).value:
        number = ctypes.get_last_error()
        if number in (2, 3):
            raise FileNotFoundError(str(path))
        raise OSError(number, "Safe generated-file handle could not be opened")
    try:
        descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close(handle)
        raise
    try:
        info = os.fstat(descriptor)
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise _error()
        if directory and not stat.S_ISDIR(info.st_mode):
            raise _error()
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _windows_dispose(descriptor: int) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Disposition(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    value = Disposition(True)
    dispose = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    dispose.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    dispose.restype = wintypes.BOOL
    if not dispose(msvcrt.get_osfhandle(descriptor), 4, ctypes.byref(value), ctypes.sizeof(value)):
        raise OSError(ctypes.get_last_error(), "Verified generated-file handle could not be deleted")


def _regular(info: os.stat_result) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
        or getattr(info, "st_file_attributes", 0) & 0x400):
        raise _error()
    if info.st_size > MAX_GENERATED_FILE_BYTES:
        raise _error("GENERATED_FILE_LIMIT", "Generated text exceeds the 1 MiB deletion bound")


def _read_verified(descriptor: int) -> tuple[str, int]:
    before = os.fstat(descriptor)
    _regular(before)
    os.lseek(descriptor, 0, os.SEEK_SET)
    content = bytearray()
    while len(content) <= MAX_GENERATED_FILE_BYTES:
        chunk = os.read(descriptor, min(65536, MAX_GENERATED_FILE_BYTES + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
    after = os.fstat(descriptor)
    _regular(after)
    def identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if identity(before) != identity(after) or len(content) != after.st_size:
        raise _error("GENERATED_FILE_CHANGED", "Generated file changed during verification")
    if len(content) > MAX_GENERATED_FILE_BYTES or b"\0" in content:
        raise _error("GENERATED_FILE_LIMIT", "Generated file is not bounded text")
    try:
        content.decode("utf-8")
    except UnicodeError:
        raise _error("GENERATED_FILE_UNSAFE", "Generated file is not valid UTF-8 text") from None
    return hashlib.sha256(content).hexdigest(), len(content)


class FixedRootFileDeletionProvider:
    """Never creates a root or derives one from a client-supplied path."""

    def __init__(self, root: Path, kind: GeneratedFileKind = "markdown") -> None:
        if (kind not in ("markdown", "storage") or not root.is_absolute()
            or ".." in root.parts or "." in root.parts):
            raise _error(status=422)
        self.root = root
        self.kind = kind

    @contextmanager
    def _parents(self, parts: tuple[str, ...]) -> Iterator[Path | None]:
        if os.name != "nt":
            raise _error("GENERATED_FILE_UNSUPPORTED", "Safe permanent file deletion is currently supported only on Windows", 503)
        if not re.fullmatch(r"[A-Za-z]:\\", self.root.anchor):
            raise _error()
        descriptors: list[int] = []
        path = Path(self.root.anchor)
        try:
            descriptors.append(_windows_open(path, directory=True))
            for part in self.root.parts[1:]:
                path /= part
                descriptors.append(_windows_open(path, directory=True))
            for part in parts[:-1]:
                path /= part
                try:
                    descriptors.append(_windows_open(path, directory=True))
                except FileNotFoundError:
                    yield None
                    return
            yield path
        except OSError:
            raise _error("GENERATED_FILE_UNAVAILABLE", "Generated file parent or exclusive handle is unavailable", 503) from None
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def inspect(self, relative_path: str) -> GeneratedFileSnapshot:
        parts = validate_generated_file_path(relative_path, self.kind)
        with self._parents(parts) as parent:
            if parent is None:
                return GeneratedFileSnapshot(relative_path, False, None, 0)
            try:
                descriptor = _windows_open(parent / parts[-1], directory=False)
            except FileNotFoundError:
                return GeneratedFileSnapshot(relative_path, False, None, 0)
            try:
                digest, size = _read_verified(descriptor)
                return GeneratedFileSnapshot(relative_path, True, digest, size)
            finally:
                os.close(descriptor)

    def delete_verified(self, relative_path: str, expected_sha256: str) -> GeneratedFileDeletionReceipt:
        parts = validate_generated_file_path(relative_path, self.kind)
        if not _SHA.fullmatch(expected_sha256):
            raise _error("GENERATED_FILE_HASH_INVALID", "An approved SHA-256 is required", 422)
        revision = _REVISION.fullmatch(relative_path)
        if revision is not None and revision[2] != expected_sha256:
            raise _error("GENERATED_FILE_CHANGED", "Revision filename differs from the approved SHA-256")
        with self._parents(parts) as parent:
            if parent is None:
                return GeneratedFileDeletionReceipt(relative_path, "ALREADY_ABSENT", expected_sha256, 0)
            try:
                descriptor = _windows_open(parent / parts[-1], directory=False, delete=True)
            except FileNotFoundError:
                return GeneratedFileDeletionReceipt(relative_path, "ALREADY_ABSENT", expected_sha256, 0)
            try:
                digest, size = _read_verified(descriptor)
                if digest != expected_sha256:
                    raise _error("GENERATED_FILE_CHANGED", "Generated file differs from the approved SHA-256")
                try:
                    _windows_dispose(descriptor)
                except OSError:
                    raise _error("GENERATED_FILE_DELETE_UNKNOWN", "Deletion outcome needs verification before retry", 503) from None
            finally:
                os.close(descriptor)
            # Confirm name absence while ancestor handles still prevent relocation.
            try:
                replacement = _windows_open(parent / parts[-1], directory=False)
            except FileNotFoundError:
                return GeneratedFileDeletionReceipt(relative_path, "DELETED", digest, size)
            os.close(replacement)
            raise _error("GENERATED_FILE_CHANGED", "Generated file path was recreated after deletion")
