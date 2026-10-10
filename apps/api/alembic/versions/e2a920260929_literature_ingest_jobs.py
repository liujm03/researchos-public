"""Durable single-paper literature ingest orchestration.

Revision ID: e2a920260929
Revises: b0d620260929
"""

import sqlalchemy as sa

from alembic import op

revision = "e2a920260929"
down_revision = "b0d620260929"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_parse_jobs",
        sa.Column("suppress_auto_analysis", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "literature_ingest_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("server_id", sa.String(100), nullable=False),
        sa.Column("library_type", sa.String(16), nullable=False),
        sa.Column("library_id", sa.String(80), nullable=False),
        sa.Column("item_key", sa.String(16), nullable=False),
        sa.Column("item_title", sa.String(2000), server_default="", nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("copy_pdf", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("request_analysis", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("analysis_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("papers.id")),
        sa.Column("attachment_id", sa.Uuid(), sa.ForeignKey("attachments.id")),
        sa.Column("parse_job_id", sa.Uuid(), sa.ForeignKey("paper_parse_jobs.id")),
        sa.Column("analysis_job_id", sa.Uuid(), sa.ForeignKey("paper_analysis_jobs.id")),
        sa.Column("inbox_item_id", sa.Uuid(), sa.ForeignKey("inbox_items.id")),
        sa.Column("warning_code", sa.String(80)),
        sa.Column("warning_message", sa.Text()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "analysis_mode IN ('FAST', 'STANDARD', 'DEEP')", name="ck_ingest_mode"
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_literature_ingest_idempotency"),
    )
    op.create_index("ix_literature_ingest_jobs_user_id", "literature_ingest_jobs", ["user_id"])
    op.create_index(
        "ix_literature_ingest_owner_status", "literature_ingest_jobs", ["user_id", "status"]
    )
    op.create_table(
        "literature_ingest_candidates",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("literature_ingest_jobs.id"), primary_key=True),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("papers.id"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("literature_ingest_candidates")
    op.drop_index("ix_literature_ingest_owner_status", table_name="literature_ingest_jobs")
    op.drop_index("ix_literature_ingest_jobs_user_id", table_name="literature_ingest_jobs")
    op.drop_table("literature_ingest_jobs")
    op.drop_column("paper_parse_jobs", "suppress_auto_analysis")
