"""Content-free receipts for irreversible, owner-selected generated-note deletion."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NotePermanentDeletion(Base):
    __tablename__ = "note_permanent_deletions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_note_deletion_owner"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_note_deletion_request"),
        UniqueConstraint("user_id", "family_key", name="uq_note_deletion_family"),
        ForeignKeyConstraint(
            ["paper_id", "user_id"],
            ["papers.id", "papers.user_id"],
            name="fk_note_deletion_paper_owner",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_note_deletion_job_owner",
        ),
        CheckConstraint(
            "state IN ('DELETING','COMPLETED','FAILED','NEEDS_ATTENTION')",
            name="ck_note_deletion_state",
        ),
        CheckConstraint(
            "length(preview_sha256)=64 AND length(request_sha256)=64", name="ck_note_deletion_hash"
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_note_deletion_lease",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # UUID identity survives physical deletion; it intentionally has no note FK or body.
    note_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reading_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    family_key: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="DELETING")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NoteDeletionMember(Base):
    __tablename__ = "note_deletion_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "user_id"],
            ["note_permanent_deletions.id", "note_permanent_deletions.user_id"],
            name="fk_note_deletion_member_owner",
        ),
        CheckConstraint(
            "revision >= 1 AND length(content_sha256)=64", name="ck_note_deletion_member"
        ),
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    note_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))


class NoteDeletionFile(Base):
    __tablename__ = "note_deletion_files"
    __table_args__ = (
        UniqueConstraint(
            "operation_id", "kind", "root_path", "relative_path", name="uq_note_deletion_file"
        ),
        ForeignKeyConstraint(
            ["operation_id", "user_id"],
            ["note_permanent_deletions.id", "note_permanent_deletions.user_id"],
            name="fk_note_deletion_file_owner",
        ),
        CheckConstraint(
            "kind IN ('NOTE_CURRENT','NOTE_REVISION','NOTE_MIRROR') AND state IN ('PENDING','DELETED','ALREADY_ABSENT','FAILED')",
            name="ck_note_deletion_file_state",
        ),
        CheckConstraint("length(sha256)=64 AND size_bytes >= 0", name="ck_note_deletion_file_hash"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    # Server-frozen provider binding, never a path received from the browser.
    root_path: Mapped[str] = mapped_column(Text)
    relative_path: Mapped[str] = mapped_column(Text)
    storage_provider: Mapped[str | None] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24), default="PENDING")
    error_code: Mapped[str | None] = mapped_column(String(80))


class NoteDeletionUsageReceipt(Base):
    """Verified restored-call accounting survives erasure without result text."""

    __tablename__ = "note_deletion_usage_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "user_id"],
            ["note_permanent_deletions.id", "note_permanent_deletions.user_id"],
            name="fk_note_deletion_usage_operation_owner",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_note_deletion_usage_job_owner",
        ),
        CheckConstraint(
            "length(input_sha256)=64 AND length(request_sha256)=64 AND "
            "length(candidate_result_sha256)=64 AND length(accepted_result_sha256)=64 AND "
            "length(note_sha256)=64 AND length(receipt_sha256)=64",
            name="ck_note_deletion_usage_hashes",
        ),
        CheckConstraint(
            "source_attempt>=1 AND budget_accounted_tokens>=0 AND "
            "(reported_input_tokens IS NULL OR reported_input_tokens>=0) AND "
            "(reported_output_tokens IS NULL OR reported_output_tokens>=0)",
            name="ck_note_deletion_usage_numbers",
        ),
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_events.event_id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    link_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_events.event_id"))
    reading_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    part_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("paper_analysis_parts.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("paper_reading_approval_plans.id"))
    input_sha256: Mapped[str] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64))
    candidate_result_sha256: Mapped[str] = mapped_column(String(64))
    accepted_result_sha256: Mapped[str] = mapped_column(String(64))
    note_sha256: Mapped[str] = mapped_column(String(64))
    source_attempt: Mapped[int] = mapped_column(Integer)
    provider_response_id: Mapped[str | None] = mapped_column(String(200))
    budget_accounted_tokens: Mapped[int] = mapped_column(Integer)
    reported_input_tokens: Mapped[int | None] = mapped_column(Integer)
    reported_output_tokens: Mapped[int | None] = mapped_column(Integer)
    call_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    receipt_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
