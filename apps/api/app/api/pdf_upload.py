"""Bound multipart parsing before Starlette can spool unbounded file data."""

from collections.abc import AsyncGenerator, AsyncIterator

from fastapi import Request
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.errors import DomainError

MULTIPART_OVERHEAD_BYTES = 64 * 1024


class _CompleteMultiPartParser(MultiPartParser):
    def __init__(self, headers: Headers, stream: AsyncGenerator[bytes, None]) -> None:
        super().__init__(headers, stream, max_files=1, max_fields=0)
        self.complete = False

    def on_end(self) -> None:
        super().on_end()
        self.complete = True

    async def parse(self) -> FormData:
        try:
            form = await super().parse()
            if not self.complete:
                raise MultiPartException("Incomplete multipart body")
            return form
        except BaseException:
            # Starlette may return a partial form without seeing the final
            # boundary. Its spool registry also contains the incomplete part.
            for file in self._files_to_close_on_error:
                file.close()
            raise


async def parse_pdf_form(request: Request, *, max_bytes: int) -> FormData:
    return await parse_file_form(request, max_bytes=max_bytes, label="PDF")


async def parse_file_form(request: Request, *, max_bytes: int, label: str = "Artifact") -> FormData:
    if max_bytes <= 0:
        raise DomainError("CONFIGURATION_ERROR", "Upload size limit must be positive", 503)
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        raise DomainError("VALIDATION_ERROR", "Upload requires multipart/form-data", 422)
    max_body_bytes = max_bytes + MULTIPART_OVERHEAD_BYTES
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError as exc:
            raise DomainError("VALIDATION_ERROR", "Invalid Content-Length", 422) from exc
        if declared < 0:
            raise DomainError("VALIDATION_ERROR", "Invalid Content-Length", 422)
        if declared > max_body_bytes:
            raise DomainError(
                "FILE_TOO_LARGE", f"{label} upload exceeds configured size limit", 413
            )
    exceeded = False

    async def bounded_body() -> AsyncGenerator[bytes, None]:
        nonlocal exceeded
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > max_body_bytes:
                exceeded = True
                # MultiPartParser closes every spool file on this exception,
                # including on older supported Starlette versions.
                raise MultiPartException(f"{label} upload exceeds configured size limit")
            yield chunk

    parser = _CompleteMultiPartParser(request.headers, bounded_body())
    try:
        form = await parser.parse()
    except (MultiPartException, MultipartParseError) as exc:
        if exceeded:
            raise DomainError(
                "FILE_TOO_LARGE", f"{label} upload exceeds configured size limit", 413
            ) from exc
        raise DomainError(
            "VALIDATION_ERROR", f"Upload must contain exactly one {label} file", 422
        ) from exc
    parts = form.multi_items()
    if len(parts) != 1 or parts[0][0] != "file" or not isinstance(parts[0][1], UploadFile):
        await form.close()
        raise DomainError(
            "VALIDATION_ERROR", "Upload must contain exactly one file named file", 422
        )
    upload = parts[0][1]
    if upload.size is not None and upload.size > max_bytes:
        await form.close()
        raise DomainError("FILE_TOO_LARGE", f"{label} exceeds configured size limit", 413)
    return form


async def upload_chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await upload.read(128 * 1024):
        yield chunk
