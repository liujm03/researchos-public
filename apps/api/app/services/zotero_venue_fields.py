import hashlib
import json
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.reference_manager import ReferenceManagerProvider
from app.errors import DomainError
from app.models import Paper, PaperSource, ResearchEvent, ZoteroSourceItem
from app.providers.reference_manager.venue_fields_registry import get_reference_venue_field_provider
from app.providers.registry import reference_manager
from app.schemas_venue_ratings import VenueAssessmentOut
from app.services.papers import get_paper


def capture_fields(
    db: Session,
    user_id: uuid.UUID,
    source: ZoteroSourceItem,
    fields: dict[str, str] | None,
    version: int,
) -> bool:
    if source.user_id != user_id:
        raise DomainError("NOT_FOUND", "Zotero source not found", 404)
    if fields is None:
        return False
    if version < 0 or (
        source.venue_fields_version is not None and version < source.venue_fields_version
    ):
        raise DomainError("ZOTERO_VERSION_STALE", "Zotero字段版本较旧，保留已有记录", 409)
    raw = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if (
        len(fields) > 40
        or len(raw.encode()) > 16_384
        or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in fields.items()
        )
    ):
        raise DomainError("ZOTERO_FIELDS_LIMIT", "Zotero期刊字段超出安全读取范围", 422)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    if (
        source.venue_fields_sha256 == digest
        and source.venue_fields_version == version
        and source.venue_fields == fields
    ):
        return False
    previous = {
        "fields": source.venue_fields,
        "sha256": source.venue_fields_sha256,
        "version": source.venue_fields_version,
    }
    source.venue_fields = dict(fields)
    source.venue_fields_sha256 = digest
    source.venue_fields_version = version
    source.venue_fields_synced_at = datetime.now(UTC)
    db.flush()
    parent = db.get(PaperSource, source.paper_source_id)
    if parent is None or parent.user_id != user_id:
        raise DomainError("NOT_FOUND", "Zotero source not found", 404)
    db.add(
        ResearchEvent(
            event_id=uuid.uuid4(),
            user_id=user_id,
            event_type="ZOTERO_VENUE_FIELDS_UPDATED",
            occurred_at=source.venue_fields_synced_at,
            source="zotero-metadata",
            paper_id=parent.paper_id if parent else None,
            payload={
                "source_item_id": str(source.id),
                "item_key": source.item_key,
                "before": previous,
                "after": {"fields": dict(fields), "sha256": digest, "version": version},
            },
        )
    )
    return True


def fields_for_paper(db: Session, user_id: uuid.UUID, paper: Paper) -> list[VenueAssessmentOut]:
    if paper.user_id != user_id:
        raise DomainError("NOT_FOUND", "Paper not found", 404)
    rows = db.scalars(
        select(ZoteroSourceItem)
        .join(PaperSource, PaperSource.id == ZoteroSourceItem.paper_source_id)
        .where(
            ZoteroSourceItem.user_id == user_id,
            PaperSource.user_id == user_id,
            PaperSource.paper_id == paper.id,
        )
    )
    result: list[VenueAssessmentOut] = []
    port = get_reference_venue_field_provider()
    for source in rows:
        if source.venue_fields is None or source.venue_fields_synced_at is None:
            continue
        raw = json.dumps(
            source.venue_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if hashlib.sha256(raw.encode()).hexdigest() != source.venue_fields_sha256:
            raise DomainError(
                "ZOTERO_FIELDS_INTEGRITY", "Zotero字段快照校验失败，请重新读取字段", 409
            )
        if not re.fullmatch(r"[A-Z0-9]{8}", source.item_key):
            continue
        for rating in port.ratings(source.venue_fields):
            result.append(
                VenueAssessmentOut.model_validate(
                    rating
                    | {
                        "source_kind": "ZOTERO_METADATA",
                        "source_url": f"/integrations/zotero?item={source.item_key}",
                        "source_label": "Zotero / Ethereal Style缓存（未独立核验）"
                        if str(rating.get("raw_field", "")).startswith("plugin:")
                        else "Zotero原字段（未独立核验）",
                        "checked_at": source.venue_fields_synced_at,
                        "source_item_key": source.item_key,
                        "source_version": source.venue_fields_version,
                    }
                )
            )
    return result


async def refresh_fields(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    provider: ReferenceManagerProvider | None = None,
) -> Paper:
    paper = get_paper(db, user_id, paper_id)
    sources = list(
        db.scalars(
            select(ZoteroSourceItem)
            .join(PaperSource, PaperSource.id == ZoteroSourceItem.paper_source_id)
            .where(
                ZoteroSourceItem.user_id == user_id,
                PaperSource.user_id == user_id,
                PaperSource.paper_id == paper.id,
            )
            .order_by(ZoteroSourceItem.id)
        )
    )
    if not sources:
        raise DomainError("ZOTERO_SOURCE_REQUIRED", "这篇论文尚未关联Zotero条目，请先关联", 422)
    if len(sources) > 20:
        raise DomainError("ZOTERO_SOURCE_LIMIT", "关联条目过多，请先整理重复来源", 409)
    port = provider or reference_manager()
    status = await port.status()
    server_id = status.get("server_id")
    if not isinstance(server_id, str):
        raise DomainError("PROVIDER_UNAVAILABLE", "Zotero未运行或本地API不可用，保留已有字段", 503)
    fetched: list[tuple[ZoteroSourceItem, dict[str, str] | None, int]] = []
    for source in sources:
        if (
            source.server_id != server_id
            or source.library_type != (status.get("library_type") or "user")
            or source.library_id != (status.get("library_id") or "0")
        ):
            raise DomainError(
                "ZOTERO_IDENTITY_CHANGED", "当前Zotero文献库与已关联来源不同，保留已有字段", 409
            )
        item = await port.get_item(source.item_key)
        if (
            item is None
            or item.key != source.item_key
            or item.item_type in {"attachment", "note", "annotation"}
        ):
            raise DomainError(
                "ZOTERO_ITEM_UNAVAILABLE", "Zotero关联论文条目不可用，保留已有字段", 409
            )
        fetched.append((source, item.venue_fields, item.version))
    try:
        for source, fields, version in fetched:
            db.refresh(source)
            parent = db.get(PaperSource, source.paper_source_id)
            if parent is None or parent.user_id != user_id or parent.paper_id != paper_id:
                raise DomainError("ZOTERO_BINDING_CHANGED", "论文关联已变化，请重新加载后刷新", 409)
            capture_fields(db, user_id, source, fields, version)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return paper
