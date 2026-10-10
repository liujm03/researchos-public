"""Read-only Zotero synchronization into the ResearchOS source registry.

The source cursor advances only after an entire changed-item pass succeeds. Each
item commits independently, so a failed item cannot erase other imported work.
Replaying a failed pass is safe because source identity and version are stable.
"""

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import BigInteger, cast, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.literature_identity import normalized_arxiv_id
from app.domain.reference_manager import (
    IncrementalReferenceManagerProvider,
    ReferenceAttachment,
    ReferenceItem,
    ReferenceManagerProvider,
)
from app.errors import DomainError
from app.models import (
    Author,
    EntityTag,
    Paper,
    PaperAttachment,
    PaperAuthor,
    PaperSource,
    SyncJob,
    Tag,
    ZoteroCollection,
    ZoteroItemCollection,
    ZoteroSourceItem,
    ZoteroSyncCursor,
)
from app.schemas import PaperCreate
from app.services.papers import create_paper, normalize_doi
from app.services.zotero_venue_fields import capture_fields

LOCAL_LIBRARY_TYPE = "user"
LOCAL_LIBRARY_ID = "0"
PAGE_SIZE = 100
MAX_CHANGED_ROWS = 20_000
CHILD_TYPES = {"attachment", "note", "annotation"}
logger = logging.getLogger(__name__)


def safe_sync_error(exc: Exception) -> str:
    """Unexpected database/provider details stay out of persisted UI messages."""
    if isinstance(exc, DomainError):
        return exc.message
    reference = uuid.uuid4().hex
    logger.error("Zotero sync failed; error_reference=%s exception_type=%s", reference, type(exc).__name__)
    return f"Zotero synchronization failed; error reference: {reference}"


@dataclass(frozen=True)
class SyncResult:
    job_id: uuid.UUID
    status: str
    cursor_before: str | None
    cursor_after: str | None
    scanned: int
    created: int
    updated: int
    skipped: int
    failed: int
    errors: tuple[dict[str, object], ...]
    paper_ids: tuple[uuid.UUID, ...]
    content_changed_paper_ids: tuple[uuid.UUID, ...]
    content_change_unknown_paper_ids: tuple[uuid.UUID, ...]
    has_more: bool = False
    candidate_item_keys: tuple[str, ...] = ()


def _identifier(item: ReferenceItem, kind: str) -> str | None:
    data = item.raw.get("data", {})
    if not isinstance(data, dict):
        return None
    extra = data.get("extra") or ""
    if kind == "arxiv":
        value = data.get("arxiv_id")
        if not value and str(data.get("archive") or "").casefold() == "arxiv":
            value = data.get("archiveLocation")
        if value:
            return str(value).strip()
        match = re.search(r"(?im)^\s*arXiv\s*:\s*([^\s;]+)", str(extra))
        return match.group(1).strip() if match else None
    value = data.get("PMID") or data.get("pmid")
    if value:
        return str(value).strip()
    match = re.search(r"(?im)^\s*PMID\s*:\s*(\d+)", str(extra))
    return match.group(1) if match else None


def _source_identity(
    server_id: str, library_type: str, library_id: str, item_key: str
) -> str:
    return f"{server_id}:{library_type}s/{library_id}:{item_key}"


def _job_key(
    client_key: str | None, item_key: str | None, provider_key: str,
    server_id: str, library_type: str, library_id: str,
) -> str | None:
    if client_key is None:
        return None
    scope = f"single:{item_key}" if item_key else "batch"
    identity = f"{provider_key}:{server_id}:{library_type}s/{library_id}"
    return hashlib.sha256(f"{identity}:{scope}:{client_key}".encode()).hexdigest()


def _source_item(
    db: Session, user_id: uuid.UUID, server_id: str, library_type: str,
    library_id: str, item_key: str,
) -> ZoteroSourceItem | None:
    return db.scalar(
        select(ZoteroSourceItem).where(
            ZoteroSourceItem.user_id == user_id,
            ZoteroSourceItem.server_id == server_id,
            ZoteroSourceItem.library_type == library_type,
            ZoteroSourceItem.library_id == library_id,
            ZoteroSourceItem.item_key == item_key,
        )
    )


def _find_paper(db: Session, user_id: uuid.UUID, item: ReferenceItem) -> Paper | None:
    doi = normalize_doi(item.doi)
    if doi:
        match = db.scalar(
            select(Paper).where(Paper.user_id == user_id, Paper.normalized_doi == doi)
        )
        if match is not None:
            return match
    for column, value in ((Paper.normalized_arxiv_id, normalized_arxiv_id(_identifier(item, "arxiv"))), (Paper.pmid, _identifier(item, "pmid"))):
        if value:
            match = db.scalar(select(Paper).where(Paper.user_id == user_id, column == value))
            if match is not None:
                if doi and match.normalized_doi and match.normalized_doi != doi:
                    raise DomainError(
                        "DUPLICATE_CANDIDATE", "Identifiers point to different papers", 409,
                        details={"candidate_paper_id": str(match.id)},
                    )
                return match
    normalized_title = " ".join(item.title.lower().split())
    candidates = list(
        db.scalars(
            select(Paper).where(
                Paper.user_id == user_id,
                Paper.normalized_title == normalized_title,
                Paper.year == item.year,
            )
        )
    )
    if not candidates:
        return None
    first_author = item.creators[0].casefold().strip() if item.creators else None
    for candidate in candidates:
        if doi and candidate.normalized_doi and candidate.normalized_doi != doi:
            continue
        stored_first = db.scalar(
            select(Author.display_name)
            .join(PaperAuthor, PaperAuthor.author_id == Author.id)
            .where(PaperAuthor.paper_id == candidate.id, PaperAuthor.position == 1)
        )
        if first_author and stored_first and stored_first.casefold().strip() == first_author:
            return candidate
    raise DomainError(
        "DUPLICATE_CANDIDATE",
        "A paper with the same title and year needs manual merge review",
        409,
        details={"candidate_paper_ids": [str(paper.id) for paper in candidates]},
    )


def _add_source_tags(db: Session, user_id: uuid.UUID, paper_id: uuid.UUID, item: ReferenceItem) -> None:
    # EntityTag has no source provenance. Never remove tags that may have been added by hand.
    pending_links = {
        (link.entity_id, link.tag_id) for link in db.new if isinstance(link, EntityTag)
    }
    normalized_names: set[str] = set()
    for raw_name in item.tags:
        name = raw_name.strip().lstrip("#").strip()[:80]
        if not name:
            continue
        normalized = name.casefold()
        if normalized in normalized_names:
            continue
        normalized_names.add(normalized)
        tag = db.scalar(
            select(Tag).where(Tag.user_id == user_id, Tag.normalized_name == normalized)
        )
        if tag is None:
            tag = Tag(user_id=user_id, name=name, normalized_name=normalized)
            db.add(tag)
            db.flush()
        identity = (paper_id, tag.id)
        if identity not in pending_links and db.get(EntityTag, identity) is None:
            db.add(EntityTag(entity_id=paper_id, tag_id=tag.id))
            pending_links.add(identity)


def _fill_missing_identifiers(paper: Paper, item: ReferenceItem) -> None:
    doi = normalize_doi(item.doi)
    if paper.normalized_doi is None and doi:
        paper.doi = item.doi
        paper.normalized_doi = doi
    arxiv_id = _identifier(item, "arxiv")
    if paper.arxiv_id is None and arxiv_id:
        paper.arxiv_id = arxiv_id
        paper.normalized_arxiv_id = normalized_arxiv_id(arxiv_id)
    pmid = _identifier(item, "pmid")
    if paper.pmid is None and pmid:
        paper.pmid = pmid


def _editable_paper_values(paper: Paper) -> tuple[object, ...]:
    return (
        paper.abstract, paper.url, paper.year, paper.doi, paper.normalized_doi,
        paper.arxiv_id, paper.normalized_arxiv_id, paper.pmid,
    )


def _sync_item_collections(
    db: Session, user_id: uuid.UUID, server_id: str, library_type: str,
    library_id: str, source_id: uuid.UUID,
    item: ReferenceItem,
) -> None:
    data = item.raw.get("data", {})
    keys = data.get("collections", []) if isinstance(data, dict) else []
    wanted: set[uuid.UUID] = set()
    for key in keys:
        if not isinstance(key, str):
            continue
        collection = db.scalar(
            select(ZoteroCollection).where(
                ZoteroCollection.user_id == user_id,
                ZoteroCollection.server_id == server_id,
                ZoteroCollection.library_type == library_type,
                ZoteroCollection.library_id == library_id,
                ZoteroCollection.collection_key == key,
            )
        )
        if collection is None:
            collection = ZoteroCollection(
                user_id=user_id, server_id=server_id, library_type=library_type,
                library_id=library_id, collection_key=key, name=key,
            )
            db.add(collection)
            db.flush()
        wanted.add(collection.id)
    existing = list(
        db.scalars(
            select(ZoteroItemCollection).where(ZoteroItemCollection.source_item_id == source_id)
        )
    )
    existing_ids = {link.collection_id for link in existing}
    for link in existing:
        if link.collection_id not in wanted:
            db.delete(link)
    for collection_id in wanted - existing_ids:
        db.add(ZoteroItemCollection(source_item_id=source_id, collection_id=collection_id))


async def _sync_one(
    db: Session, user_id: uuid.UUID, server_id: str, library_type: str,
    library_id: str, item: ReferenceItem,
    provider: ReferenceManagerProvider, *, check_attachment: bool,
    attachment_changed_hint: bool = False,
    indexed_attachments: list[ReferenceAttachment] | None = None,
) -> tuple[str, uuid.UUID, bool, bool]:
    if item.item_type in CHILD_TYPES:
        raise DomainError("VALIDATION_ERROR", "Child Zotero items are not papers", 422)
    existing = _source_item(db, user_id, server_id, library_type, library_id, item.key)
    if existing is not None and item.version < existing.item_version:
        source = db.get(PaperSource, existing.paper_source_id)
        assert source is not None
        return "skipped", source.paper_id, False, False
    attachments = (
        indexed_attachments if indexed_attachments is not None
        else await provider.list_attachments(item.key) if check_attachment else []
    )
    pdfs = [attachment for attachment in attachments if attachment.content_type == "application/pdf"]
    content_changed = False
    content_change_unknown = False
    paper_before = None
    if existing is None:
        paper = _find_paper(db, user_id, item)
        if paper is None:
            paper = create_paper(
                db, user_id,
                PaperCreate(
                    title=item.title, year=item.year, venue_name=item.venue,
                    authors=list(item.creators), doi=item.doi,
                    arxiv_id=_identifier(item, "arxiv"), abstract=item.abstract,
                    url=item.url, tags=[],
                ),
                commit=False,
            )
            paper.pmid = _identifier(item, "pmid")
            # A newly created paper has a new metadata/abstract analysis input.
            content_changed = True
        else:
            paper_before = _editable_paper_values(paper)
            if paper.abstract is None and item.abstract:
                paper.abstract = item.abstract
                content_changed = True
        provider_id = _source_identity(server_id, library_type, library_id, item.key)
        source = PaperSource(
            user_id=user_id, paper_id=paper.id,
            provider_key=provider.provider_key, provider_id=provider_id,
            source_version=item.version, source_url=item.url,
        )
        db.add(source)
        db.flush()
        existing = ZoteroSourceItem(
            user_id=user_id, paper_source_id=source.id, server_id=server_id,
            library_type=library_type, library_id=library_id,
            item_key=item.key, item_version=item.version, sync_status="NEW",
        )
        db.add(existing)
        db.flush()
        result = "created"
    else:
        source = db.get(PaperSource, existing.paper_source_id)
        assert source is not None
        paper = db.get(Paper, source.paper_id)
        assert paper is not None
        paper_before = _editable_paper_values(paper)
        doi = normalize_doi(item.doi)
        if doi and paper.normalized_doi and doi != paper.normalized_doi:
            raise DomainError("DUPLICATE_CANDIDATE", "Zotero DOI conflicts with linked paper", 409)
        result = "updated" if item.version > existing.item_version else "skipped"
        if result == "updated":
            existing.item_version = item.version
            existing.sync_status = "UPDATED"
            source.source_version = item.version
            source.source_url = item.url
            source.fetched_at = datetime.now(UTC)
            # Fill only missing values; never overwrite user edits or other sources.
            if paper.abstract is None and item.abstract:
                paper.abstract = item.abstract
                content_changed = True
            elif item.abstract and paper.abstract and item.abstract != paper.abstract:
                # Paper may contain a user correction or metadata from another source.
                content_change_unknown = True
    if result != "skipped":
        _fill_missing_identifiers(paper, item)
        if paper.url is None and item.url:
            paper.url = item.url
        if paper.year is None and item.year:
            paper.year = item.year
        if paper_before is not None and _editable_paper_values(paper) != paper_before:
            paper.version += 1
        _sync_item_collections(
            db, user_id, server_id, library_type, library_id, existing.id, item
        )
        _add_source_tags(db, user_id, paper.id, item)
    capture_fields(db, user_id, existing, item.venue_fields, item.version)
    if check_attachment:
        if not pdfs:
            attachment_status = "MISSING"
        else:
            downloaded = {
                (key, version)
                for key, version in db.execute(
                    select(PaperAttachment.attachment_key, PaperAttachment.source_version).where(
                        PaperAttachment.source_item_id == existing.id,
                        PaperAttachment.status == "DOWNLOADED",
                    )
                )
            }
            attachment_status = (
                "DOWNLOADED"
                if all((attachment.key, attachment.version) in downloaded for attachment in pdfs)
                else "AVAILABLE"
            )
            if attachment_status == "AVAILABLE":
                if existing.attachment_status in {"UNKNOWN", "MISSING", "DOWNLOADED"}:
                    content_changed = True
                elif result == "updated" or attachment_changed_hint:
                    # No source-level PDF version snapshot exists for uncopied files.
                    content_change_unknown = True
        if existing.attachment_status != attachment_status:
            existing.attachment_status = attachment_status
            result = "updated" if result == "skipped" else result
    existing.last_synced_at = datetime.now(UTC)
    if result == "skipped":
        existing.sync_status = "SYNCED"
    return result, paper.id, content_changed, content_change_unknown


async def _sync_collections(
    db: Session, user_id: uuid.UUID, server_id: str, library_type: str,
    library_id: str, provider: ReferenceManagerProvider,
) -> None:
    start = 0
    while True:
        records = await provider.list_collections(PAGE_SIZE, start)
        for record in records:
            collection = db.scalar(
                select(ZoteroCollection).where(
                    ZoteroCollection.user_id == user_id,
                    ZoteroCollection.server_id == server_id,
                    ZoteroCollection.library_type == library_type,
                    ZoteroCollection.library_id == library_id,
                    ZoteroCollection.collection_key == record.key,
                )
            )
            if collection is None:
                collection = ZoteroCollection(
                    user_id=user_id, server_id=server_id,
                    library_type=library_type, library_id=library_id,
                    collection_key=record.key, name=record.name,
                    parent_collection_key=record.parent_key,
                )
                db.add(collection)
            else:
                collection.name = record.name
                collection.parent_collection_key = record.parent_key
                collection.last_synced_at = datetime.now(UTC)
        start += len(records)
        if len(records) < PAGE_SIZE:
            break
        if start > MAX_CHANGED_ROWS:
            raise DomainError("SYNC_LIMIT", "Too many Zotero collections in one pass", 409)
    db.commit()


async def _changed_items(
    provider: IncrementalReferenceManagerProvider, since: int | None,
) -> tuple[list[ReferenceItem], int, set[str]]:
    start = 0
    snapshot: int | None = None
    items: dict[str, ReferenceItem] = {}
    child_parents: set[str] = set()
    while True:
        page = await provider.list_updated_items(since, PAGE_SIZE, start)
        if page.library_version is None:
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "Zotero did not return a library version", 503
            )
        if snapshot is None:
            snapshot = page.library_version
        elif page.library_version != snapshot:
            raise DomainError(
                "LIBRARY_CHANGED", "Zotero changed during pagination; retry the sync", 409
            )
        for item in page.items:
            if item.version <= snapshot:
                items[item.key] = item
        child_parents.update(page.changed_parent_keys)
        start += page.raw_count
        if page.raw_count < PAGE_SIZE:
            break
        if start >= MAX_CHANGED_ROWS:
            raise DomainError("SYNC_LIMIT", "Too many changed Zotero items in one pass", 409)
    for parent_key in sorted(child_parents - items.keys()):
        parent = await provider.get_item(parent_key)
        if parent is not None and parent.item_type not in CHILD_TYPES:
            items[parent_key] = parent
    assert snapshot is not None
    return list(items.values()), snapshot, child_parents


def _result(
    job: SyncJob, errors: list[dict[str, object]], paper_ids: list[uuid.UUID],
    content_changed_ids: list[uuid.UUID], unknown_ids: list[uuid.UUID],
    *, has_more: bool = False, candidate_item_keys: list[str] | None = None,
) -> SyncResult:
    return SyncResult(
        job_id=job.id, status=job.status, cursor_before=job.cursor_before,
        cursor_after=job.cursor_after, scanned=job.scanned_count,
        created=job.created_count, updated=job.updated_count,
        skipped=job.skipped_count, failed=job.failed_count,
        errors=tuple(errors), paper_ids=tuple(paper_ids),
        content_changed_paper_ids=tuple(dict.fromkeys(content_changed_ids)),
        content_change_unknown_paper_ids=tuple(dict.fromkeys(unknown_ids)),
        has_more=has_more,
        candidate_item_keys=tuple(dict.fromkeys(candidate_item_keys or [])),
    )


def advance_cursor(
    db: Session, user_id: uuid.UUID, server_id: str, library_type: str,
    library_id: str, snapshot: int,
) -> str:
    """Atomically retain the greatest successfully imported library snapshot."""
    identity = (
        ZoteroSyncCursor.user_id == user_id,
        ZoteroSyncCursor.server_id == server_id,
        ZoteroSyncCursor.library_type == library_type,
        ZoteroSyncCursor.library_id == library_id,
    )
    cursor = db.scalar(select(ZoteroSyncCursor).where(*identity))
    if cursor is None:
        try:
            with db.begin_nested():
                cursor = ZoteroSyncCursor(
                    user_id=user_id, server_id=server_id, library_type=library_type,
                    library_id=library_id,
                )
                db.add(cursor)
                db.flush()
        except IntegrityError:
            cursor = db.scalar(select(ZoteroSyncCursor).where(*identity))
    db.execute(
        update(ZoteroSyncCursor).where(
            *identity,
            or_(ZoteroSyncCursor.cursor.is_(None), cast(ZoteroSyncCursor.cursor, BigInteger) <= snapshot),
        ).values(cursor=str(snapshot), last_success_at=datetime.now(UTC), last_error=None),
        execution_options={"synchronize_session": False},
    )
    assert cursor is not None
    db.refresh(cursor)
    return cursor.cursor or str(snapshot)


async def sync_zotero(
    db: Session, user_id: uuid.UUID, provider: ReferenceManagerProvider,
    *, item_key: str | None = None, idempotency_key: str | None = None,
    max_items: int | None = None,
    on_content_change: Callable[[Session, ReferenceItem], Awaitable[None]] | None = None,
) -> SyncResult:
    """Synchronize one paper or a full changed-item pass from a read-only provider."""
    if provider.provider_key not in {"zotero_local", "zotero_web"}:
        raise DomainError("CAPABILITY_UNAVAILABLE", "Unsupported Zotero provider", 501)
    if item_key is None and not isinstance(provider, IncrementalReferenceManagerProvider):
        raise DomainError(
            "CAPABILITY_UNAVAILABLE", "This Zotero provider has no incremental cursor", 501
        )
    if max_items is not None and not 1 <= max_items <= 1000:
        raise DomainError("VALIDATION_ERROR", "max_items must be between 1 and 1000", 422)
    stored_key: str | None = None
    try:
        status = await provider.status()
        server_id = status.get("server_id")
        if not isinstance(server_id, str) or not server_id:
            raise DomainError("PROVIDER_UNAVAILABLE", "Zotero instance ID is unavailable", 503)
        library_type = status.get("library_type") or LOCAL_LIBRARY_TYPE
        library_id = status.get("library_id") or LOCAL_LIBRARY_ID
        if (
            not isinstance(library_type, str)
            or library_type not in {"user", "group"}
            or not isinstance(library_id, str)
            or not library_id
            or (provider.provider_key == "zotero_local" and
                (library_type, library_id) != (LOCAL_LIBRARY_TYPE, LOCAL_LIBRARY_ID))
        ):
            raise DomainError("PROVIDER_UNAVAILABLE", "Invalid Zotero library identity", 503)
    except Exception as exc:
        code = exc.code if isinstance(exc, DomainError) else "PROVIDER_UNAVAILABLE"
        message = safe_sync_error(exc)
        failed = SyncJob(
            user_id=user_id, provider_key=provider.provider_key,
            job_type="SINGLE_ITEM" if item_key else "INCREMENTAL",
            status="FAILED", idempotency_key=stored_key,
            error_code=code, error_message=message,
            started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
        )
        db.add(failed)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if stored_key is None:
                raise
            previous = db.scalar(
                select(SyncJob).where(
                    SyncJob.user_id == user_id, SyncJob.idempotency_key == stored_key
                )
            )
            if previous is None:
                raise
            return _result(previous, [], [], [], [])
        return _result(failed, [{"key": "connection", "error": message}], [], [], [])
    stored_key = _job_key(
        idempotency_key, item_key, provider.provider_key,
        server_id, library_type, library_id,
    )
    if stored_key:
        previous = db.scalar(
            select(SyncJob).where(
                SyncJob.user_id == user_id, SyncJob.idempotency_key == stored_key
            )
        )
        if previous is not None:
            persisted_errors: list[dict[str, object]] = []
            if previous.error_message:
                try:
                    persisted_errors = json.loads(previous.error_message)
                except (ValueError, TypeError):
                    persisted_errors = [{"key": "batch", "error": previous.error_message}]
            return _result(previous, persisted_errors, [], [], [])
    cursor = db.scalar(
        select(ZoteroSyncCursor).where(
            ZoteroSyncCursor.user_id == user_id,
            ZoteroSyncCursor.server_id == server_id,
            ZoteroSyncCursor.library_type == library_type,
            ZoteroSyncCursor.library_id == library_id,
        )
    )
    before = cursor.cursor if cursor is not None else None
    job = SyncJob(
        user_id=user_id, provider_key=provider.provider_key,
        job_type="SINGLE_ITEM" if item_key else "INCREMENTAL",
        status="RUNNING", cursor_before=before,
        idempotency_key=stored_key, started_at=datetime.now(UTC),
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if stored_key is None:
            raise
        previous = db.scalar(
            select(SyncJob).where(
                SyncJob.user_id == user_id, SyncJob.idempotency_key == stored_key
            )
        )
        if previous is None:
            raise
        return _result(previous, [], [], [], [])
    errors: list[dict[str, object]] = []
    paper_ids: list[uuid.UUID] = []
    content_changed_ids: list[uuid.UUID] = []
    unknown_ids: list[uuid.UUID] = []
    candidate_item_keys: list[str] = []
    has_more = False
    effective_count = 0
    try:
        if item_key:
            item = await provider.get_item(item_key)
            if item is None or item.item_type in CHILD_TYPES:
                raise DomainError("NOT_FOUND", "Zotero paper item not found", 404)
            items, snapshot, changed_parent_keys = [item], None, set[str]()
        else:
            await _sync_collections(
                db, user_id, server_id, library_type, library_id, provider
            )
            assert isinstance(provider, IncrementalReferenceManagerProvider)
            items, snapshot, changed_parent_keys = await _changed_items(
                provider, int(before) if before else None
            )
        for item in items:
            if max_items is not None and effective_count >= max_items:
                has_more = True
                break
            job.scanned_count += 1
            try:
                # The savepoint keeps each bad source from poisoning the session.
                with db.begin_nested():
                    outcome, paper_id, content_changed, unknown = await _sync_one(
                        db, user_id, server_id, library_type, library_id,
                        item, provider, check_attachment=True,
                        attachment_changed_hint=item.key in changed_parent_keys,
                    )
                    if on_content_change is not None and (content_changed or unknown):
                        await on_content_change(db, item)
                paper_ids.append(paper_id)
                if content_changed:
                    content_changed_ids.append(paper_id)
                if unknown:
                    unknown_ids.append(paper_id)
                if content_changed or unknown:
                    candidate_item_keys.append(item.key)
                if outcome == "created":
                    job.created_count += 1
                    effective_count += 1
                elif outcome == "updated":
                    job.updated_count += 1
                    effective_count += 1
                else:
                    job.skipped_count += 1
            except Exception as exc:
                job.failed_count += 1
                detail: dict[str, object] = {
                    "key": item.key,
                    "error": safe_sync_error(exc),
                }
                if isinstance(exc, DomainError):
                    detail["code"] = exc.code
                    candidates = exc.details if isinstance(exc.details, dict) else {}
                    candidate_ids = candidates.get("candidate_paper_ids")
                    if isinstance(candidate_ids, list):
                        detail["candidate_paper_ids"] = [str(candidate) for candidate in candidate_ids]
                    elif candidates.get("candidate_paper_id") is not None:
                        detail["candidate_paper_ids"] = [str(candidates["candidate_paper_id"])]
                errors.append(detail)
            db.commit()
        if errors:
            job.status = "PARTIAL"
            job.error_code = "ITEM_SYNC_FAILED"
            job.error_message = json.dumps(errors[:50], ensure_ascii=False)
            if cursor is not None:
                cursor.last_error = f"{len(errors)} Zotero items failed; cursor retained"
        else:
            job.status = "CONTINUATION" if has_more else "COMPLETED"
            if snapshot is not None and not has_more:
                # A remote update during item/attachment processing must not
                # advance the cursor past data we have not imported.
                assert isinstance(provider, IncrementalReferenceManagerProvider)
                observed = await provider.list_updated_items(snapshot, 1, 0)
                if observed.library_version != snapshot:
                    raise DomainError(
                        "LIBRARY_CHANGED", "Zotero changed during sync; retry the sync", 409
                    )
                job.cursor_after = advance_cursor(
                    db, user_id, server_id, library_type, library_id, snapshot
                )
        job.completed_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        job.status = "FAILED"
        job.error_code = exc.code if isinstance(exc, DomainError) else "SYNC_FAILED"
        job.error_message = safe_sync_error(exc)
        job.completed_at = datetime.now(UTC)
        if cursor is not None:
            cursor.last_error = job.error_message
        db.commit()
        errors.append({"key": "batch", "error": job.error_message})
    return _result(
        job, errors, paper_ids, content_changed_ids, unknown_ids,
        has_more=has_more, candidate_item_keys=candidate_item_keys,
    )
