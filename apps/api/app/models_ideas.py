"""Owner ideas with immutable revisions, exact note excerpts and explicit actions."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
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


class ResearchIdea(Base):
    __tablename__ = "research_ideas"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_idea_owner"),
        UniqueConstraint("user_id", "create_key", name="uq_idea_create_key"),
        CheckConstraint(
            "(create_key IS NULL AND create_sha256 IS NULL) OR (create_key IS NOT NULL AND length(create_key) BETWEEN 1 AND 120 AND create_sha256 IS NOT NULL AND length(create_sha256)=64)",
            name="ck_idea_create_pair",
        ),
        ForeignKeyConstraint(
            ["id", "user_id"],
            ["research_entities.id", "research_entities.user_id"],
            name="fk_idea_entity_owner",
        ),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_idea_project_owner",
        ),
        CheckConstraint("revision > 0", name="ck_idea_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    create_key: Mapped[str | None] = mapped_column(String(120))
    create_sha256: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(320))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdeaRevision(Base):
    __tablename__ = "idea_revisions"
    __table_args__ = (
        UniqueConstraint("id", "idea_id", "user_id", name="uq_idea_revision_owner"),
        UniqueConstraint("idea_id", "revision", name="uq_idea_revision_number"),
        ForeignKeyConstraint(
            ["idea_id", "user_id"],
            ["research_ideas.id", "research_ideas.user_id"],
            name="fk_idea_revision_owner",
        ),
        CheckConstraint(
            "status IN ('INBOX','EVALUATING','PROMISING','EXPERIMENTING','VALIDATED','REJECTED','PAPER_CANDIDATE')",
            name="ck_idea_status",
        ),
        CheckConstraint("revision>0 AND length(sha256)=64", name="ck_idea_revision_hash"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idea_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(320))
    content: Mapped[str] = mapped_column(Text)
    problem: Mapped[str | None] = mapped_column(Text)
    hypothesis: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    contribution: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str | None] = mapped_column(Text)
    novelty: Mapped[str | None] = mapped_column(Text)
    feasibility: Mapped[str | None] = mapped_column(Text)
    required_dataset: Mapped[str | None] = mapped_column(Text)
    required_hardware: Mapped[str | None] = mapped_column(Text)
    next_experiment: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdeaSource(Base):
    __tablename__ = "idea_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "idea_id", "user_id"],
            ["idea_revisions.id", "idea_revisions.idea_id", "idea_revisions.user_id"],
            name="fk_idea_source_revision",
        ),
        ForeignKeyConstraint(
            ["canonical_note_id", "reading_job_id", "reading_plan_id", "user_id"],
            [
                "canonical_analytical_notes.id",
                "canonical_analytical_notes.job_id",
                "canonical_analytical_notes.plan_id",
                "canonical_analytical_notes.user_id",
            ],
            name="fk_idea_source_note",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "reading_plan_id", "user_id"],
            [
                "paper_reading_approvals.job_id",
                "paper_reading_approvals.plan_id",
                "paper_reading_approvals.user_id",
            ],
            name="fk_idea_source_approval",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "paper_id", "user_id"],
            [
                "paper_analysis_jobs.id",
                "paper_analysis_jobs.paper_id",
                "paper_analysis_jobs.user_id",
            ],
            name="fk_idea_source_paper",
        ),
        CheckConstraint(
            "start_offset>=0 AND end_offset>start_offset AND length(exact_quote)=end_offset-start_offset",
            name="ck_idea_source_offsets",
        ),
        CheckConstraint(
            "length(note_sha256)=64 AND length(source_sha256)=64", name="ck_idea_source_hash"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    idea_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    canonical_note_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reading_job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reading_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    paper_title: Mapped[str] = mapped_column(Text)
    note_sha256: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    exact_quote: Mapped[str] = mapped_column(Text)


class IdeaTaskAction(Base):
    __tablename__ = "idea_task_actions"
    __table_args__ = (
        UniqueConstraint("idea_id", "idempotency_key", name="uq_idea_task_key"),
        ForeignKeyConstraint(
            ["revision_id", "idea_id", "user_id"],
            ["idea_revisions.id", "idea_revisions.idea_id", "idea_revisions.user_id"],
            name="fk_idea_task_revision",
        ),
        ForeignKeyConstraint(
            ["task_id", "user_id"], ["tasks.id", "tasks.user_id"], name="fk_idea_task_owner"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    idea_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    revision_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchBriefIdeaSource(Base):
    __tablename__ = "research_brief_idea_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_idea_owner",
        ),
        ForeignKeyConstraint(
            ["revision_id", "idea_id", "user_id"],
            ["idea_revisions.id", "idea_revisions.idea_id", "idea_revisions.user_id"],
            name="fk_brief_idea_revision",
        ),
        CheckConstraint(
            "length(revision_sha256)=64 AND length(source_sha256)=64", name="ck_brief_idea_hash"
        ),
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    idea_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    revision_sha256: Mapped[str] = mapped_column(String(64))
    selected_sections: Mapped[str] = mapped_column(String(160))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_sha256: Mapped[str] = mapped_column(String(64))


class IdeaBriefAction(Base):
    __tablename__ = "idea_brief_actions"
    __table_args__ = (
        UniqueConstraint("idea_id", "idempotency_key", name="uq_idea_brief_key"),
        ForeignKeyConstraint(
            ["revision_id", "idea_id", "user_id"],
            ["idea_revisions.id", "idea_revisions.idea_id", "idea_revisions.user_id"],
            name="fk_idea_brief_revision",
        ),
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_idea_brief_action_owner",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    idea_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdeaRevisionTag(Base):
    """Frozen tag labels; live shared EntityTag links project the current revision."""

    __tablename__ = "idea_revision_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "idea_id", "user_id"],
            ["idea_revisions.id", "idea_revisions.idea_id", "idea_revisions.user_id"],
            name="fk_idea_tag_revision",
        ),
        CheckConstraint("length(name) BETWEEN 1 AND 80", name="ck_idea_tag_name"),
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    idea_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(80))
