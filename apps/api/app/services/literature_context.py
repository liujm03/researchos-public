"""Batch local provenance projection; never searches Zotero or guesses identities."""

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import exists, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    Paper,
    PaperSource,
    ProjectPaper,
    ResearchEntity,
    ResearchProject,
    ZoteroCollection,
    ZoteroItemCollection,
    ZoteroSourceItem,
)
from app.schemas_literature_context import (
    LiteratureClassificationOptionsOut,
    LiteratureProjectOut,
    PaperLiteratureContextOut,
    ZoteroClassificationOptionOut,
    ZoteroCollectionPathOut,
    ZoteroCollectionSegmentOut,
    ZoteroPaperSourceOut,
)

LibraryIdentity = tuple[str, str, str]
CollectionIdentity = tuple[str, str, str, str]


def zotero_collection_paper_filter(
    user_id: uuid.UUID, collection_id: uuid.UUID, family_ids: Sequence[uuid.UUID] | None = None
) -> ColumnElement[bool]:
    """Correlated Paper filter for one exact synchronized collection identity."""
    return exists(
        select(ZoteroSourceItem.id)
        .join(PaperSource, ZoteroSourceItem.paper_source_id == PaperSource.id)
        .join(ZoteroItemCollection, ZoteroItemCollection.source_item_id == ZoteroSourceItem.id)
        .join(ZoteroCollection, ZoteroCollection.id == ZoteroItemCollection.collection_id)
        .where(
            PaperSource.paper_id == Paper.id,
            Paper.user_id == user_id,
            PaperSource.user_id == user_id,
            ZoteroSourceItem.user_id == user_id,
            ZoteroCollection.user_id == user_id,
            ZoteroCollection.id.in_(family_ids if family_ids is not None else [collection_id]),
            ZoteroCollection.server_id == ZoteroSourceItem.server_id,
            ZoteroCollection.library_type == ZoteroSourceItem.library_type,
            ZoteroCollection.library_id == ZoteroSourceItem.library_id,
        )
    )


def collection_family_ids(
    db: Session, user_id: uuid.UUID, collection_id: uuid.UUID
) -> list[uuid.UUID]:
    """Resolve one owned library subtree; cycles stop at visited keys."""
    root = db.scalar(
        select(ZoteroCollection).where(
            ZoteroCollection.id == collection_id,
            ZoteroCollection.user_id == user_id,
        )
    )
    if root is None:
        return []
    rows = list(
        db.scalars(
            select(ZoteroCollection).where(
                ZoteroCollection.user_id == user_id,
                ZoteroCollection.server_id == root.server_id,
                ZoteroCollection.library_type == root.library_type,
                ZoteroCollection.library_id == root.library_id,
            )
        )
    )
    children: dict[str, list[ZoteroCollection]] = defaultdict(list)
    for row in rows:
        if row.parent_collection_key:
            children[row.parent_collection_key].append(row)
    result, pending, seen = [root.id], [root.collection_key], {root.collection_key}
    while pending:
        for child in children.get(pending.pop(), []):
            if child.collection_key not in seen:
                seen.add(child.collection_key)
                result.append(child.id)
                pending.append(child.collection_key)
    return result


def _library(row: ZoteroCollection | ZoteroSourceItem) -> LibraryIdentity:
    return row.server_id, row.library_type, row.library_id


def _collection_identity(row: ZoteroCollection) -> CollectionIdentity:
    return *_library(row), row.collection_key


def _path(
    collection: ZoteroCollection, by_identity: dict[CollectionIdentity, ZoteroCollection]
) -> ZoteroCollectionPathOut:
    """An unresolved parent never becomes a fabricated complete folder path."""
    segments: list[ZoteroCollectionSegmentOut] = []
    seen: set[str] = set()
    current = collection
    result = ZoteroCollectionPathOut(
        collection_id=collection.id,
        collection_key=collection.collection_key,
        segments=[],
        path="",
        status="COMPLETE",
    )
    incomplete = False
    while True:
        if current.collection_key in seen:
            result.status = "CYCLE"
            break
        seen.add(current.collection_key)
        segments.append(ZoteroCollectionSegmentOut(key=current.collection_key, name=current.name))
        # Sync creates key-only placeholders until collection metadata becomes available.
        incomplete |= not current.name.strip() or (
            current.source_version is None and current.name == current.collection_key
        )
        if not current.parent_collection_key:
            if incomplete:
                result.status = "METADATA_INCOMPLETE"
            break
        parent = by_identity.get((*_library(current), current.parent_collection_key))
        if parent is None:
            result.status = "MISSING_PARENT"
            result.missing_parent_key = current.parent_collection_key
            break
        current = parent
    result.segments = list(reversed(segments))
    result.path = " / ".join(segment.name for segment in result.segments)
    return result


def project_literature_contexts(
    db: Session, user_id: uuid.UUID, paper_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, PaperLiteratureContextOut]:
    """Return only owned visible papers, with constant query count per batch.

    Collections reflect the last synchronized local snapshot. No membership recorded
    is deliberately distinct from proving a paper belongs to Zotero's library root.
    """
    if not paper_ids:
        return {}
    owned = list(
        db.scalars(
            select(Paper.id)
            .join(ResearchEntity, ResearchEntity.id == Paper.id)
            .where(
                Paper.user_id == user_id,
                Paper.id.in_(set(paper_ids)),
                ResearchEntity.user_id == user_id,
                ResearchEntity.deleted_at.is_(None),
            )
        )
    )
    contexts = {paper_id: PaperLiteratureContextOut() for paper_id in owned}
    if not owned:
        return contexts
    source_rows = list(
        db.execute(
            select(PaperSource.paper_id, ZoteroSourceItem)
            .join(ZoteroSourceItem, ZoteroSourceItem.paper_source_id == PaperSource.id)
            .where(
                PaperSource.user_id == user_id,
                PaperSource.paper_id.in_(owned),
                ZoteroSourceItem.user_id == user_id,
            )
            .order_by(
                ZoteroSourceItem.server_id,
                ZoteroSourceItem.library_type,
                ZoteroSourceItem.library_id,
                ZoteroSourceItem.item_key,
            )
        )
    )
    if source_rows:
        source_ids = [source.id for _, source in source_rows]
        identities = {_library(source) for _, source in source_rows}
        collections = list(
            db.scalars(
                select(ZoteroCollection).where(
                    ZoteroCollection.user_id == user_id,
                    tuple_(
                        ZoteroCollection.server_id,
                        ZoteroCollection.library_type,
                        ZoteroCollection.library_id,
                    ).in_(identities),
                )
            )
        )
        by_id = {row.id: row for row in collections}
        by_identity = {_collection_identity(row): row for row in collections}
        paths: dict[uuid.UUID, ZoteroCollectionPathOut] = {}
        memberships: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for link in db.scalars(
            select(ZoteroItemCollection).where(ZoteroItemCollection.source_item_id.in_(source_ids))
        ):
            memberships[link.source_item_id].append(link.collection_id)
        for paper_id, source in source_rows:
            source_out = ZoteroPaperSourceOut(
                source_item_id=source.id,
                server_id=source.server_id,
                library_type=source.library_type,
                library_id=source.library_id,
                item_key=source.item_key,
                item_version=source.item_version,
                last_synced_at=source.last_synced_at,
                collection_status="NO_MEMBERSHIP_RECORDED",
            )
            for collection_id in memberships[source.id]:
                collection = by_id.get(collection_id)
                if collection is None or _library(collection) != _library(source):
                    source_out.collection_status = "INVALID_SCOPE"
                    continue
                if source_out.collection_status != "INVALID_SCOPE":
                    source_out.collection_status = "KNOWN"
                if collection_id not in paths:
                    paths[collection_id] = _path(collection, by_identity)
                source_out.collections.append(paths[collection_id])
            source_out.collections.sort(
                key=lambda path: (path.path.casefold(), path.collection_key)
            )
            contexts[paper_id].zotero_status = "LINKED"
            contexts[paper_id].zotero_sources.append(source_out)
    project_rows = db.execute(
        select(ProjectPaper.paper_id, ResearchProject.id, ResearchProject.name)
        .join(ResearchProject, ProjectPaper.project_id == ResearchProject.id)
        .join(ResearchEntity, ResearchEntity.id == ResearchProject.id)
        .where(
            ProjectPaper.paper_id.in_(owned),
            ResearchProject.user_id == user_id,
            ResearchEntity.user_id == user_id,
            ResearchEntity.deleted_at.is_(None),
        )
        .distinct()
        .order_by(ResearchProject.name, ResearchProject.id)
    )
    for paper_id, project_id, name in project_rows:
        contexts[paper_id].projects.append(LiteratureProjectOut(id=project_id, name=name))
        contexts[paper_id].classification_status = "CLASSIFIED"
    return contexts


def classification_options(db: Session, user_id: uuid.UUID) -> LiteratureClassificationOptionsOut:
    """Local synchronized folder choices and visible owned projects, without I/O."""
    projects = list(
        db.scalars(
            select(ResearchProject)
            .join(ResearchEntity, ResearchEntity.id == ResearchProject.id)
            .where(
                ResearchProject.user_id == user_id,
                ResearchEntity.user_id == user_id,
                ResearchEntity.deleted_at.is_(None),
            )
            .order_by(ResearchProject.name, ResearchProject.id)
        )
    )
    collections = list(
        db.scalars(
            select(ZoteroCollection).where(
                ZoteroCollection.user_id == user_id,
            )
        )
    )
    by_identity = {_collection_identity(row): row for row in collections}
    options = []
    for row in collections:
        path = _path(row, by_identity)
        options.append(
            ZoteroClassificationOptionOut(
                collection_id=row.id,
                server_id=row.server_id,
                library_type=row.library_type,
                library_id=row.library_id,
                collection_key=row.collection_key,
                path=path.path,
                status=path.status,
            )
        )
    options.sort(
        key=lambda row: (
            row.server_id,
            row.library_type,
            row.library_id,
            row.path.casefold(),
            row.collection_key,
        )
    )
    return LiteratureClassificationOptionsOut(
        projects=[LiteratureProjectOut(id=row.id, name=row.name) for row in projects],
        collections=options,
    )
