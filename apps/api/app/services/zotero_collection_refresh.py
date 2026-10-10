"""Owner-triggered collection metadata refresh, without paper/PDF/AI processing."""

import asyncio
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.reference_manager import ReferenceCollection, ReferenceManagerProvider
from app.errors import DomainError
from app.models import ZoteroCollection
from app.schemas_literature_context import ZoteroCollectionsRefreshOut

PAGE_SIZE = 100
MAX_COLLECTIONS = 20_000
DISCOVERY_TIMEOUT_SECONDS = 60


async def _identity(provider: ReferenceManagerProvider) -> tuple[str, str, str, str]:
    if provider.provider_key not in {"zotero_local", "zotero_web"}:
        raise DomainError("CAPABILITY_UNAVAILABLE", "Unsupported Zotero provider", 501)
    status = await provider.status()
    server = status.get("server_id")
    library_type = status.get("library_type") or "user"
    library_id = status.get("library_id") or "0"
    if (
        status.get("connected") is not True
        or not isinstance(server, str) or not server or len(server) > 100
        or library_type not in {"user", "group"}
        or not isinstance(library_id, str) or not library_id or len(library_id) > 80
        or (provider.provider_key == "zotero_local" and (library_type, library_id) != ("user", "0"))
        or (provider.provider_key == "zotero_web" and not re.fullmatch(r"[1-9]\d*", library_id))
    ):
        raise DomainError("PROVIDER_UNAVAILABLE", "Invalid Zotero library identity", 503)
    return provider.provider_key, server, str(library_type), library_id


async def _discover(
    provider: ReferenceManagerProvider,
) -> tuple[tuple[str, str, str, str], list[ReferenceCollection]]:
    identity = await _identity(provider)
    records: list[ReferenceCollection] = []
    seen: set[str] = set()
    start = 0
    while True:
        if await _identity(provider) != identity:
            raise DomainError("SOURCE_CHANGED", "Zotero library changed during folder refresh", 409)
        page = await provider.list_collections(PAGE_SIZE, start)
        if await _identity(provider) != identity:
            raise DomainError("SOURCE_CHANGED", "Zotero library changed during folder refresh", 409)
        if len(page) > PAGE_SIZE or len(records) + len(page) > MAX_COLLECTIONS:
            raise DomainError("SYNC_LIMIT", "Too many Zotero collections in one refresh", 409)
        for row in page:
            if (
                not isinstance(row.key, str) or not re.fullmatch(r"[A-Z0-9]{8}", row.key)
                or not isinstance(row.name, str) or not row.name.strip() or len(row.name) > 320
                or (row.parent_key is not None and (
                    not isinstance(row.parent_key, str)
                    or not re.fullmatch(r"[A-Z0-9]{8}", row.parent_key)
                ))
            ):
                raise DomainError("PROVIDER_UNAVAILABLE", "Invalid Zotero collection metadata", 503)
            if row.key in seen:
                raise DomainError("SOURCE_CHANGED", "Repeated Zotero collection page; refresh again", 409)
            seen.add(row.key)
            records.append(row)
        start += len(page)
        if len(page) < PAGE_SIZE:
            return identity, records


async def refresh_zotero_collections(
    db: Session, user_id: uuid.UUID, provider: ReferenceManagerProvider,
) -> ZoteroCollectionsRefreshOut:
    """Fetch before mutation, then atomically create/update the exact owner/library.

    Old collection snapshots remain when absent upstream; membership removal is
    reserved for item reconciliation. No paper, attachment or project is modified.
    """
    if db.new or db.dirty or db.deleted:
        raise DomainError("CONFLICT", "Finish pending database changes before folder refresh", 409)
    try:
        async with asyncio.timeout(DISCOVERY_TIMEOUT_SECONDS):
            identity, records = await _discover(provider)
    except TimeoutError as exc:
        raise DomainError("PROVIDER_UNAVAILABLE", "Zotero folder refresh timed out; retry", 503) from exc
    provider_key, server_id, library_type, library_id = identity
    now = datetime.now(UTC)
    # A simultaneous refresh may insert the same unique source identity first.
    # Retry only the local atomic transaction once, using the already fetched snapshot.
    for attempt in range(2):
        try:
            existing = list(db.scalars(select(ZoteroCollection).where(
                ZoteroCollection.server_id == server_id,
                ZoteroCollection.library_type == library_type,
                ZoteroCollection.library_id == library_id,
            ).with_for_update()))
            by_key = {row.collection_key: row for row in existing}
            created = updated = unchanged = 0
            for record in records:
                row = by_key.get(record.key)
                if row is not None and row.user_id != user_id:
                    raise DomainError("SOURCE_SCOPE_CONFLICT", "Zotero collection belongs to another owner", 409)
                if row is None:
                    row = ZoteroCollection(
                        user_id=user_id, server_id=server_id, library_type=library_type,
                        library_id=library_id, collection_key=record.key, name=record.name,
                        parent_collection_key=record.parent_key, last_synced_at=now,
                    )
                    db.add(row)
                    created += 1
                else:
                    if (row.name, row.parent_collection_key) == (record.name, record.parent_key):
                        unchanged += 1
                    else:
                        updated += 1
                    row.name = record.name
                    row.parent_collection_key = record.parent_key
                    row.last_synced_at = now
            db.commit()
            return ZoteroCollectionsRefreshOut(
                provider_key=provider_key, server_id=server_id, library_type=library_type,
                library_id=library_id, created=created, updated=updated, unchanged=unchanged,
                total=len(records), refreshed_at=now,
            )
        except IntegrityError:
            db.rollback()
            if attempt:
                raise DomainError("CONFLICT", "Concurrent Zotero folder update; refresh again", 409) from None
        except Exception:
            db.rollback()
            raise
    raise AssertionError("Atomic refresh retry exhausted")
