import asyncio
import hashlib
import os
import re
import stat
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

from app.domain.storage import StorageReader, StorageStat, StoredObject
from app.errors import DomainError


class _LocalStorageReader:
    def __init__(self, file: BinaryIO, size_bytes: int) -> None:
        self.file = file
        self.size_bytes = size_bytes
        self.used = False

    async def iter_bytes(self, *, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]:
        if self.file.closed:
            raise DomainError("STORAGE_READ_FAILED", "Storage reader is closed", 503)
        if self.used:
            raise DomainError(
                "STORAGE_READ_FAILED", "Storage reader can only be consumed once", 503
            )
        stop = self.size_bytes if end is None else end
        if not 0 <= start <= stop <= self.size_bytes:
            raise DomainError("VALIDATION_ERROR", "Invalid storage byte range", 422)
        self.used = True
        try:
            await asyncio.to_thread(self.file.seek, start)
            remaining = stop - start
            while remaining:
                chunk = await asyncio.to_thread(self.file.read, min(128 * 1024, remaining))
                if not chunk:
                    raise DomainError(
                        "STORAGE_OBJECT_CHANGED", "Stored object changed during reading", 409
                    )
                remaining -= len(chunk)
                yield chunk
        except OSError as exc:
            raise DomainError(
                "STORAGE_READ_FAILED", "Stored object could not be read", 503
            ) from exc

    async def close(self) -> None:
        # No await gap: cancellation cannot lose this local descriptor. A read
        # thread holds Python's file lock, so close waits for its bounded read.
        self.file.close()


class LocalStorageProvider:
    provider_key = "local"
    _extensions = {
        "application/pdf": "pdf",
        "application/octet-stream": "bin",
        "text/plain": "txt",
        "text/csv": "csv",
        "application/json": "json",
        "application/zip": "zip",
        "image/png": "png",
        "image/jpeg": "jpg",
    }

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{2}/[0-9a-f]{32}\.(pdf|bin|txt|csv|json|png|jpg|zip)", key):
            raise DomainError("VALIDATION_ERROR", "Invalid storage key", 422)
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise DomainError("VALIDATION_ERROR", "Storage key escapes root", 422)
        return path

    async def save(
        self,
        content: AsyncIterator[bytes],
        *,
        mime_type: str,
        max_bytes: int,
        allow_empty: bool = False,
    ) -> StoredObject:
        extension = self._extensions.get(mime_type)
        if extension is None:
            raise DomainError("VALIDATION_ERROR", "Unsupported storage MIME type", 422)
        if max_bytes <= 0:
            raise DomainError("VALIDATION_ERROR", "Storage size limit must be positive", 422)
        key = f"{uuid.uuid4().hex[:2]}/{uuid.uuid4().hex}.{extension}"
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, delete=False)
        temp_path = Path(temporary.name)
        hasher = hashlib.sha256()
        size = 0
        magic = bytearray()
        try:
            async for chunk in content:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise DomainError("FILE_TOO_LARGE", "File exceeds configured size limit", 413)
                if len(magic) < 8:
                    magic.extend(chunk[: 8 - len(magic)])
                hasher.update(chunk)
                await asyncio.to_thread(temporary.write, chunk)
            if mime_type == "application/pdf" and not magic.startswith(b"%PDF-"):
                raise DomainError("INVALID_PDF", "Uploaded file is not a PDF", 422)
            if size == 0 and not allow_empty:
                raise DomainError("EMPTY_FILE", "Uploaded artifact is empty", 422)
            if mime_type == "image/png" and magic != b"\x89PNG\r\n\x1a\n":
                raise DomainError("INVALID_IMAGE", "Uploaded file is not a PNG", 422)
            if mime_type == "image/jpeg" and not magic.startswith(b"\xff\xd8\xff"):
                raise DomainError("INVALID_IMAGE", "Uploaded file is not a JPEG", 422)
            if mime_type == "application/zip" and not magic.startswith((b"PK\x03\x04", b"PK\x05\x06")):
                raise DomainError("INVALID_ZIP", "Stored artifact is not a ZIP", 422)
            await asyncio.to_thread(temporary.flush)
            await asyncio.to_thread(temporary.close)
            os.replace(temp_path, target)
            return StoredObject(
                key=key,
                size_bytes=size,
                sha256=hasher.hexdigest(),
                mime_type=mime_type,
            )
        except BaseException:
            temporary.close()
            temp_path.unlink(missing_ok=True)
            raise

    async def open(self, key: str) -> StorageReader:
        path = self._path(key)
        try:
            # Opening and fstat happen before returning a reader, so a missing
            # file is reported before the HTTP response headers are sent.
            if not path.is_file():
                raise DomainError("NOT_FOUND", "Stored object not found", 404)
            file = path.open("rb")
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as exc:
            raise DomainError("NOT_FOUND", "Stored object not found", 404) from exc
        except OSError as exc:
            raise DomainError("STORAGE_UNAVAILABLE", "Stored object is unavailable", 503) from exc
        try:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise DomainError("NOT_FOUND", "Stored object not found", 404)
            return _LocalStorageReader(file, info.st_size)
        except OSError as exc:
            file.close()
            raise DomainError("STORAGE_UNAVAILABLE", "Stored object is unavailable", 503) from exc
        except BaseException:
            file.close()
            raise

    async def stat(self, key: str) -> StorageStat:
        reader = await self.open(key)
        try:
            return StorageStat(key=key, size_bytes=reader.size_bytes)
        finally:
            await reader.close()

    async def load(
        self, key: str, *, start: int = 0, end: int | None = None
    ) -> AsyncIterator[bytes]:
        reader = await self.open(key)
        try:
            async for chunk in reader.iter_bytes(start=start, end=end):
                yield chunk
        finally:
            await reader.close()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    async def list(self, prefix: str = "") -> list[str]:
        if prefix and not re.fullmatch(r"[0-9a-f]{0,2}", prefix):
            raise DomainError("VALIDATION_ERROR", "Invalid storage prefix", 422)
        return [
            path.relative_to(self.root).as_posix()
            for path in self.root.glob(f"{prefix}*/*")
            if path.is_file()
            and re.fullmatch(
                r"[0-9a-f]{2}/[0-9a-f]{32}\.(pdf|bin|txt|csv|json|png|jpg|zip)",
                path.relative_to(self.root).as_posix(),
            )
        ]

    def get_url(self, key: str) -> str:
        self._path(key)
        return f"/api/v1/storage/{key}"
