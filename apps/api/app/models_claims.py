"""Normalized immutable claims, evidence and append-only owner review."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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


class ResearchClaim(Base):
    __tablename__ = "research_claims"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_claim_owner"),
        UniqueConstraint("user_id", "create_key", name="uq_claim_create_key"),
        ForeignKeyConstraint(
            ["id", "user_id"],
            ["research_entities.id", "research_entities.user_id"],
            name="fk_claim_entity",
        ),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_claim_project",
        ),
        CheckConstraint("revision>0 AND length(create_sha256)=64", name="ck_claim_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(320))
    text: Mapped[str] = mapped_column(Text)
    create_key: Mapped[str] = mapped_column(String(120))
    create_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClaimRevision(Base):
    __tablename__ = "claim_revisions"
    __table_args__ = (
        UniqueConstraint("id", "claim_id", "project_id", "user_id", name="uq_claim_revision_owner"),
        UniqueConstraint("claim_id", "revision", name="uq_claim_revision_number"),
        UniqueConstraint("claim_id", "idempotency_key", name="uq_claim_revision_key"),
        ForeignKeyConstraint(
            ["claim_id", "project_id", "user_id"],
            ["research_claims.id", "research_claims.project_id", "research_claims.user_id"],
            name="fk_claim_revision_owner",
        ),
        ForeignKeyConstraint(
            ["research_question_id", "project_id"],
            ["research_questions.id", "research_questions.project_id"],
            name="fk_claim_question",
        ),
        CheckConstraint(
            "kind IN ('HYPOTHESIS','FINDING','LIMITATION','RESEARCH_GAP')", name="ck_claim_kind"
        ),
        CheckConstraint(
            "revision>0 AND length(sha256)=64 AND length(evidence_sha256)=64 AND length(request_sha256)=64",
            name="ck_claim_hash",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(320))
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24))
    conditions: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text)
    evaluation_criteria: Mapped[str] = mapped_column(Text)
    research_question_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sha256: Mapped[str] = mapped_column(String(64))
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def revision_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["revision_id", "claim_id", "project_id", "user_id"],
        [
            "claim_revisions.id",
            "claim_revisions.claim_id",
            "claim_revisions.project_id",
            "claim_revisions.user_id",
        ],
        name="fk_claim_" + name + "_revision",
    )


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (
        revision_fk("evidence"),
        UniqueConstraint("revision_id", "position", name="uq_claim_evidence_position"),
        ForeignKeyConstraint(
            ["result_id", "project_id", "user_id"],
            ["server_results.id", "server_results.project_id", "server_results.user_id"],
            name="fk_claim_evidence_result",
        ),
        ForeignKeyConstraint(
            ["metric_id", "result_id", "project_id", "user_id"],
            [
                "server_result_metrics.id",
                "server_result_metrics.result_id",
                "server_result_metrics.project_id",
                "server_result_metrics.user_id",
            ],
            name="fk_claim_evidence_metric",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "result_id", "project_id", "user_id"],
            [
                "server_result_artifacts.id",
                "server_result_artifacts.result_id",
                "server_result_artifacts.project_id",
                "server_result_artifacts.user_id",
            ],
            name="fk_claim_evidence_artifact",
        ),
        ForeignKeyConstraint(
            ["canonical_note_id", "reading_job_id", "reading_plan_id", "user_id"],
            [
                "canonical_analytical_notes.id",
                "canonical_analytical_notes.job_id",
                "canonical_analytical_notes.plan_id",
                "canonical_analytical_notes.user_id",
            ],
            name="fk_claim_evidence_note",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "paper_id", "user_id"],
            [
                "paper_analysis_jobs.id",
                "paper_analysis_jobs.paper_id",
                "paper_analysis_jobs.user_id",
            ],
            name="fk_claim_evidence_paper",
        ),
        ForeignKeyConstraint(
            ["reading_job_id", "reading_plan_id", "user_id"],
            [
                "paper_reading_approvals.job_id",
                "paper_reading_approvals.plan_id",
                "paper_reading_approvals.user_id",
            ],
            name="fk_claim_evidence_approval",
        ),
        CheckConstraint(
            "relation IN ('SUPPORTS','REFUTES','CONTEXT')", name="ck_claim_evidence_relation"
        ),
        CheckConstraint("position>=0 AND length(source_sha256)=64", name="ck_claim_evidence_hash"),
        CheckConstraint(
            "source_kind NOT IN ('RESULT_METRIC','RESULT_ARTIFACT') OR (result_sha256 IS NOT NULL AND length(result_sha256)=64)",
            name="ck_claim_result_hash",
        ),
        CheckConstraint(
            "source_kind<>'CANONICAL_QUOTE' OR (note_sha256 IS NOT NULL AND length(note_sha256)=64 AND exact_quote IS NOT NULL AND start_offset IS NOT NULL AND end_offset IS NOT NULL)",
            name="ck_claim_quote_hash",
        ),
        CheckConstraint(
            "length(rationale)<=4000 AND (observation IS NULL OR length(observation) BETWEEN 1 AND 20000) AND (exact_quote IS NULL OR length(exact_quote)<=20000)",
            name="ck_claim_evidence_bounds",
        ),
        CheckConstraint(
            "(source_kind='RESULT_METRIC' AND result_id IS NOT NULL AND metric_id IS NOT NULL AND artifact_id IS NULL AND canonical_note_id IS NULL AND observation IS NULL) OR (source_kind='RESULT_ARTIFACT' AND result_id IS NOT NULL AND artifact_id IS NOT NULL AND metric_id IS NULL AND canonical_note_id IS NULL AND observation IS NULL) OR (source_kind='CANONICAL_QUOTE' AND canonical_note_id IS NOT NULL AND reading_job_id IS NOT NULL AND reading_plan_id IS NOT NULL AND paper_id IS NOT NULL AND result_id IS NULL AND metric_id IS NULL AND artifact_id IS NULL AND observation IS NULL AND start_offset>=0 AND end_offset>start_offset AND length(exact_quote)=end_offset-start_offset) OR (source_kind='OWNER_OBSERVATION' AND observation IS NOT NULL AND result_id IS NULL AND metric_id IS NULL AND artifact_id IS NULL AND canonical_note_id IS NULL)",
            name="ck_claim_evidence_kind",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    position: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[str] = mapped_column(String(24))
    relation: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text)
    result_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    metric_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    canonical_note_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reading_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reading_plan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    paper_title: Mapped[str | None] = mapped_column(Text)
    note_sha256: Mapped[str | None] = mapped_column(String(64))
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    exact_quote: Mapped[str | None] = mapped_column(Text)
    observation: Mapped[str | None] = mapped_column(Text)
    metric_name: Mapped[str | None] = mapped_column(String(120))
    metric_value: Mapped[float | None] = mapped_column(Float)
    metric_unit: Mapped[str | None] = mapped_column(String(80))
    metric_split: Mapped[str | None] = mapped_column(String(80))
    evaluation_protocol: Mapped[str | None] = mapped_column(Text)
    protocol_sha256: Mapped[str | None] = mapped_column(String(64))
    dataset_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_path: Mapped[str | None] = mapped_column(String(240))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_verification: Mapped[str | None] = mapped_column(String(24))
    source_facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_sha256: Mapped[str] = mapped_column(String(64))


class ClaimReview(Base):
    __tablename__ = "claim_reviews"
    __table_args__ = (
        revision_fk("review"),
        UniqueConstraint("claim_id", "idempotency_key", name="uq_claim_review_key"),
        CheckConstraint(
            "decision IN ('ACCEPT','REJECT','COMMENT')", name="ck_claim_review_decision"
        ),
        CheckConstraint(
            "length(revision_sha256)=64 AND length(evidence_sha256)=64 AND length(request_sha256)=64",
            name="ck_claim_review_hash",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision_sha256: Mapped[str] = mapped_column(String(64))
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    conclusion: Mapped[str] = mapped_column(Text)
    acknowledge_gaps: Mapped[bool] = mapped_column(Boolean)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
