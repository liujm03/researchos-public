"""Freeze approved project metadata search and candidate provenance."""

import sqlalchemy as sa

from alembic import op

revision = "a07520261008"
down_revision = "a07420261007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("research_questions") as batch:
        batch.create_unique_constraint("uq_research_question_project", ["id", "project_id"])
    op.create_table(
        "literature_recommendation_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("parent_batch_id", sa.Uuid(), nullable=True),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.String(length=500), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("from_year", sa.Integer(), nullable=True),
        sa.Column("until_year", sa.Integer(), nullable=True),
        sa.Column("page_size", sa.Integer(), nullable=False),
        sa.Column("project_version", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=240), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("context_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_results", sa.Integer(), nullable=True),
        sa.Column("request_cursor", sa.Text(), nullable=True),
        sa.Column("next_cursor", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=240), nullable=True),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "page_size BETWEEN 1 AND 50 AND project_version>0 AND length(context_sha256)=64 AND length(idempotency_key) BETWEEN 1 AND 120 AND length(query)>=2",
            name="ck_lit_batch_bounds",
        ),
        sa.CheckConstraint(
            "parent_batch_id IS NULL OR parent_batch_id<>id", name="ck_lit_batch_not_self"
        ),
        sa.CheckConstraint(
            "status IN ('FETCHING','COMPLETED','FAILED','NEEDS_ATTENTION') AND length(provider_key) BETWEEN 1 AND 64",
            name="ck_lit_batch_status",
        ),
        sa.CheckConstraint(
            "(status='FETCHING' AND completed_at IS NULL) OR (status<>'FETCHING' AND completed_at IS NOT NULL)",
            name="ck_lit_batch_terminal",
        ),
        sa.CheckConstraint(
            "(from_year IS NULL OR from_year BETWEEN 1400 AND 2200) AND (until_year IS NULL OR until_year BETWEEN 1400 AND 2200) AND (from_year IS NULL OR until_year IS NULL OR from_year<=until_year) AND (total_results IS NULL OR total_results>=0)",
            name="ck_lit_batch_years",
        ),
        sa.ForeignKeyConstraint(
            ["parent_batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_batches.id",
                "literature_recommendation_batches.project_id",
                "literature_recommendation_batches.user_id",
            ],
            name="fk_lit_batch_parent_owner",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_lit_batch_project_owner",
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "project_id"],
            ["research_questions.id", "research_questions.project_id"],
            name="fk_lit_batch_question_project",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "project_id", "idempotency_key", name="uq_lit_batch_key"),
        sa.UniqueConstraint("id", "project_id", "user_id", name="uq_lit_batch_project_owner"),
    )
    op.create_index(
        "ix_literature_recommendation_batches_project_id",
        "literature_recommendation_batches",
        ["project_id"],
    )
    op.create_index(
        "ix_literature_recommendation_batches_user_id",
        "literature_recommendation_batches",
        ["user_id"],
    )
    op.create_table(
        "literature_recommendation_terms",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("term", sa.String(length=120), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 19 AND length(term) BETWEEN 1 AND 120",
            name="ck_lit_term_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_batches.id",
                "literature_recommendation_batches.project_id",
                "literature_recommendation_batches.user_id",
            ],
            name="fk_lit_term_batch_owner",
        ),
        sa.PrimaryKeyConstraint("batch_id", "user_id", "position"),
    )
    op.create_table(
        "literature_recommendation_venues",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("venue_key", sa.String(length=32), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 19", name="ck_lit_venue_bounds"),
        sa.ForeignKeyConstraint(
            ["batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_batches.id",
                "literature_recommendation_batches.project_id",
                "literature_recommendation_batches.user_id",
            ],
            name="fk_lit_venue_batch_owner",
        ),
        sa.PrimaryKeyConstraint("batch_id", "user_id", "position"),
    )
    op.create_table(
        "literature_recommendation_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=320), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(length=300), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("paper_type", sa.String(length=80), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_sha256", sa.String(length=64), nullable=False),
        sa.Column("venue_key", sa.String(length=32), nullable=True),
        sa.Column("venue_status", sa.String(length=16), nullable=False),
        sa.Column("in_scope", sa.Boolean(), nullable=False),
        sa.Column("publication_status", sa.String(length=24), nullable=False),
        sa.Column("rank_score", sa.Integer(), nullable=False),
        sa.Column("match_reasons_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=16), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "venue_status IN ('MATCHED','OTHER','UNKNOWN') AND publication_status IN ('METADATA_REPORTED','PREPRINT','UNKNOWN')",
            name="ck_lit_candidate_classification",
        ),
        sa.CheckConstraint(
            "length(provider_key) BETWEEN 1 AND 64 AND length(provider_id)>0 AND length(source_hash)=64 AND length(candidate_sha256)=64 AND rank_score>=0",
            name="ck_lit_candidate_identity",
        ),
        sa.CheckConstraint(
            "(review_status='CANDIDATE' AND paper_id IS NULL) OR (review_status='ADOPTED' AND paper_id IS NOT NULL)",
            name="ck_lit_candidate_review",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_batches.id",
                "literature_recommendation_batches.project_id",
                "literature_recommendation_batches.user_id",
            ],
            name="fk_lit_candidate_batch_owner",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id", "user_id"],
            ["papers.id", "papers.user_id"],
            name="fk_lit_candidate_paper_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id", "provider_key", "provider_id", name="uq_lit_candidate_identity"
        ),
        sa.UniqueConstraint(
            "id", "batch_id", "project_id", "user_id", name="uq_lit_candidate_scope"
        ),
    )
    op.create_index(
        "ix_literature_recommendation_candidates_batch_id",
        "literature_recommendation_candidates",
        ["batch_id"],
    )
    op.create_index(
        "ix_literature_recommendation_candidates_user_id",
        "literature_recommendation_candidates",
        ["user_id"],
    )
    op.create_table(
        "literature_recommendation_authors",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.CheckConstraint("position>=0 AND length(name)>0", name="ck_lit_author_bounds"),
        sa.ForeignKeyConstraint(
            ["candidate_id", "batch_id", "project_id", "user_id"],
            [
                "literature_recommendation_candidates.id",
                "literature_recommendation_candidates.batch_id",
                "literature_recommendation_candidates.project_id",
                "literature_recommendation_candidates.user_id",
            ],
            name="fk_lit_author_candidate_owner",
        ),
        sa.PrimaryKeyConstraint("candidate_id", "user_id", "position"),
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Recommendation downgrade requires an online owner-data audit")
    tables = (
        "literature_recommendation_authors",
        "literature_recommendation_candidates",
        "literature_recommendation_venues",
        "literature_recommendation_terms",
        "literature_recommendation_batches",
    )
    if any(op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {table}")) for table in tables):
        raise RuntimeError(
            "Recommendation owner data cannot be represented before a075; preserve a complete backup"
        )
    for table in tables:
        op.drop_table(table)
    with op.batch_alter_table("research_questions") as batch:
        batch.drop_constraint("uq_research_question_project", type_="unique")
