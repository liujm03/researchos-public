"""Recoverable generated-note lifecycle; original bytes and review facts stay intact."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GeneratedFileSettings(Base):
    __tablename__ = "generated_file_settings"
    __table_args__ = (
        CheckConstraint(
            "note_delete_scope IN ('VERSION','READING_RUN')", name="ck_generated_delete_scope"
        ),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    note_delete_scope: Mapped[str] = mapped_column(
        String(16), default="READING_RUN", server_default="READING_RUN"
    )


class NoteTrashEntry(Base):
    __tablename__ = "note_trash_entries"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_note_trash_entry_owner"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_note_trash_create_key"),
        ForeignKeyConstraint(
            ["note_id", "user_id"],
            ["paper_research_notes.id", "paper_research_notes.user_id"],
            name="fk_note_trash_target_owner",
        ),
        ForeignKeyConstraint(
            ["paper_id", "user_id"],
            ["papers.id", "papers.user_id"],
            name="fk_note_trash_paper_owner",
        ),
        CheckConstraint(
            "scope IN ('VERSION','READING_RUN') AND state IN ('TRASHED','RESTORED') AND version >= 1",
            name="ck_note_trash_lifecycle",
        ),
        CheckConstraint(
            "length(preview_sha256)=64 AND length(request_sha256)=64", name="ck_note_trash_hashes"
        ),
        CheckConstraint(
            "(state='TRASHED' AND restored_at IS NULL) OR (state='RESTORED' AND restored_at IS NOT NULL)",
            name="ck_note_trash_restored",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    note_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    scope: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16), default="TRASHED")
    version: Mapped[int] = mapped_column(Integer, default=1)
    preview_sha256: Mapped[str] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    preview_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NoteTrashMember(Base):
    __tablename__ = "note_trash_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["entry_id", "user_id"],
            ["note_trash_entries.id", "note_trash_entries.user_id"],
            name="fk_note_trash_member_entry_owner",
        ),
        ForeignKeyConstraint(
            ["note_id", "user_id"],
            ["paper_research_notes.id", "paper_research_notes.user_id"],
            name="fk_note_trash_member_note_owner",
        ),
        CheckConstraint(
            "revision >= 1 AND length(content_sha256)=64", name="ck_note_trash_member_snapshot"
        ),
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    note_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(24))
    content_sha256: Mapped[str] = mapped_column(String(64))
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NoteTrashOperation(Base):
    __tablename__ = "note_trash_operations"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_note_trash_operation_key"),
        ForeignKeyConstraint(
            ["entry_id", "user_id"],
            ["note_trash_entries.id", "note_trash_entries.user_id"],
            name="fk_note_trash_operation_entry_owner",
        ),
        CheckConstraint(
            "kind IN ('TRASH','RESTORE') AND length(request_sha256)=64",
            name="ck_note_trash_operation",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
