"""Owner-scoped fences for notes undergoing irreversible deletion.

Every state is fenced, including incomplete cleanup, so a retry cannot recreate
files or publish a late provider response while deletion is being recovered.
"""

import hashlib
import uuid
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.errors import DomainError


def selectable_deletion_clause(owner: Any, job_id_column: Any) -> ColumnElement[bool]:
    from app.models_note_deletion import NotePermanentDeletion

    return ~exists(
        select(NotePermanentDeletion.id).where(
            NotePermanentDeletion.user_id == owner,
            NotePermanentDeletion.reading_job_id == job_id_column,
        )
    )


def require_not_permanently_deleted(db: Session, owner: uuid.UUID, job_id: uuid.UUID) -> None:
    with db.no_autoflush:
        allowed = db.scalar(select(selectable_deletion_clause(owner, job_id)))
    if not allowed:
        raise DomainError(
            "NOTE_PERMANENTLY_DELETED",
            "This reading's notes are permanently deleted or their deletion is in progress",
            409,
        )


def require_output_path_available(
    db: Session, owner: uuid.UUID, root: str, relative_path: str
) -> None:
    """Fence the exact frozen destination until every old file cleanup is complete."""
    from app.models_note_deletion import NoteDeletionFile, NotePermanentDeletion

    lock_note_output_path(db, owner, root, relative_path)
    # Destination inputs come from approved server plans, not browser paths.
    # Windows is case-insensitive and both separator spellings identify a path.
    root_key = root.replace("\\", "/").rstrip("/").lower()
    path_key = relative_path.replace("\\", "/").lower()
    with db.no_autoflush:
        busy = db.scalar(
            select(NoteDeletionFile.id)
            .join(
                NotePermanentDeletion,
                (NotePermanentDeletion.id == NoteDeletionFile.operation_id)
                & (NotePermanentDeletion.user_id == owner),
            )
            .where(
                NoteDeletionFile.user_id == owner,
                NotePermanentDeletion.state != "COMPLETED",
                func.lower(func.rtrim(func.replace(NoteDeletionFile.root_path, "\\", "/"), "/"))
                == root_key,
                func.lower(func.replace(NoteDeletionFile.relative_path, "\\", "/")) == path_key,
            )
            .limit(1)
        )
    if busy is not None:
        raise DomainError(
            "NOTE_DELETION_IN_PROGRESS",
            "The approved note destination is still being permanently deleted; finish its cleanup first",
            409,
        )


def lock_note_output_path(db: Session, owner: uuid.UUID, root: str, relative_path: str) -> None:
    """Serialize deletion admission and new publication of one approved path."""
    if db.get_bind().dialect.name != "postgresql":
        return  # Synthetic SQLite checks do not prove concurrent filesystem safety.
    normalized = (
        str(owner),
        root.replace("\\", "/").rstrip("/").lower(),
        relative_path.replace("\\", "/").lower(),
    )
    key = int.from_bytes(
        hashlib.sha256("\0".join(normalized).encode()).digest()[:8], "big", signed=True
    )
    with db.no_autoflush:
        db.execute(select(func.pg_advisory_xact_lock(key)))
