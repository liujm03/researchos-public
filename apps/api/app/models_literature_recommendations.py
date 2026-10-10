"""Owner-scoped frozen metadata queries, candidates, and ordered authors."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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


class LiteratureRecommendationBatch(Base):
    __tablename__ = "literature_recommendation_batches"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_lit_batch_project_owner"),
        UniqueConstraint("user_id", "project_id", "idempotency_key", name="uq_lit_batch_key"),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_lit_batch_project_owner",
        ),
        ForeignKeyConstraint(
            ["parent_batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_batches.id",
                "literature_recommendation_batches.project_id",
                "literature_recommendation_batches.user_id",
            ],
            name="fk_lit_batch_parent_owner",
        ),
        ForeignKeyConstraint(
            ["question_id", "project_id"],
            ["research_questions.id", "research_questions.project_id"],
            name="fk_lit_batch_question_project",
        ),
        CheckConstraint(
            "status IN ('FETCHING','COMPLETED','FAILED','NEEDS_ATTENTION') AND length(provider_key) BETWEEN 1 AND 64",
            name="ck_lit_batch_status",
        ),
        CheckConstraint(
            "page_size BETWEEN 1 AND 50 AND project_version>0 AND length(context_sha256)=64 AND length(idempotency_key) BETWEEN 1 AND 120 AND length(query)>=2",
            name="ck_lit_batch_bounds",
        ),
        CheckConstraint(
            "(from_year IS NULL OR from_year BETWEEN 1400 AND 2200) AND (until_year IS NULL OR until_year BETWEEN 1400 AND 2200) AND (from_year IS NULL OR until_year IS NULL OR from_year<=until_year) AND (total_results IS NULL OR total_results>=0)",
            name="ck_lit_batch_years",
        ),
        CheckConstraint(
            "parent_batch_id IS NULL OR parent_batch_id<>id", name="ck_lit_batch_not_self"
        ),
        CheckConstraint(
            "(status='FETCHING' AND completed_at IS NULL) OR (status<>'FETCHING' AND completed_at IS NOT NULL)",
            name="ck_lit_batch_terminal",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    parent_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    question_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    query: Mapped[str] = mapped_column(String(500))
    provider_key: Mapped[str] = mapped_column(String(64))
    from_year: Mapped[int | None] = mapped_column(Integer)
    until_year: Mapped[int | None] = mapped_column(Integer)
    page_size: Mapped[int] = mapped_column(Integer)
    project_version: Mapped[int] = mapped_column(Integer)
    project_name: Mapped[str] = mapped_column(String(240))
    question_text: Mapped[str | None] = mapped_column(Text)
    context_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="FETCHING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_results: Mapped[int | None] = mapped_column(Integer)
    request_cursor: Mapped[str | None] = mapped_column(Text)
    next_cursor: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(240))
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class LiteratureRecommendationTerm(Base):
    __tablename__ = "literature_recommendation_terms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_batches.id",
                "literature_recommendation_batches.project_id",
                "literature_recommendation_batches.user_id",
            ],
            name="fk_lit_term_batch_owner",
        ),
        CheckConstraint(
            "position BETWEEN 0 AND 19 AND length(term) BETWEEN 1 AND 120",
            name="ck_lit_term_bounds",
        ),
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    term: Mapped[str] = mapped_column(String(120))


class LiteratureRecommendationVenue(Base):
    __tablename__ = "literature_recommendation_venues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_batches.id",
                "literature_recommendation_batches.project_id",
                "literature_recommendation_batches.user_id",
            ],
            name="fk_lit_venue_batch_owner",
        ),
        CheckConstraint("position BETWEEN 0 AND 19", name="ck_lit_venue_bounds"),
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    venue_key: Mapped[str] = mapped_column(String(32))


class LiteratureRecommendationCandidate(Base):
    __tablename__ = "literature_recommendation_candidates"
    __table_args__ = (
        UniqueConstraint("id", "batch_id", "project_id", "user_id", name="uq_lit_candidate_scope"),
        UniqueConstraint(
            "batch_id", "provider_key", "provider_id", name="uq_lit_candidate_identity"
        ),
        ForeignKeyConstraint(
            ["batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_batches.id",
                "literature_recommendation_batches.project_id",
                "literature_recommendation_batches.user_id",
            ],
            name="fk_lit_candidate_batch_owner",
        ),
        ForeignKeyConstraint(
            ["paper_id", "user_id"],
            ["papers.id", "papers.user_id"],
            name="fk_lit_candidate_paper_owner",
        ),
        CheckConstraint(
            "length(provider_key) BETWEEN 1 AND 64 AND length(provider_id)>0 AND length(source_hash)=64 AND length(candidate_sha256)=64 AND rank_score>=0",
            name="ck_lit_candidate_identity",
        ),
        CheckConstraint(
            "venue_status IN ('MATCHED','OTHER','UNKNOWN') AND publication_status IN ('METADATA_REPORTED','PREPRINT','UNKNOWN')",
            name="ck_lit_candidate_classification",
        ),
        CheckConstraint(
            "(review_status='CANDIDATE' AND paper_id IS NULL) OR (review_status='ADOPTED' AND paper_id IS NOT NULL)",
            name="ck_lit_candidate_review",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    provider_key: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str] = mapped_column(String(320))
    title: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    paper_type: Mapped[str | None] = mapped_column(String(80))
    abstract: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidate_sha256: Mapped[str] = mapped_column(String(64))
    venue_key: Mapped[str | None] = mapped_column(String(32))
    venue_status: Mapped[str] = mapped_column(String(16))
    in_scope: Mapped[bool] = mapped_column(Boolean)
    publication_status: Mapped[str] = mapped_column(String(24))
    rank_score: Mapped[int] = mapped_column(Integer)
    match_reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(16), default="CANDIDATE")
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class LiteratureRecommendationAuthor(Base):
    __tablename__ = "literature_recommendation_authors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_candidates.id",
                "literature_recommendation_candidates.batch_id",
                "literature_recommendation_candidates.project_id",
                "literature_recommendation_candidates.user_id",
            ],
            name="fk_lit_author_candidate_owner",
        ),
        CheckConstraint("position>=0 AND length(name)>0", name="ck_lit_author_bounds"),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
