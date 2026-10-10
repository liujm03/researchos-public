import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.reference_manager import (
    CatalogReferenceManagerProvider,
    ReferenceCatalogPage,
    ReferenceManagerProvider,
)
from app.errors import DomainError
from app.models import Paper, PaperSource, ZoteroSourceItem
from app.schemas import PaperCreate
from app.services.papers import create_paper, get_paper, normalize_doi
from app.services.zotero_venue_fields import capture_fields


async def import_zotero_item(
    db: Session,
    user_id: uuid.UUID,
    item_key: str,
    provider: ReferenceManagerProvider,
    existing_paper_id: uuid.UUID | None = None,
) -> Paper:
    status = await provider.status()
    server_id = status.get("server_id")
    if not isinstance(server_id, str) or not server_id:
        raise DomainError("PROVIDER_UNAVAILABLE", "Zotero instance ID is unavailable", 503)
    library_type = status.get("library_type") or "user"
    library_id = status.get("library_id") or "0"
    if (
        not isinstance(library_type, str)
        or library_type not in {"user", "group"}
        or not isinstance(library_id, str)
    ):
        raise DomainError("PROVIDER_UNAVAILABLE", "Zotero library identity is invalid", 503)
    item = await provider.get_item(item_key)
    if item is None or item.item_type in {"attachment", "note", "annotation"}:
        raise DomainError("NOT_FOUND", "Zotero paper item not found", 404)
    library_path = "users" if library_type == "user" else "groups"
    provider_id = f"{server_id}:{library_path}/{library_id}:{item.key}"
    source = db.scalar(
        select(PaperSource).where(
            PaperSource.user_id == user_id,
            PaperSource.provider_key == provider.provider_key,
            PaperSource.provider_id == provider_id,
        )
    )
    if source is not None:
        source_item = db.scalar(
            select(ZoteroSourceItem).where(
                ZoteroSourceItem.paper_source_id == source.id,
                ZoteroSourceItem.user_id == user_id,
            )
        )
        if source_item is None:
            source_item = ZoteroSourceItem(
                user_id=user_id,
                paper_source_id=source.id,
                server_id=server_id,
                library_type=library_type,
                library_id=library_id,
                item_key=item_key,
                item_version=source.source_version or 0,
            )
            db.add(source_item)
        capture_fields(db, user_id, source_item, item.venue_fields, item.version)
        db.commit()
        return get_paper(db, user_id, source.paper_id)

    if existing_paper_id is not None:
        paper = get_paper(db, user_id, existing_paper_id)
        if item.doi and paper.normalized_doi and normalize_doi(item.doi) != paper.normalized_doi:
            raise DomainError("CONFLICT", "The selected paper has a different DOI", 409)
    else:
        paper = None
        normalized_doi = normalize_doi(item.doi)
        if normalized_doi:
            paper = db.scalar(
                select(Paper).where(
                    Paper.user_id == user_id, Paper.normalized_doi == normalized_doi
                )
            )
        if paper is None:
            normalized_title = " ".join(item.title.lower().split())
            candidate = db.scalar(
                select(Paper).where(
                    Paper.user_id == user_id,
                    Paper.normalized_title == normalized_title,
                    Paper.year == item.year,
                )
            )
            if candidate is not None:
                raise DomainError(
                    "DUPLICATE_CANDIDATE",
                    "A paper with the same title and year exists; choose it explicitly or review the record",
                    409,
                    details={"candidate_paper_id": str(candidate.id)},
                )
            paper = create_paper(
                db,
                user_id,
                PaperCreate(
                    title=item.title,
                    year=item.year,
                    venue_name=item.venue,
                    authors=list(item.creators),
                    doi=item.doi,
                    abstract=item.abstract,
                    url=item.url,
                    tags=list(item.tags),
                ),
                commit=False,
            )
    assert paper is not None
    source_id = uuid.uuid4()
    db.add(
        PaperSource(
            id=source_id,
            user_id=user_id,
            paper_id=paper.id,
            provider_key=provider.provider_key,
            provider_id=provider_id,
            source_version=item.version,
        )
    )
    source_item = ZoteroSourceItem(
        user_id=user_id,
        paper_source_id=source_id,
        server_id=server_id,
        library_type=library_type,
        library_id=library_id,
        item_key=item.key,
        item_version=item.version,
    )
    db.add(source_item)
    db.flush()
    # Preserve the exact collection keys supplied by this authorized item read.
    # Names/hierarchy remain explicitly cached or refreshed through the folder endpoint.
    from app.services.zotero_sync import _sync_item_collections

    _sync_item_collections(db, user_id, server_id, library_type, library_id, source_item.id, item)
    capture_fields(db, user_id, source_item, item.venue_fields, item.version)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("CONFLICT", "Zotero item is already linked", 409) from exc
    db.refresh(paper)
    return paper


async def read_catalog(
    provider: ReferenceManagerProvider,
    query: str,
    limit: int,
    start: int,
    collection_key: str | None = None,
) -> ReferenceCatalogPage:
    if not isinstance(provider, CatalogReferenceManagerProvider):
        raise DomainError("CAPABILITY_UNAVAILABLE", "Provider has no paged catalog capability", 501)
    return await provider.search_items_page(query, limit, start, collection_key)
