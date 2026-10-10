"""Normalized immutable brief revisions and exact owner review receipts."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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


class ResearchBrief(Base):
    __tablename__ = "research_briefs"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_research_brief_project_owner"),
        UniqueConstraint("project_id", "revision", name="uq_research_brief_revision"),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_brief_project_owner",
        ),
        ForeignKeyConstraint(
            ["base_brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_base_project_owner",
        ),
        CheckConstraint("revision > 0 AND project_version > 0", name="ck_brief_versions"),
        CheckConstraint("length(idea) BETWEEN 1 AND 12000", name="ck_brief_idea"),
        CheckConstraint("length(sha256) = 64", name="ck_brief_hash"),
        ForeignKeyConstraint(
            ["stop_source_planning_job_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_brief_stop_planning_owner",
            use_alter=True,
        ),
        CheckConstraint(
            "(stop_source_planning_job_id IS NULL AND stop_source_result_sha256 IS NULL) OR (stop_source_planning_job_id IS NOT NULL AND stop_source_result_sha256 IS NOT NULL AND length(stop_source_result_sha256)=64)",
            name="ck_brief_stop_source_pair",
        ),
        CheckConstraint(
            "stop_rules_origin IS NULL OR stop_rules_origin IN ('OWNER_INPUT','AI_INFERRED')",
            name="ck_brief_stop_origin",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    project_version: Mapped[int] = mapped_column(Integer)
    base_brief_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    idea: Mapped[str] = mapped_column(Text)
    stop_rules: Mapped[str | None] = mapped_column(Text)
    stop_rules_origin: Mapped[str | None] = mapped_column(String(24))
    stop_source_planning_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    stop_source_result_sha256: Mapped[str | None] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchBriefSection(Base):
    __tablename__ = "research_brief_sections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_section_owner",
        ),
        CheckConstraint(
            "key IN ('intent','related_work','hypotheses','resources','routes','protocol','stage_plan','decision')",
            name="ck_brief_section_key",
        ),
        CheckConstraint(
            "origin_type IN ('OWNER_INPUT','PROJECT_CONTEXT','MISSING','AI_INFERRED')",
            name="ck_brief_section_origin",
        ),
        ForeignKeyConstraint(
            ["source_planning_job_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_brief_section_planning_owner",
        ),
        CheckConstraint(
            "(source_planning_job_id IS NULL AND source_result_sha256 IS NULL) OR (source_planning_job_id IS NOT NULL AND source_result_sha256 IS NOT NULL AND length(source_result_sha256)=64)",
            name="ck_brief_section_source_pair",
        ),
        CheckConstraint(
            "origin_type<>'AI_INFERRED' OR source_planning_job_id IS NOT NULL",
            name="ck_brief_section_ai_source",
        ),
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(24), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    content: Mapped[str | None] = mapped_column(Text)
    origin_type: Mapped[str] = mapped_column(String(24))
    uncertainty: Mapped[str | None] = mapped_column(Text)
    source_planning_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_result_sha256: Mapped[str | None] = mapped_column(String(64))


class ResearchBriefEvidence(Base):
    __tablename__ = "research_brief_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_evidence_owner",
        ),
        ForeignKeyConstraint(
            ["paper_id", "user_id"],
            ["papers.id", "papers.user_id"],
            name="fk_brief_evidence_paper_owner",
        ),
        UniqueConstraint("brief_id", "paper_id", name="uq_brief_evidence_paper"),
        CheckConstraint(
            "paper_version > 0 AND length(sha256) = 64", name="ck_brief_evidence_version_hash"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(600))
    abstract: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    doi: Mapped[str | None] = mapped_column(String(300))
    paper_version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))


class ResearchBriefReview(Base):
    __tablename__ = "research_brief_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_review_owner",
        ),
        CheckConstraint("decision IN ('ACCEPT','REJECT')", name="ck_brief_review_decision"),
        CheckConstraint(
            "length(sha256) = 64 AND reviewer_id = user_id", name="ck_brief_review_identity"
        ),
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    sha256: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ResearchBriefCanonicalSource(Base):
    """Exact selected note and frozen original-reading provenance, never PDF bytes."""

    __tablename__ = "research_brief_canonical_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_canonical_brief_owner",
        ),
        ForeignKeyConstraint(
            ["canonical_note_id", "reading_job_id", "reading_plan_id", "user_id"],
            [
                "canonical_analytical_notes.id",
                "canonical_analytical_notes.job_id",
                "canonical_analytical_notes.plan_id",
                "canonical_analytical_notes.user_id",
            ],
            name="fk_brief_canonical_note_owner",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "reading_plan_id", "user_id"],
            [
                "paper_reading_approvals.job_id",
                "paper_reading_approvals.plan_id",
                "paper_reading_approvals.user_id",
            ],
            name="fk_brief_canonical_approval_owner",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "paper_id", "user_id"],
            [
                "paper_analysis_jobs.id",
                "paper_analysis_jobs.paper_id",
                "paper_analysis_jobs.user_id",
            ],
            name="fk_brief_canonical_job_paper_owner",
        ),
        ForeignKeyConstraint(
            ["reading_plan_id", "pdf_attachment_id", "user_id"],
            [
                "paper_reading_approval_plans.id",
                "paper_reading_approval_plans.attachment_id",
                "paper_reading_approval_plans.user_id",
            ],
            name="fk_brief_canonical_plan_pdf_owner",
        ),
        ForeignKeyConstraint(
            ["pdf_attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_brief_canonical_pdf_owner",
        ),
        CheckConstraint(
            "source_scope='DERIVED_NOTE' AND note_origin='AI_DERIVED'",
            name="ck_brief_canonical_kind",
        ),
        CheckConstraint(
            "length(note_sha256)=64 AND length(source_sha256)=64 AND length(markdown) BETWEEN 1 AND 524288",
            name="ck_brief_canonical_bounds",
        ),
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    canonical_note_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reading_job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reading_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    pdf_attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    paper_title: Mapped[str] = mapped_column(Text)
    note_sha256: Mapped[str] = mapped_column(String(64))
    markdown: Mapped[str] = mapped_column(Text)
    source_scope: Mapped[str] = mapped_column(String(24), default="DERIVED_NOTE")
    note_origin: Mapped[str] = mapped_column(String(24), default="AI_DERIVED")
    source_facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
