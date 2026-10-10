"""Bounded UTF-8 I/O with real handle fences; never executes code or Git.

The caller supplies a trusted archive-binding root and owns authorization, frozen
before bytes and attempt records. It never enumerates or creates selected-code
directories; only the fixed .git/researchos control directory may be initialized.
Windows holds every ancestor against rename and rejects reparse points. POSIX
uses descriptor-relative O_NOFOLLOW traversal. The advisory byte lock coordinates
with the archive worker; it cannot constrain unrelated editors on POSIX.
"""

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, cast

from app.domain.code_changes import (
    MAX_CODE_FILE_BYTES,
    MAX_CODE_FILES,
    MAX_CODE_TOTAL_BYTES,
    CodeFileChange,
    CodeFileReceipt,
    CodeFileSnapshot,
)
from app.errors import DomainError

_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".ts", ".tsx", ".js", ".jsx", ".css", ".html"}
_PRIVATE = {"data", "dataset", "datasets", "cache", "caches", "weights", "checkpoint", "checkpoints", "uploads", "attachments", "private", "secrets", "credentials", "logs", "runtime", "backups", "node_modules", "venv", "env", "notes", "__pycache__"}
_DEVICES = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"} | {f"{p}{i}" for p in ("COM", "LPT") for i in (*range(1, 10), "¹", "²", "³")}
_MARKER = (".git", "researchos", "code-change-active.json")
_SECRET = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b")
_SECRET_FIELD = r"(?:[A-Za-z_]\w*_)?(?:token|password|passwd|secret|api_key|apikey)"
_SECRET_QUOTED = re.compile(rf"(?im)^[ \t]*[\"']?{_SECRET_FIELD}[\"']?[ \t]*[:=][ \t]*[\"']([^\"'\r\n]+)[\"']")
_SECRET_ASSIGNED = re.compile(rf"(?im)^[ \t]*[\"']?{_SECRET_FIELD}[\"']?[ \t]*[:=][ \t]*[\"']?([^\r\n\"'#;,]+)")
_PLACEHOLDERS = {"replace_with_secret", "your_api_key_here", "replace_me_with_secret", "your_token_here", "your_password_here", "changeme", "placeholder", "researchos-test-only-not-a-credential", "researchos_test_only_not_a_credential"}


def _scan_text(text: str) -> None:
    """Same conservative literal policy as archives, with no process dependency.

    Pattern screening cannot prove arbitrary code contains no secret. Never
    redact: a flagged file cannot be silently changed before approval.
    """
    if _SECRET.search(text):
        raise _error("CODE_FILE_POSSIBLE_SECRET", "Selected code text contains a possible credential and needs owner cleanup")
    for expression, minimum in ((_SECRET_QUOTED, 1), (_SECRET_ASSIGNED, 16)):
        for match in expression.finditer(text):
            value = match.group(1).strip()
            if re.fullmatch(r"[A-Za-z0-9_+/=-]{" + str(minimum) + r",}", value) and value.casefold() not in _PLACEHOLDERS:
                raise _error("CODE_FILE_POSSIBLE_SECRET", "Selected code text contains a possible credential and needs owner cleanup")


class _UnixLocks(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int) -> None: ...


def _unix_lock(fd: int, *, release: bool = False) -> None:
    import fcntl
    locks = cast(_UnixLocks, fcntl)
    locks.flock(fd, locks.LOCK_UN if release else locks.LOCK_EX | locks.LOCK_NB)


def _posix_flag(name: str) -> int:
    # Missing security flags are never replaced by zero.
    value: object = getattr(os, name)
    if not isinstance(value, int):
        raise _error()
    return value


def _error(code: str = "CODE_FILE_UNSAFE", message: str = "Selected code file failed safe filesystem verification") -> DomainError:
    return DomainError(code, message, 409)


def validate_code_path(value: str) -> tuple[str, ...]:
    parts = value.split("/")
    if not value or len(value) > 1000 or len(parts) > 32:
        raise _error()
    for part in parts:
        if (not part or part.startswith(".") or len(part) > 255 or part.endswith((".", " "))
            or any(c in part for c in '<>:"\\|?*') or any(ord(c) < 32 or ord(c) == 127 for c in part)
            or part.casefold() in _PRIVATE or part.split(".")[0].upper() in _DEVICES
            or re.search(r"(?:^|[_.-])(?:credential|secret|password|token)s?(?:[_.-]|$)", part, re.I)):
            raise _error()
    if Path(parts[-1]).suffix.lower() not in _EXTENSIONS:
        raise _error()
    return tuple(parts)


def _bytes(text: str) -> bytes:
    try:
        value = text.encode("utf-8")
    except UnicodeError:
        raise _error("CODE_FILE_ENCODING", "Code changes must be valid UTF-8") from None
    if b"\0" in value or len(value) > MAX_CODE_FILE_BYTES:
        raise _error("CODE_FILE_LIMIT", "Code files must be UTF-8 text no larger than 256 KiB")
    _scan_text(text)
    return value


def _regular(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
        raise _error()


def _read_fd(fd: int) -> bytes:
    initial = os.fstat(fd)
    _regular(initial)
    os.lseek(fd, 0, os.SEEK_SET)
    content = bytearray()
    while len(content) <= MAX_CODE_FILE_BYTES:
        chunk = os.read(fd, min(65536, MAX_CODE_FILE_BYTES + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
    final = os.fstat(fd)
    _regular(final)
    if (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns, initial.st_ctime_ns) != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns, final.st_ctime_ns):
        raise _error("CODE_FILE_CHANGED", "Selected file changed during bounded read")
    if len(content) > MAX_CODE_FILE_BYTES or b"\0" in content:
        raise _error("CODE_FILE_LIMIT", "Code file exceeds the bounded text limit")
    try:
        bytes(content).decode("utf-8")
    except UnicodeError:
        raise _error("CODE_FILE_ENCODING", "Selected file is not UTF-8 text") from None
    return bytes(content)


def _windows_open(path: Path, *, directory: bool, write: bool = False, create: bool = False, delete: bool = False) -> int:
    # Delay imports: the adapter also runs on POSIX, with no Win32 dependencies.
    import ctypes
    import msvcrt
    from ctypes import wintypes

    library = ctypes.WinDLL("kernel32", use_last_error=True)
    function = library.CreateFileW
    function.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    function.restype = wintypes.HANDLE
    close = library.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    access = 0x80000000 | (0x40000000 if write else 0) | (0x10000 if delete else 0)
    # Directories allow metadata/content writes but NEVER rename/delete. Read-only
    # leaf denies writers; write leaf excludes every other open handle.
    sharing = 3 if directory else (0 if write else 1)
    handle = function(str(path), access, sharing, None, 1 if create else 3, 0x00200000 | (0x02000000 if directory else 0), None)
    if handle == wintypes.HANDLE(-1).value:
        number = ctypes.get_last_error()
        if number in (2, 3):
            raise FileNotFoundError(str(path))
        raise OSError(number, "Safe code-file handle could not be opened")
    try:
        fd = msvcrt.open_osfhandle(int(handle), (os.O_RDWR if write else os.O_RDONLY) | os.O_BINARY)
    except BaseException:
        close(handle)
        raise
    info = os.fstat(fd)
    if getattr(info, "st_file_attributes", 0) & 0x400 or (directory and not stat.S_ISDIR(info.st_mode)):
        os.close(fd)
        raise _error()
    return fd


class LocalCodeFileProvider:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or ".." in root.parts:
            raise _error()
        self.root = root
        self._locked = False
        self._root_fd: int | None = None
        self._applied: dict[str, int] = {}
        self._active: tuple[str, str, str] | None = None

    @contextmanager
    def _parents(self, parts: tuple[str, ...], *, root: bool = False) -> Iterator[tuple[int, Path]]:
        fds: list[int] = []
        identities: list[tuple[Path, int, int]] = []
        try:
            if root:
                path = Path(self.root.anchor)
                ancestry = self.root.parts[1:]
                fd = _windows_open(path, directory=True) if os.name == "nt" else os.open(path, os.O_RDONLY | _posix_flag("O_DIRECTORY") | _posix_flag("O_NOFOLLOW"))
            else:
                if self._root_fd is None:
                    raise _error("CODE_FILE_LOCK_REQUIRED")
                path, ancestry, fd = self.root, parts[:-1], os.dup(self._root_fd)
            fds.append(fd)
            state = os.fstat(fd)
            identities.append((path, state.st_dev, state.st_ino))
            for part in ancestry:
                path /= part
                fd = _windows_open(path, directory=True) if os.name == "nt" else os.open(part, os.O_RDONLY | _posix_flag("O_DIRECTORY") | _posix_flag("O_NOFOLLOW"), dir_fd=fd)
                if not stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise _error()
                fds.append(fd)
                state = os.fstat(fd)
                identities.append((path, state.st_dev, state.st_ino))
            yield fd, path
            # Descriptor-relative I/O cannot escape into a replacement directory,
            # but must not claim that a detached directory is still the named root.
            for location, device, inode in identities:
                current = location.lstat()
                if not stat.S_ISDIR(current.st_mode) or getattr(current, "st_file_attributes", 0) & 0x400 or (current.st_dev, current.st_ino) != (device, inode):
                    raise _error("CODE_FILE_PATH_CHANGED", "Selected directory identity changed during code-file I/O")
        finally:
            for fd in reversed(fds):
                os.close(fd)

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        if self._locked:
            raise _error("CODE_FILE_BUSY")
        body_failed = False
        try:
            with self._parents((), root=True) as (root_fd, _):
                self._root_fd = root_fd
                # Internal lock path is fixed, never owner-selected. Parents must
                # exist except the fixed control dir for first archive binding.
                with self._parents((".git", "researchos")) as (git_fd, git_path):
                    try:
                        if os.name == "nt":
                            (git_path / "researchos").mkdir()
                        else:
                            os.mkdir("researchos", mode=0o700, dir_fd=git_fd)
                    except FileExistsError:
                        pass
                with self._parents((".git", "researchos", "execution.lock")) as (parent_fd, parent):
                    if os.name == "nt":
                        # Sharing read/write lets msvcrt byte locks coordinate with
                        # the existing archive provider, while rename stays denied.
                        lock_fd = _windows_lock_open(parent / "execution.lock")
                    else:
                        lock_fd = os.open("execution.lock", os.O_RDWR | os.O_CREAT | _posix_flag("O_NOFOLLOW") | _posix_flag("O_NONBLOCK"), 0o600, dir_fd=parent_fd)
                    acquired = False
                    try:
                        _regular(os.fstat(lock_fd))
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                        else:
                            _unix_lock(lock_fd)
                        acquired = True
                        if os.fstat(lock_fd).st_size == 0:
                            os.write(lock_fd, b"\0")
                            os.fsync(lock_fd)
                        self._locked, self._applied, self._active = True, {}, None
                        try:
                            yield
                        except OSError:
                            body_failed = True
                            raise
                    finally:
                        self._locked = False
                        self._active = None
                        if acquired:
                            os.lseek(lock_fd, 0, os.SEEK_SET)
                            if os.name == "nt":
                                import msvcrt
                                msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                            else:
                                _unix_lock(lock_fd, release=True)
                        os.close(lock_fd)
        except OSError:
            if body_failed:
                raise
            raise _error("CODE_FILE_BUSY", "Project file lock or safe path could not be acquired") from None
        finally:
            self._root_fd = None

    def _require_lock(self) -> None:
        if not self._locked:
            raise _error("CODE_FILE_LOCK_REQUIRED", "Code file I/O requires the exclusive project lock")

    def _marker(self, parent_fd: int, parent: Path) -> dict[str, str] | None:
        try:
            fd = self._open(parent_fd, parent, _MARKER[-1])
        except FileNotFoundError:
            return None
        try:
            if os.fstat(fd).st_size > 4096:
                raise _error("CODE_FILE_PENDING", "Pending code-change marker is invalid and requires reconciliation")
            content = _read_fd(fd)
        finally:
            os.close(fd)
        if len(content) > 4096:
            raise _error("CODE_FILE_PENDING", "Pending code-change marker is invalid and requires reconciliation")
        try:
            value = json.loads(content, object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError):
            raise _error("CODE_FILE_PENDING", "Pending code-change marker is invalid and requires reconciliation") from None
        if not isinstance(value, dict) or set(value) != {"plan_id", "proposal_sha256", "attempt_id"} or any(not isinstance(v, str) for v in value.values()):
            raise _error("CODE_FILE_PENDING")
        if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value[key]) for key in ("plan_id", "attempt_id")) or not re.fullmatch(r"[a-f0-9]{64}", value["proposal_sha256"]):
            raise _error("CODE_FILE_PENDING")
        return cast(dict[str, str], value)

    def assert_no_pending_changes(self) -> None:
        self._require_lock()
        try:
            with self._parents(_MARKER) as (parent_fd, parent):
                if self._marker(parent_fd, parent) is not None:
                    raise _error("CODE_FILE_PENDING", "A previous code change needs reconciliation before another change or archive operation")
        except OSError:
            raise _error("CODE_FILE_PENDING") from None

    def begin(self, plan_id: str, proposal_sha256: str, attempt_id: str) -> None:
        self._require_lock()
        if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) for value in (plan_id, attempt_id)) or not re.fullmatch(r"[a-f0-9]{64}", proposal_sha256):
            raise _error("CODE_FILE_PLAN_INVALID")
        marker = {"plan_id": plan_id, "proposal_sha256": proposal_sha256, "attempt_id": attempt_id}
        content = json.dumps(marker, sort_keys=True, separators=(",", ":")).encode()
        try:
            with self._parents(_MARKER) as (parent_fd, parent):
                current = self._marker(parent_fd, parent)
                if current is not None and (current["plan_id"], current["proposal_sha256"]) != (plan_id, proposal_sha256):
                    raise _error("CODE_FILE_PENDING", "Another approved code change has pending filesystem effects")
                fd = self._open(parent_fd, parent, _MARKER[-1], write=True, create=current is None)
                try:
                    _regular(os.fstat(fd))
                    if current is not None and json.loads(_read_fd(fd)) != current:
                        raise _error("CODE_FILE_PENDING")
                    _write_fd(fd, content)
                    if _read_fd(fd) != content:
                        raise _error("CODE_FILE_PENDING")
                    if current is None and os.name != "nt":
                        os.fsync(parent_fd)
                finally:
                    os.close(fd)
                self._active = plan_id, proposal_sha256, attempt_id
        except OSError:
            raise _error("CODE_FILE_PENDING", "Code-change marker write is unknown; do not apply or archive until reconciled") from None

    def complete(self, plan_id: str, proposal_sha256: str, attempt_id: str) -> None:
        self._require_lock()
        expected = {"plan_id": plan_id, "proposal_sha256": proposal_sha256, "attempt_id": attempt_id}
        try:
            with self._parents(_MARKER) as (parent_fd, parent):
                if self._marker(parent_fd, parent) != expected or self._active != (plan_id, proposal_sha256, attempt_id):
                    raise _error("CODE_FILE_PENDING", "Only the exact current code-change attempt may clear its pending marker")
                if os.name == "nt":
                    fd = _windows_open(parent / _MARKER[-1], directory=False, write=True, delete=True)
                    try:
                        if json.loads(_read_fd(fd)) != expected:
                            raise _error("CODE_FILE_PENDING")
                        _windows_delete_fd(fd)
                    finally:
                        os.close(fd)
                else:
                    fd = self._open(parent_fd, parent, _MARKER[-1], write=True)
                    try:
                        opened = os.fstat(fd)
                        entry = os.stat(_MARKER[-1], dir_fd=parent_fd, follow_symlinks=False)
                        if json.loads(_read_fd(fd)) != expected or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino):
                            raise _error("CODE_FILE_PENDING")
                        os.unlink(_MARKER[-1], dir_fd=parent_fd)
                        os.fsync(parent_fd)
                    finally:
                        os.close(fd)
                self._active = None
        except OSError:
            raise _error("CODE_FILE_PENDING", "Code-change marker cleanup is unknown and requires reconciliation") from None

    def _open(self, parent_fd: int, parent: Path, name: str, *, write: bool = False, create: bool = False) -> int:
        if os.name == "nt":
            return _windows_open(parent / name, directory=False, write=write, create=create)
        flags = (os.O_RDWR if write else os.O_RDONLY) | _posix_flag("O_NOFOLLOW") | _posix_flag("O_NONBLOCK")
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        return os.open(name, flags, 0o600, dir_fd=parent_fd)

    def read(self, paths: tuple[str, ...]) -> tuple[CodeFileSnapshot, ...]:
        self._require_lock()
        if not 1 <= len(paths) <= MAX_CODE_FILES or len({p.casefold() for p in paths}) != len(paths):
            raise _error("CODE_FILE_LIMIT")
        snapshots: list[CodeFileSnapshot] = []
        total = 0
        for path in paths:
            parts = validate_code_path(path)
            try:
                with self._parents(parts) as (parent_fd, parent):
                    try:
                        fd = self._open(parent_fd, parent, parts[-1])
                    except FileNotFoundError:
                        snapshots.append(CodeFileSnapshot(path, False, None, "", 0))
                        continue
                    try:
                        content = _read_fd(fd)
                        entry = (parent / parts[-1]).lstat() if os.name == "nt" else os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                        opened = os.fstat(fd)
                        _regular(entry)
                        if (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino):
                            raise _error("CODE_FILE_CHANGED")
                    finally:
                        os.close(fd)
                    total += len(content)
                    if total > MAX_CODE_TOTAL_BYTES:
                        raise _error("CODE_FILE_LIMIT")
                    _scan_text(content.decode("utf-8"))
                    snapshots.append(CodeFileSnapshot(path, True, hashlib.sha256(content).hexdigest(), content.decode("utf-8"), len(content)))
            except OSError:
                raise _error() from None
        return tuple(snapshots)

    def apply(self, file: CodeFileChange) -> CodeFileReceipt:
        self._require_lock()
        if self._active is None:
            raise _error("CODE_FILE_PLAN_REQUIRED", "A persisted pending marker is required before changing code files")
        with self._parents(_MARKER) as (marker_parent_fd, marker_parent):
            marker = self._marker(marker_parent_fd, marker_parent)
            if marker != dict(zip(("plan_id", "proposal_sha256", "attempt_id"), self._active, strict=True)):
                raise _error("CODE_FILE_PENDING", "Code-change marker changed before file application")
        parts, after = validate_code_path(file.path), _bytes(file.after_text)
        if file.before_sha256 is not None and not re.fullmatch(r"[a-f0-9]{64}", file.before_sha256):
            raise _error("CODE_FILE_BEFORE_INVALID")
        sizes = self._applied | {file.path.casefold(): len(after)}
        if len(sizes) > MAX_CODE_FILES or sum(sizes.values()) > MAX_CODE_TOTAL_BYTES:
            raise _error("CODE_FILE_LIMIT")
        after_sha = hashlib.sha256(after).hexdigest()
        try:
            with self._parents(parts) as (parent_fd, parent):
                try:
                    fd = self._open(parent_fd, parent, parts[-1], write=True)
                except FileNotFoundError:
                    if file.before_sha256 is not None:
                        raise _error("CODE_FILE_CHANGED", "Selected source file no longer matches its approved before SHA") from None
                    fd = self._open(parent_fd, parent, parts[-1], write=True, create=True)
                    before_sha = None
                else:
                    try:
                        before = _read_fd(fd)
                        _scan_text(before.decode("utf-8"))
                    except BaseException:
                        os.close(fd)
                        raise
                    before_sha = hashlib.sha256(before).hexdigest()
                    if before_sha == after_sha:
                        try:
                            self._verify_entry(fd, parent_fd, parent, parts[-1])
                        finally:
                            os.close(fd)
                        self._applied = sizes
                        return CodeFileReceipt(file.path, file.before_sha256, after_sha, len(after), True)
                    if before_sha != file.before_sha256:
                        os.close(fd)
                        raise _error("CODE_FILE_CHANGED", "Selected source file no longer matches its approved before SHA")
                try:
                    _regular(os.fstat(fd))
                    _write_fd(fd, after)
                    if before_sha is None and os.name != "nt":
                        os.fsync(parent_fd)
                    if _read_fd(fd) != after:
                        raise _error("CODE_FILE_WRITE_UNKNOWN", "Written code-file bytes failed readback verification")
                    # POSIX unrelated editors can rename the entry despite dir fd;
                    # report unknown rather than giving a misleading path receipt.
                    self._verify_entry(fd, parent_fd, parent, parts[-1])
                finally:
                    os.close(fd)
                self._applied = sizes
                return CodeFileReceipt(file.path, before_sha, after_sha, len(after), False)
        except OSError:
            raise _error("CODE_FILE_WRITE_UNKNOWN", "Code-file write failed; actual bytes require explicit reconciliation") from None

    def _verify_entry(self, fd: int, parent_fd: int, parent: Path, name: str) -> None:
        leaf = os.stat(name, dir_fd=parent_fd, follow_symlinks=False) if os.name != "nt" else (parent / name).lstat()
        opened = os.fstat(fd)
        _regular(leaf)
        _regular(opened)
        if (leaf.st_dev, leaf.st_ino) != (opened.st_dev, opened.st_ino):
            raise _error("CODE_FILE_WRITE_UNKNOWN")


def _windows_lock_open(path: Path) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    library: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    function = library.CreateFileW
    function.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    function.restype = wintypes.HANDLE
    close = library.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = function(str(path), 0xC0000000, 3, None, 4, 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "Project archive lock unavailable")
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_RDWR | os.O_BINARY)
    except BaseException:
        close(handle)
        raise


def _write_fd(fd: int, content: bytes) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    remaining = memoryview(content)
    while remaining:
        count = os.write(fd, remaining)
        if count <= 0:
            raise OSError("File write made no progress")
        remaining = remaining[count:]
    os.ftruncate(fd, len(content))
    os.fsync(fd)


def _windows_delete_fd(fd: int) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Disposition(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    value = Disposition(True)
    function = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    function.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    function.restype = wintypes.BOOL
    if not function(msvcrt.get_osfhandle(fd), 4, ctypes.byref(value), ctypes.sizeof(value)):
        raise OSError(ctypes.get_last_error(), "Pending code-change marker could not be removed")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate marker field")
        value[key] = item
    return value
