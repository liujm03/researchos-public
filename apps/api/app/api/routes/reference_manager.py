import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.core.config import get_settings
from app.db import get_db
from app.errors import DomainError
from app.providers.registry import reference_manager, storage_provider
from app.services.paper_attachments import copy_zotero_pdf
from app.services.reference_manager import import_zotero_item, read_catalog

router = APIRouter(prefix="/reference-managers/zotero", tags=["reference-managers"])


class ReferenceItemOut(BaseModel):
    key: str
    item_type: str
    title: str
    creators: list[str]
    year: int | None
    doi: str | None
    abstract: str | None
    url: str | None
    venue: str | None
    tags: list[str]


class CollectionOut(BaseModel):
    key: str
    name: str
    parent_key: str | None


class ZoteroCatalogPage(BaseModel):
    items: list[ReferenceItemOut]
    limit: int
    start: int
    raw_count: int
    source_total: int | None
    next_start: int | None


class AttachmentOut(BaseModel):
    key: str
    title: str
    content_type: str | None
    filename: str | None
    link_mode: str | None


class ImportItemRequest(BaseModel):
    existing_paper_id: uuid.UUID | None = None


class ImportItemOut(BaseModel):
    paper_id: uuid.UUID
    title: str


class StatusOut(BaseModel):
    connected: bool
    provider_key: str
    mode: str
    server_id: str | None
    api_version: str | None
    library_type: str | None = None
    library_id: str | None = None


class IndexedTextOut(BaseModel):
    content: str
    total_characters: int
    indexed_pages: int | None
    total_pages: int | None


class CopyPdfRequest(BaseModel):
    paper_id: uuid.UUID


class CopiedPdfOut(BaseModel):
    attachment_id: uuid.UUID
    paper_id: uuid.UUID
    sha256: str
    size_bytes: int
    status: str


@router.get("/status", response_model=StatusOut)
async def status(context: AuthContext = Depends(current_context)) -> StatusOut:
    mode = get_settings().zotero_mode
    if mode == "disabled":
        return StatusOut(
            connected=False, provider_key="zotero", mode=mode, server_id=None, api_version=None
        )
    return StatusOut.model_validate(await reference_manager().status())


@router.get("/items", response_model=list[ReferenceItemOut])
async def items(
    q: str = "",
    collection_key: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    start: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
) -> list[ReferenceItemOut]:
    records = await reference_manager().search_items(q, limit, start, collection_key)
    return [
        ReferenceItemOut(
            key=item.key,
            item_type=item.item_type,
            title=item.title,
            creators=list(item.creators),
            year=item.year,
            doi=item.doi,
            abstract=item.abstract,
            url=item.url,
            venue=item.venue,
            tags=list(item.tags),
        )
        for item in records
    ]


@router.get("/catalog/items", response_model=ZoteroCatalogPage)
async def catalog_items(
    q: str = "",
    collection_key: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    start: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
) -> ZoteroCatalogPage:
    page = await read_catalog(reference_manager(), q, limit, start, collection_key)
    return ZoteroCatalogPage(
        items=[
            ReferenceItemOut(
                key=item.key,
                item_type=item.item_type,
                title=item.title,
                creators=list(item.creators),
                year=item.year,
                doi=item.doi,
                abstract=item.abstract,
                url=item.url,
                venue=item.venue,
                tags=list(item.tags),
            )
            for item in page.items
        ],
        limit=limit,
        start=start,
        raw_count=page.raw_count,
        source_total=page.source_total,
        next_start=page.next_start,
    )


@router.get("/items/{item_key}", response_model=ReferenceItemOut)
async def item(
    item_key: str,
    context: AuthContext = Depends(current_context),
) -> ReferenceItemOut:
    record = await reference_manager().get_item(item_key)
    if record is None:
        raise DomainError("NOT_FOUND", "Zotero item not found", 404)
    return ReferenceItemOut(
        key=record.key,
        item_type=record.item_type,
        title=record.title,
        creators=list(record.creators),
        year=record.year,
        doi=record.doi,
        abstract=record.abstract,
        url=record.url,
        venue=record.venue,
        tags=list(record.tags),
    )


@router.post("/items/{item_key}/import", response_model=ImportItemOut)
async def import_item(
    item_key: str,
    body: ImportItemRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ImportItemOut:
    paper = await import_zotero_item(
        db, context.user.id, item_key, reference_manager(), body.existing_paper_id
    )
    return ImportItemOut(paper_id=paper.id, title=paper.title)


@router.get("/collections", response_model=list[CollectionOut])
async def collections(
    limit: int = Query(default=100, ge=1, le=100),
    start: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
) -> list[CollectionOut]:
    records = await reference_manager().list_collections(limit, start)
    return [
        CollectionOut(key=item.key, name=item.name, parent_key=item.parent_key) for item in records
    ]


@router.get("/items/{item_key}/attachments", response_model=list[AttachmentOut])
async def attachments(
    item_key: str,
    context: AuthContext = Depends(current_context),
) -> list[AttachmentOut]:
    provider = reference_manager()
    parent = await provider.get_item(item_key)
    if parent is None:
        raise DomainError("NOT_FOUND", "Zotero item not found", 404)
    records = await provider.list_attachments(item_key)
    return [
        AttachmentOut(
            key=item.key,
            title=item.title,
            content_type=item.content_type,
            filename=item.filename,
            link_mode=item.link_mode,
        )
        for item in records
    ]


async def _verified_pdf(item_key: str, attachment_key: str) -> None:
    provider = reference_manager()
    parent = await provider.get_item(item_key)
    if parent is None:
        raise DomainError("NOT_FOUND", "Zotero item not found", 404)
    attachments = await provider.list_attachments(item_key)
    attachment = next((item for item in attachments if item.key == attachment_key), None)
    if attachment is None or attachment.content_type != "application/pdf":
        raise DomainError("NOT_FOUND", "PDF attachment not found for this item", 404)


@router.get("/items/{item_key}/attachments/{attachment_key}/content")
async def attachment_content(
    item_key: str,
    attachment_key: str,
    context: AuthContext = Depends(current_context),
) -> StreamingResponse:
    await _verified_pdf(item_key, attachment_key)
    content = await reference_manager().open_attachment(attachment_key)

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in content.chunks:
                yield chunk
        finally:
            await content.close()

    headers = {"Content-Disposition": "inline", "Cache-Control": "private, no-store"}
    if content.content_length is not None:
        headers["Content-Length"] = str(content.content_length)
    return StreamingResponse(chunks(), media_type="application/pdf", headers=headers)


@router.post("/items/{item_key}/attachments/{attachment_key}/copy", response_model=CopiedPdfOut)
async def copy_pdf(
    item_key: str,
    attachment_key: str,
    body: CopyPdfRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CopiedPdfOut:
    attachment, link = await copy_zotero_pdf(
        db,
        context.user.id,
        body.paper_id,
        item_key,
        attachment_key,
        reference_manager(),
        storage_provider(),
    )
    return CopiedPdfOut(
        attachment_id=attachment.id,
        paper_id=body.paper_id,
        sha256=attachment.sha256,
        size_bytes=attachment.size_bytes,
        status=link.status,
    )


@router.get(
    "/items/{item_key}/attachments/{attachment_key}/fulltext", response_model=IndexedTextOut
)
async def attachment_fulltext(
    item_key: str,
    attachment_key: str,
    limit_chars: int = Query(default=20000, ge=100, le=100000),
    context: AuthContext = Depends(current_context),
) -> IndexedTextOut:
    await _verified_pdf(item_key, attachment_key)
    indexed = await reference_manager().get_indexed_fulltext(attachment_key)
    if indexed is None:
        raise DomainError("NOT_FOUND", "Zotero has no indexed full text for this attachment", 404)
    return IndexedTextOut(
        content=indexed.content[:limit_chars],
        total_characters=len(indexed.content),
        indexed_pages=indexed.indexed_pages,
        total_pages=indexed.total_pages,
    )
