"""Exact canonical note source identities and immutable selected Unicode excerpts."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PaperReproductionCanonicalSource(Base):
    __tablename__ = "paper_reproduction_canonical_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "paper_id", "user_id"],
            [
                "paper_reproduction_contexts.task_id",
                "paper_reproduction_contexts.paper_id",
                "paper_reproduction_contexts.user_id",
            ],
            name="fk_reproduction_canonical_context_owner",
        ),
        ForeignKeyConstraint(
            ["canonical_note_id", "reading_job_id", "reading_plan_id", "user_id"],
            [
                "canonical_analytical_notes.id",
                "canonical_analytical_notes.job_id",
                "canonical_analytical_notes.plan_id",
                "canonical_analytical_notes.user_id",
            ],
            name="fk_reproduction_canonical_note_owner",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "reading_plan_id", "user_id"],
            [
                "paper_reading_approvals.job_id",
                "paper_reading_approvals.plan_id",
                "paper_reading_approvals.user_id",
            ],
            name="fk_reproduction_canonical_approval_owner",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "paper_id", "user_id"],
            [
                "paper_analysis_jobs.id",
                "paper_analysis_jobs.paper_id",
                "paper_analysis_jobs.user_id",
            ],
            name="fk_reproduction_canonical_job_paper_owner",
        ),
        ForeignKeyConstraint(
            ["reading_plan_id", "pdf_attachment_id", "user_id"],
            [
                "paper_reading_approval_plans.id",
                "paper_reading_approval_plans.attachment_id",
                "paper_reading_approval_plans.user_id",
            ],
            name="fk_reproduction_canonical_plan_pdf_owner",
        ),
        ForeignKeyConstraint(
            ["pdf_attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_reproduction_canonical_pdf_owner",
        ),
        CheckConstraint(
            "selection_mode IN ('FULL','EXCERPTS') AND note_origin='AI_DERIVED' AND origin_reading_scope='FULL_TEXT' AND pdf_delivery='BOUND_NOT_SENT'",
            name="ck_reproduction_canonical_kind",
        ),
        CheckConstraint(
            "length(note_sha256)=64 AND length(pdf_sha256)=64 AND length(reading_plan_sha256)=64 AND length(skill_sha256)=64 AND note_characters>0 AND page_count>0",
            name="ck_reproduction_canonical_hashes",
        ),
        CheckConstraint(
            "(skill_provenance='LEGACY_INSTRUCTIONS' AND source_manifest_sha256 IS NULL) OR (skill_provenance='FROZEN_FILES' AND source_manifest_sha256 IS NOT NULL AND length(source_manifest_sha256)=64)",
            name="ck_reproduction_canonical_skill_provenance",
        ),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    canonical_note_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reading_job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reading_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    pdf_attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    note_sha256: Mapped[str] = mapped_column(String(64))
    note_characters: Mapped[int] = mapped_column(Integer)
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    reading_plan_sha256: Mapped[str] = mapped_column(String(64))
    skill_key: Mapped[str] = mapped_column(String(80))
    skill_version: Mapped[str] = mapped_column(String(80))
    skill_sha256: Mapped[str] = mapped_column(String(64))
    source_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    skill_provenance: Mapped[str] = mapped_column(
        String(24), default="FROZEN_FILES", server_default="FROZEN_FILES"
    )
    selection_mode: Mapped[str] = mapped_column(String(16))
    note_origin: Mapped[str] = mapped_column(
        String(24), default="AI_DERIVED", server_default="AI_DERIVED"
    )
    origin_reading_scope: Mapped[str] = mapped_column(
        String(24), default="FULL_TEXT", server_default="FULL_TEXT"
    )
    pdf_delivery: Mapped[str] = mapped_column(
        String(24), default="BOUND_NOT_SENT", server_default="BOUND_NOT_SENT"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperReproductionNoteExcerpt(Base):
    __tablename__ = "paper_reproduction_note_excerpts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "user_id"],
            [
                "paper_reproduction_canonical_sources.task_id",
                "paper_reproduction_canonical_sources.user_id",
            ],
            name="fk_reproduction_excerpt_source_owner",
        ),
        CheckConstraint(
            "position>=0 AND start_character>=0 AND end_character>start_character AND length(text)=end_character-start_character AND length(sha256)=64",
            name="ck_reproduction_excerpt_range",
        ),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_character: Mapped[int] = mapped_column(Integer)
    end_character: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
