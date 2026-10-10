import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import Attachment, PaperAttachment, ResearchEntity
from app.models_pdf_annotations import PdfAnnotation, PdfAnnotationGeometry, PdfAnnotationPoint
from app.providers.pdf_annotations.base import PdfAnnotationProvider
from app.schemas_pdf_annotations import (
    PdfAnnotationOut,
    PdfAnnotationPut,
    PdfAnnotationsOut,
    PdfGeometry,
    PdfPoint,
)
from app.services.papers import get_paper

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_ANNOTATIONS = 2000


def source_attachment(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    expected_sha: str | None = None,
    *,
    lock: bool = False,
) -> Attachment:
    get_paper(db, user_id, paper_id)
    entity = db.get(ResearchEntity, paper_id)
    if entity is None or entity.user_id != user_id or entity.deleted_at is not None:
        raise DomainError("NOT_FOUND", "Paper not found", 404)
    query = (
        select(Attachment)
        .join(PaperAttachment, PaperAttachment.attachment_id == Attachment.id)
        .where(
            Attachment.id == attachment_id,
            Attachment.user_id == user_id,
            Attachment.deleted_at.is_(None),
            PaperAttachment.paper_id == paper_id,
        )
    )
    if lock:
        query = query.with_for_update(of=Attachment)
    attachment = db.scalar(query)
    if attachment is None:
        raise DomainError("NOT_FOUND", "PDF attachment is not linked to this paper", 404)
    if attachment.mime_type != "application/pdf":
        raise DomainError("PDF_REQUIRED", "Annotations require a PDF attachment", 422)
    if expected_sha is not None and attachment.sha256 != expected_sha:
        raise DomainError("PDF_SOURCE_CHANGED", "PDF source has changed; reopen before saving", 409)
    return attachment


async def source_bytes(attachment: Attachment, storage: StorageProvider) -> bytes:
    if attachment.storage_provider != storage.provider_key:
        raise DomainError("STORAGE_UNAVAILABLE", "PDF storage provider is unavailable", 503)
    if attachment.size_bytes <= 0 or attachment.size_bytes > MAX_SOURCE_BYTES:
        raise DomainError("PDF_SIZE_LIMIT", "Annotation source must be at most 64 MiB", 413)
    reader = await storage.open(attachment.object_key)
    chunks: list[bytes] = []
    total = 0
    try:
        if reader.size_bytes != attachment.size_bytes:
            raise DomainError(
                "PDF_SOURCE_CHANGED", "Stored PDF size differs from its identity", 409
            )
        async for chunk in reader.iter_bytes():
            total += len(chunk)
            if total > MAX_SOURCE_BYTES or total > attachment.size_bytes:
                raise DomainError("PDF_SIZE_LIMIT", "Stored PDF exceeds its size limit", 413)
            chunks.append(chunk)
    finally:
        await reader.close()
    data = b"".join(chunks)
    if len(data) != attachment.size_bytes or hashlib.sha256(data).hexdigest() != attachment.sha256:
        raise DomainError(
            "PDF_SOURCE_CHANGED", "Stored PDF checksum differs from its identity", 409
        )
    return data


def _item(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    annotation_id: uuid.UUID,
) -> PdfAnnotation:
    item = db.scalar(
        select(PdfAnnotation).where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.user_id == user_id,
            PdfAnnotation.paper_id == paper_id,
            PdfAnnotation.attachment_id == attachment_id,
        )
    )
    if item is None:
        raise DomainError("NOT_FOUND", "PDF mark not found", 404)
    return item


def annotation_out(db: Session, item: PdfAnnotation) -> PdfAnnotationOut:
    rows = db.scalars(
        select(PdfAnnotationGeometry)
        .where(
            PdfAnnotationGeometry.annotation_id == item.id,
            PdfAnnotationGeometry.user_id == item.user_id,
        )
        .order_by(PdfAnnotationGeometry.position)
    ).all()
    geometries = []
    for row in rows:
        points = db.scalars(
            select(PdfAnnotationPoint)
            .where(
                PdfAnnotationPoint.geometry_id == row.id,
                PdfAnnotationPoint.user_id == item.user_id,
            )
            .order_by(PdfAnnotationPoint.position)
        ).all()
        geometries.append(
            PdfGeometry(
                geometry_kind=cast(Literal["RECT", "STROKE"], row.geometry_kind),
                x=row.x,
                y=row.y,
                width=row.width,
                height=row.height,
                points=[PdfPoint(x=p.x, y=p.y) for p in points],
            )
        )
    return PdfAnnotationOut(
        id=item.id,
        attachment_id=item.attachment_id,
        source_sha256=item.source_sha256,
        kind=cast(Literal["HIGHLIGHT", "UNDERLINE", "COMMENT", "INK"], item.kind),
        page=item.page,
        color=item.color,
        body=item.body,
        revision=item.revision,
        geometries=geometries,
        created_at=item.created_at,
        updated_at=item.updated_at,
        deleted_at=item.deleted_at,
    )


async def list_annotations(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    storage: StorageProvider,
    provider: PdfAnnotationProvider,
) -> PdfAnnotationsOut:
    attachment = source_attachment(db, user_id, paper_id, attachment_id, lock=True)
    raw = await source_bytes(attachment, storage)
    count = await asyncio.to_thread(provider.page_count, raw)
    items = db.scalars(
        select(PdfAnnotation)
        .where(
            PdfAnnotation.user_id == user_id,
            PdfAnnotation.paper_id == paper_id,
            PdfAnnotation.attachment_id == attachment_id,
            PdfAnnotation.source_sha256 == attachment.sha256,
            PdfAnnotation.deleted_at.is_(None),
        )
        .order_by(PdfAnnotation.page, PdfAnnotation.created_at, PdfAnnotation.id)
        .limit(MAX_ANNOTATIONS + 1)
    ).all()
    if len(items) > MAX_ANNOTATIONS:
        raise DomainError("PDF_ANNOTATION_LIMIT", "Too many PDF marks", 422)
    return PdfAnnotationsOut(
        attachment_id=attachment.id,
        source_sha256=attachment.sha256,
        page_count=count,
        annotations=[annotation_out(db, item) for item in items],
    )


def get_annotation(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    annotation_id: uuid.UUID,
) -> PdfAnnotationOut:
    attachment = source_attachment(db, user_id, paper_id, attachment_id, lock=True)
    item = _item(db, user_id, paper_id, attachment_id, annotation_id)
    if item.source_sha256 != attachment.sha256:
        raise DomainError("PDF_SOURCE_CHANGED", "Mark belongs to a different PDF version", 409)
    return annotation_out(db, item)


def _replace_geometries(db: Session, item: PdfAnnotation, geometries: list[PdfGeometry]) -> None:
    old = select(PdfAnnotationGeometry.id).where(
        PdfAnnotationGeometry.annotation_id == item.id,
        PdfAnnotationGeometry.user_id == item.user_id,
    )
    db.execute(
        delete(PdfAnnotationPoint).where(
            PdfAnnotationPoint.geometry_id.in_(old), PdfAnnotationPoint.user_id == item.user_id
        )
    )
    db.execute(
        delete(PdfAnnotationGeometry).where(
            PdfAnnotationGeometry.annotation_id == item.id,
            PdfAnnotationGeometry.user_id == item.user_id,
        )
    )
    for index, geometry in enumerate(geometries):
        row = PdfAnnotationGeometry(
            id=uuid.uuid4(),
            user_id=item.user_id,
            annotation_id=item.id,
            position=index,
            geometry_kind=geometry.geometry_kind,
            x=geometry.x,
            y=geometry.y,
            width=geometry.width,
            height=geometry.height,
        )
        db.add(row)
        db.flush()
        for pos, point in enumerate(geometry.points):
            db.add(
                PdfAnnotationPoint(
                    user_id=item.user_id, geometry_id=row.id, position=pos, x=point.x, y=point.y
                )
            )


async def put_annotation(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    annotation_id: uuid.UUID,
    data: PdfAnnotationPut,
    storage: StorageProvider,
    provider: PdfAnnotationProvider,
) -> PdfAnnotationOut:
    attachment = source_attachment(
        db, user_id, paper_id, attachment_id, data.source_sha256, lock=True
    )
    payload_sha = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    existing = db.get(PdfAnnotation, annotation_id)
    if existing is not None:
        if (
            existing.user_id,
            existing.paper_id,
            existing.attachment_id,
            existing.source_sha256,
        ) != (user_id, paper_id, attachment_id, data.source_sha256):
            raise DomainError("CONFLICT", "PDF mark identity is already in use", 409)
        if (
            existing.deleted_at is None
            and existing.payload_sha256 == payload_sha
            and existing.last_expected_revision == data.expected_revision
        ):
            return annotation_out(db, existing)
        if existing.deleted_at is not None or existing.revision != data.expected_revision:
            raise DomainError(
                "REVISION_CONFLICT", "PDF mark changed; reopen to inspect the saved version", 409
            )
    elif data.expected_revision != 0:
        raise DomainError("REVISION_CONFLICT", "New marks require expected_revision 0", 409)
    raw = await source_bytes(attachment, storage)
    page_count = await asyncio.to_thread(provider.page_count, raw)
    if data.page > page_count:
        raise DomainError("PDF_PAGE_INVALID", "PDF mark page is outside the actual PDF", 422)
    now = datetime.now(UTC)
    if existing is None:
        count = (
            db.scalar(
                select(func.count())
                .select_from(PdfAnnotation)
                .where(
                    PdfAnnotation.user_id == user_id,
                    PdfAnnotation.paper_id == paper_id,
                    PdfAnnotation.attachment_id == attachment_id,
                    PdfAnnotation.deleted_at.is_(None),
                )
            )
            or 0
        )
        if count >= MAX_ANNOTATIONS:
            raise DomainError("PDF_ANNOTATION_LIMIT", "This PDF already has 2000 marks", 422)
        existing = PdfAnnotation(
            id=annotation_id,
            user_id=user_id,
            paper_id=paper_id,
            attachment_id=attachment_id,
            source_sha256=data.source_sha256,
            kind=data.kind,
            page=data.page,
            color=data.color.lower(),
            body=data.body,
            revision=1,
            last_expected_revision=0,
            payload_sha256=payload_sha,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise DomainError(
                "REVISION_CONFLICT", "PDF mark was saved concurrently; inspect it first", 409
            ) from exc
    else:
        result = db.execute(
            update(PdfAnnotation)
            .where(
                PdfAnnotation.id == annotation_id,
                PdfAnnotation.user_id == user_id,
                PdfAnnotation.revision == data.expected_revision,
                PdfAnnotation.deleted_at.is_(None),
            )
            .values(
                kind=data.kind,
                page=data.page,
                color=data.color.lower(),
                body=data.body,
                revision=data.expected_revision + 1,
                last_expected_revision=data.expected_revision,
                payload_sha256=payload_sha,
                updated_at=now,
            )
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            raise DomainError("REVISION_CONFLICT", "PDF mark was changed concurrently", 409)
    _replace_geometries(db, existing, data.geometries)
    db.commit()
    db.refresh(existing)
    return annotation_out(db, existing)


def delete_annotation(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    annotation_id: uuid.UUID,
    expected_revision: int,
    source_sha256: str,
) -> PdfAnnotationOut:
    source_attachment(db, user_id, paper_id, attachment_id, source_sha256, lock=True)
    item = _item(db, user_id, paper_id, attachment_id, annotation_id)
    if item.source_sha256 != source_sha256:
        raise DomainError("PDF_SOURCE_CHANGED", "Mark belongs to a different PDF version", 409)
    if item.deleted_at is not None and item.last_expected_revision == expected_revision:
        return annotation_out(db, item)
    now = datetime.now(UTC)
    result = db.execute(
        update(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.user_id == user_id,
            PdfAnnotation.revision == expected_revision,
            PdfAnnotation.deleted_at.is_(None),
        )
        .values(
            revision=expected_revision + 1,
            last_expected_revision=expected_revision,
            deleted_at=now,
            updated_at=now,
        )
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        db.rollback()
        raise DomainError("REVISION_CONFLICT", "PDF mark changed; inspect before deleting", 409)
    db.commit()
    db.refresh(item)
    return annotation_out(db, item)


async def export_annotated_pdf(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    storage: StorageProvider,
    provider: PdfAnnotationProvider,
) -> bytes:
    attachment = source_attachment(db, user_id, paper_id, attachment_id, lock=True)
    raw = await source_bytes(attachment, storage)
    items = db.scalars(
        select(PdfAnnotation)
        .where(
            PdfAnnotation.user_id == user_id,
            PdfAnnotation.paper_id == paper_id,
            PdfAnnotation.attachment_id == attachment_id,
            PdfAnnotation.source_sha256 == attachment.sha256,
            PdfAnnotation.deleted_at.is_(None),
        )
        .order_by(PdfAnnotation.page, PdfAnnotation.id)
        .limit(MAX_ANNOTATIONS + 1)
    ).all()
    if len(items) > MAX_ANNOTATIONS:
        raise DomainError("PDF_ANNOTATION_LIMIT", "Too many PDF marks to export", 422)
    return await asyncio.to_thread(
        provider.export, raw, [annotation_out(db, item) for item in items]
    )
