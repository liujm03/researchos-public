"""Owner supplied PDFs use the same storage, evidence and parse registry as Zotero."""

import unicodedata
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.paper_parser import PaperParser
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import Attachment, Paper, PaperAttachment, PaperParseJob
from app.services.papers import get_paper
from app.services.parse_jobs import enqueue_parse_job


@dataclass(frozen=True)
class PdfUploadResult:
    attachment: Attachment
    link: PaperAttachment
    parse_job: PaperParseJob
    duplicate: bool


def safe_pdf_filename(filename: str | None) -> str:
    """A display label only: paths never determine the provider object key."""
    name = unicodedata.normalize("NFC", filename or "paper.pdf")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(
        char for char in name
        if not unicodedata.category(char).startswith("C") and char not in '<>:"|?*'
    ).strip(" .")
    if not name:
        name = "paper.pdf"
    # Reserve space for a stable .pdf extension within Attachment.original_filename.
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return f"{name[:316] or 'paper'}.pdf"


async def _validated_pdf_stream(
    content: AsyncIterator[bytes], max_bytes: int
) -> AsyncIterator[bytes]:
    size = 0
    signature = bytearray()
    checked = False
    async for chunk in content:
        if not chunk:
            continue
        size += len(chunk)
        if size > max_bytes:
            raise DomainError("FILE_TOO_LARGE", "PDF exceeds configured size limit", 413)
        if not checked:
            take = min(5 - len(signature), len(chunk))
            signature.extend(chunk[:take])
            if len(signature) < 5:
                continue
            if signature != b"%PDF-":
                raise DomainError("INVALID_PDF", "Uploaded file is not a PDF", 422)
            checked = True
            yield bytes(signature)
            if chunk[take:]:
                yield chunk[take:]
        else:
            yield chunk
    if not checked:
        raise DomainError("INVALID_PDF", "Uploaded file is empty or not a PDF", 422)


async def upload_paper_pdf(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    content: AsyncIterator[bytes],
    *,
    filename: str | None,
    content_type: str | None,
    storage: StorageProvider,
    parser: PaperParser,
    max_bytes: int,
) -> PdfUploadResult:
    get_paper(db, user_id, paper_id)
    if max_bytes <= 0:
        raise DomainError("CONFIGURATION_ERROR", "PDF upload size limit must be positive", 503)
    if content_type != "application/pdf":
        raise DomainError("INVALID_PDF", "The uploaded file must use application/pdf", 422)
    try:
        stored = await storage.save(
            _validated_pdf_stream(content, max_bytes),
            mime_type="application/pdf", max_bytes=max_bytes,
        )
    except OSError as exc:
        raise DomainError("STORAGE_UNAVAILABLE", "PDF storage is unavailable", 503) from exc

    cleanup_key: str | None = stored.key
    commit_attempted = False
    try:
        # PostgreSQL serializes upload confirmation per Paper. No row lock is held
        # while the owner uploads or while a storage provider writes the bytes.
        locked = db.scalar(
            select(Paper)
            .where(Paper.id == paper_id, Paper.user_id == user_id)
            .with_for_update()
        )
        if locked is None:
            raise DomainError("NOT_FOUND", "Paper not found", 404)
        existing = db.execute(
            select(Attachment, PaperAttachment)
            .join(PaperAttachment, PaperAttachment.attachment_id == Attachment.id)
            .where(
                PaperAttachment.paper_id == paper_id,
                Attachment.user_id == user_id,
                Attachment.deleted_at.is_(None),
                Attachment.storage_provider == storage.provider_key,
                Attachment.sha256 == stored.sha256,
            )
            .order_by(PaperAttachment.created_at, PaperAttachment.id)
            .limit(1)
        ).first()
        if existing is not None:
            attachment, link = existing
            await storage.delete(stored.key)
            cleanup_key = None
        else:
            attachment = Attachment(
                id=uuid.uuid4(), user_id=user_id, storage_provider=storage.provider_key,
                object_key=stored.key, original_filename=safe_pdf_filename(filename),
                mime_type=stored.mime_type, size_bytes=stored.size_bytes, sha256=stored.sha256,
            )
            db.add(attachment)
            db.flush()
            link = PaperAttachment(
                id=uuid.uuid4(), paper_id=paper_id, attachment_id=attachment.id,
                status="DOWNLOADED",
            )
            db.add(link)
            db.flush()
        parse_job = enqueue_parse_job(
            db, user_id, paper_id, attachment.id, parser,
            suppress_auto_analysis=True, commit=False,
        )
        # No committed attachment can be left without its durable local parse job.
        commit_attempted = True
        db.commit()
        cleanup_key = None
        return PdfUploadResult(attachment, link, parse_job, existing is not None)
    except BaseException:
        db.rollback()
        if cleanup_key is not None:
            if commit_attempted:
                # A lost commit acknowledgment is not proof of rollback. Never
                # delete bytes that the database may already have registered.
                try:
                    registered = db.scalar(
                        select(Attachment.id).where(
                            Attachment.user_id == user_id,
                            Attachment.object_key == cleanup_key,
                            Attachment.storage_provider == storage.provider_key,
                        )
                    )
                except Exception as exc:
                    raise DomainError(
                        "UPLOAD_OUTCOME_UNKNOWN",
                        "PDF confirmation could not be checked; retry after the database is available",
                        503,
                    ) from exc
                if registered is not None:
                    raise DomainError(
                        "UPLOAD_OUTCOME_UNKNOWN",
                        "PDF was registered but confirmation failed; retrying the upload is safe",
                        503,
                    ) from None
            try:
                await storage.delete(cleanup_key)
            except Exception as exc:
                raise DomainError(
                    "STORAGE_CLEANUP_FAILED", "PDF save failed and storage cleanup needs attention", 503
                ) from exc
        raise
