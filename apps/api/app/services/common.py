import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ResearchEntity


def register_entity(db: Session, user_id: uuid.UUID, kind: str) -> uuid.UUID:
    entity_id = uuid.uuid4()
    db.add(ResearchEntity(id=entity_id, user_id=user_id, kind=kind))
    # Domain rows reference this id but do not have ORM relationships to it.
    # Persist the parent first so a later flush cannot insert a child before it.
    db.flush()
    return entity_id


def assert_version(current: int, if_match: str | None) -> None:
    if if_match is None:
        raise DomainError("PRECONDITION_REQUIRED", "If-Match version is required", 428)
    try:
        expected = int(if_match.strip('"'))
    except ValueError as exc:
        raise DomainError("VALIDATION_ERROR", "Invalid If-Match version", 422) from exc
    if expected != current:
        raise DomainError("CONFLICT", "This record changed; reload before saving", 409)


def encode_cursor(created_at: datetime, entity_id: uuid.UUID) -> str:
    payload = json.dumps([created_at.isoformat(), str(entity_id)]).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        timestamp, item_id = json.loads(raw)
        return datetime.fromisoformat(timestamp), uuid.UUID(item_id)
    except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
        raise DomainError("VALIDATION_ERROR", "Invalid page cursor", 422) from exc


def cursor_filter(model: Any, cursor: str | None) -> Any:
    if cursor is None:
        return True
    created_at, item_id = decode_cursor(cursor)
    return tuple_(model.created_at, model.id) < (created_at, item_id)
