"""Verified literal quotations and immutable owner adoption receipts."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class PlanningBriefProposal(Base):
    __tablename__ = "planning_brief_proposals"
    __table_args__ = (
        UniqueConstraint("job_id", "project_id", "user_id", name="uq_brief_proposal_owner"),
        ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "research_planning_results.job_id",
                "research_planning_results.project_id",
                "research_planning_results.user_id",
            ],
            name="fk_brief_proposal_result_owner",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "job_id", "project_id", "user_id"],
            [
                "research_planning_attempts.id",
                "research_planning_attempts.job_id",
                "research_planning_attempts.project_id",
                "research_planning_attempts.user_id",
            ],
            name="fk_brief_proposal_attempt_owner",
        ),
        CheckConstraint(
            "length(result_sha256)=64 AND length(sha256)=64", name="ck_brief_proposal_hashes"
        ),
        CheckConstraint(
            "(stop_rules_quote IS NULL AND stop_source_start IS NULL AND stop_source_end IS NULL) OR (stop_rules_quote IS NOT NULL AND stop_source_start IS NOT NULL AND stop_source_end IS NOT NULL AND stop_source_start>=0 AND stop_source_end>stop_source_start)",
            name="ck_brief_proposal_stop_span",
        ),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    result_sha256: Mapped[str] = mapped_column(String(64))
    contract_version: Mapped[str] = mapped_column(String(64))
    contract_sha256: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    stop_rules_quote: Mapped[str | None] = mapped_column(Text)
    stop_source_start: Mapped[int | None] = mapped_column(Integer)
    stop_source_end: Mapped[int | None] = mapped_column(Integer)
    warnings_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanningBriefProposalSection(Base):
    __tablename__ = "planning_brief_proposal_sections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "planning_brief_proposals.job_id",
                "planning_brief_proposals.project_id",
                "planning_brief_proposals.user_id",
            ],
            name="fk_brief_proposal_section_owner",
        ),
        CheckConstraint(
            "key IN ('intent','related_work','hypotheses','resources','routes','protocol','stage_plan','decision')",
            name="ck_brief_proposal_section_key",
        ),
        CheckConstraint(
            "(content IS NULL AND source_start IS NULL AND source_end IS NULL) OR (content IS NOT NULL AND source_start IS NOT NULL AND source_end IS NOT NULL AND source_start>=0 AND source_end>source_start)",
            name="ck_brief_proposal_section_span",
        ),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(24), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    content: Mapped[str | None] = mapped_column(Text)
    source_start: Mapped[int | None] = mapped_column(Integer)
    source_end: Mapped[int | None] = mapped_column(Integer)
    uncertainty: Mapped[str | None] = mapped_column(Text)


class PlanningBriefAdoptionReceipt(Base):
    __tablename__ = "planning_brief_adoption_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_brief_adoption_job_owner",
        ),
        ForeignKeyConstraint(
            ["new_brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_adoption_new_owner",
        ),
        ForeignKeyConstraint(
            ["base_brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_adoption_base_owner",
        ),
        UniqueConstraint("user_id", "project_id", "idempotency_key", name="uq_brief_adoption_key"),
        UniqueConstraint("new_brief_id", name="uq_brief_adoption_revision"),
        CheckConstraint(
            "length(result_sha256)=64 AND length(proposal_sha256)=64 AND length(request_sha256)=64",
            name="ck_brief_adoption_hashes",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    new_brief_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    base_brief_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    result_sha256: Mapped[str] = mapped_column(String(64))
    proposal_sha256: Mapped[str] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    include_stop_rules: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
