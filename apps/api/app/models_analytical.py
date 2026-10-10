"""Frozen per-paper source approval and immutable canonical file receipts."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PaperReadingApprovalPlan(Base):
    __tablename__ = "paper_reading_approval_plans"
    __table_args__ = (
        CheckConstraint(
            "note_output_contract IN ('PAPER_ANALYSIS_V1','CANONICAL_MARKDOWN_V2')",
            name="ck_reading_plan_output_contract",
        ),
        UniqueConstraint("id", "attachment_id", "user_id", name="uq_reading_plan_pdf_owner"),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_reading_plan_attachment_owner",
        ),
        Index("ux_reading_plan_id_owner", "id", "user_id", unique=True),
        CheckConstraint(
            "(source_manifest_sha256 IS NULL AND source_binding_version IS NULL) OR "
            "(source_manifest_sha256 IS NOT NULL AND source_binding_version IS NOT NULL AND length(source_manifest_sha256) = 64 AND source_binding_version = 'original-pdf-files-v1')",
            name="ck_reading_plan_source_pair",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"), index=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    paper_version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    collection: Mapped[str] = mapped_column(String(160))
    model_key: Mapped[str] = mapped_column(String(160))
    reasoning_effort: Mapped[str] = mapped_column(String(16))
    skill_key: Mapped[str] = mapped_column(String(80))
    skill_version: Mapped[str] = mapped_column(String(80))
    skill_instructions: Mapped[str] = mapped_column(Text)
    skill_sha256: Mapped[str] = mapped_column(String(64))
    template_text: Mapped[str] = mapped_column(Text)
    template_sha256: Mapped[str] = mapped_column(String(64))
    note_output_contract: Mapped[str] = mapped_column(
        String(32), default="PAPER_ANALYSIS_V1", server_default="PAPER_ANALYSIS_V1"
    )
    render_version: Mapped[str] = mapped_column(String(160))
    output_root: Mapped[str] = mapped_column(Text)
    output_path: Mapped[str] = mapped_column(Text)
    existing_file_sha256: Mapped[str | None] = mapped_column(String(64))
    plan_sha256: Mapped[str] = mapped_column(String(64))
    source_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    source_binding_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperReadingApproval(Base):
    __tablename__ = "paper_reading_approvals"
    __table_args__ = (
        UniqueConstraint("job_id", "plan_id", "user_id", name="uq_reading_approval_plan_owner"),
        ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_reading_approval_job_owner",
        ),
        ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["paper_reading_approval_plans.id", "paper_reading_approval_plans.user_id"],
            name="fk_reading_approval_plan_owner",
        ),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True, unique=True)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CanonicalAnalyticalNote(Base):
    __tablename__ = "canonical_analytical_notes"
    __table_args__ = (
        UniqueConstraint(
            "id", "job_id", "plan_id", "user_id", name="uq_canonical_note_source_owner"
        ),
        CheckConstraint("export_attempt_count >= 0", name="ck_canonical_export_attempts"),
        CheckConstraint(
            "(export_lease_token IS NULL AND export_lease_expires_at IS NULL) OR "
            "(export_lease_token IS NOT NULL AND export_lease_expires_at IS NOT NULL)",
            name="ck_canonical_export_lease_pair",
        ),
        ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_canonical_note_job_owner",
        ),
        ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["paper_reading_approval_plans.id", "paper_reading_approval_plans.user_id"],
            name="fk_canonical_note_plan_owner",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_canonical_note_attachment_owner",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    markdown: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    output_path: Mapped[str] = mapped_column(Text)
    export_status: Mapped[str] = mapped_column(
        String(24), default="PENDING", server_default="PENDING"
    )
    export_error: Mapped[str | None] = mapped_column(String(2000))
    export_error_code: Mapped[str | None] = mapped_column(String(80))
    export_attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    export_retryable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    export_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    export_lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    export_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
