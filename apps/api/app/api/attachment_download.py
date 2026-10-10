"""Authenticated attachment HTTP semantics over provider-owned object readers."""

import re
from urllib.parse import quote

import anyio
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.domain.storage import StorageProvider, StorageReader
from app.errors import DomainError
from app.models import Attachment
from app.services.attachment_names import safe_attachment_filename
from app.services.pdf_upload import safe_pdf_filename


class _ClosingStorageResponse(StreamingResponse):
    def __init__(
        self, reader: StorageReader, *, start: int, end: int,
        media_type: str, status_code: int, headers: dict[str, str],
    ) -> None:
        self.reader = reader
        super().__init__(
            reader.iter_bytes(start=start, end=end), media_type=media_type,
            status_code=status_code, headers=headers,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A generator finally alone misses cancellation before its first
            # iteration. The response owns the opened reader throughout ASGI.
            with anyio.CancelScope(shield=True):
                await self.reader.close()


def _byte_range(value: str | None, size_bytes: int) -> tuple[int, int] | None:
    if value is None:
        return None
    value = value.strip()
    unit, _, _spec = value.partition("=")
    if unit.lower() != "bytes":
        # RFC 9110 requires unknown range units to be ignored.
        return None
    error = DomainError(
        "RANGE_NOT_SATISFIABLE", "Only a satisfiable single byte range is supported", 416,
        headers={"Content-Range": f"bytes */{size_bytes}", "Accept-Ranges": "bytes"},
    )
    if len(value) > 256:
        raise error
    match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", value, flags=re.IGNORECASE)
    if match is None or size_bytes == 0:
        raise error
    first, last = match.groups()
    if not first:
        if not last or int(last) == 0:
            raise error
        return max(0, size_bytes - int(last)), size_bytes
    start = int(first)
    stop = size_bytes if not last else min(int(last) + 1, size_bytes)
    if start >= size_bytes or stop <= start:
        raise error
    return start, stop


async def attachment_response(
    attachment: Attachment, request: Request, provider: StorageProvider
) -> Response:
    reader = await provider.open(attachment.object_key)
    try:
        if reader.size_bytes != attachment.size_bytes:
            raise DomainError(
                "STORAGE_OBJECT_CHANGED", "Stored attachment size differs from its registered version", 409,
            )
        if not re.fullmatch(r"[0-9a-f]{64}", attachment.sha256):
            raise DomainError("STORAGE_METADATA_INVALID", "Stored attachment metadata is invalid", 409)
        etag = f'"{attachment.sha256}"'
        filename = quote(
            safe_pdf_filename(attachment.original_filename)
            if attachment.mime_type == "application/pdf"
            else safe_attachment_filename(attachment.original_filename),
            safe="",
        )
        fallback = "paper.pdf" if attachment.mime_type == "application/pdf" else "attachment"
        disposition = "inline" if attachment.mime_type == "application/pdf" else "attachment"
        headers = {
            "Content-Disposition": f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{filename}',
            "Content-Length": str(reader.size_bytes),
            "Cache-Control": "private, no-store",
            "Accept-Ranges": "bytes",
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        if request.method == "HEAD":
            await reader.close()
            return Response(media_type=attachment.mime_type, headers=headers)
        range_value = ",".join(request.headers.getlist("range")) or None
        if_range = request.headers.get("if-range")
        if if_range is not None and if_range != etag:
            range_value = None
        selected = _byte_range(range_value, reader.size_bytes)
        start, end = selected if selected is not None else (0, reader.size_bytes)
        if selected is not None:
            headers["Content-Range"] = f"bytes {start}-{end - 1}/{reader.size_bytes}"
            headers["Content-Length"] = str(end - start)
        return _ClosingStorageResponse(
            reader, start=start, end=end, media_type=attachment.mime_type,
            status_code=206 if selected is not None else 200, headers=headers,
        )
    except BaseException:
        with anyio.CancelScope(shield=True):
            await reader.close()
        raise
