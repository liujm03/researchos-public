import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.reference_manager import ReferenceManagerProvider
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import Attachment, PaperAttachment, PaperSource, ZoteroSourceItem
from app.services.papers import get_paper


async def copy_zotero_pdf(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    item_key: str,
    attachment_key: str,
    provider: ReferenceManagerProvider,
    storage: StorageProvider,
) -> tuple[Attachment, PaperAttachment]:
    get_paper(db, user_id, paper_id)
    status = await provider.status()
    server_id = status.get("server_id")
    library_type = status.get("library_type") or "user"
    library_id = status.get("library_id") or "0"
    if not isinstance(server_id, str) or not server_id:
        raise DomainError("PROVIDER_UNAVAILABLE", "Zotero source identity is unavailable", 503)
    source_item = db.scalar(
        select(ZoteroSourceItem)
        .join(PaperSource, PaperSource.id == ZoteroSourceItem.paper_source_id)
        .where(
            ZoteroSourceItem.user_id == user_id,
            ZoteroSourceItem.server_id == server_id,
            ZoteroSourceItem.library_type == library_type,
            ZoteroSourceItem.library_id == library_id,
            ZoteroSourceItem.item_key == item_key,
            PaperSource.paper_id == paper_id,
            PaperSource.provider_key == provider.provider_key,
        )
    )
    if source_item is None:
        raise DomainError("NOT_FOUND", "Import this Zotero item before copying its PDF", 404)
    candidates = await provider.list_attachments(item_key)
    candidate = next((item for item in candidates if item.key == attachment_key), None)
    if candidate is None or candidate.content_type != "application/pdf":
        raise DomainError("NOT_FOUND", "PDF attachment not found for this Zotero item", 404)
    existing = db.scalar(
        select(PaperAttachment).where(
            PaperAttachment.source_item_id == source_item.id,
            PaperAttachment.attachment_key == attachment_key,
            PaperAttachment.source_version == candidate.version,
        )
    )
    if existing and existing.attachment_id:
        attachment = db.get(Attachment, existing.attachment_id)
        if attachment is not None:
            return attachment, existing
    upstream = await provider.open_attachment(attachment_key)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if upstream.content_length is not None and upstream.content_length > max_bytes:
        await upstream.close()
        raise DomainError("FILE_TOO_LARGE", "Zotero PDF exceeds configured limit", 413)
    try:
        stored = await storage.save(
            upstream.chunks, mime_type="application/pdf", max_bytes=max_bytes
        )
    finally:
        await upstream.close()
    attachment = Attachment(
        id=uuid.uuid4(),
        user_id=user_id,
        storage_provider=storage.provider_key,
        object_key=stored.key,
        original_filename=candidate.filename or f"{attachment_key}.pdf",
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
    )
    link = PaperAttachment(
        id=uuid.uuid4(),
        paper_id=paper_id,
        source_item_id=source_item.id,
        attachment_id=attachment.id,
        attachment_key=attachment_key,
        source_version=candidate.version,
        status="DOWNLOADED",
    )
    db.add_all([attachment, link])
    source_item.attachment_status = "DOWNLOADED"
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        await storage.delete(stored.key)
        if isinstance(exc, IntegrityError):
            raise DomainError("CONFLICT", "PDF version was already copied", 409) from exc
        raise
    db.refresh(attachment)
    db.refresh(link)
    return attachment, link
