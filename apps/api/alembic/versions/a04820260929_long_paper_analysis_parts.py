"""Persist ordered, owner-scoped long-paper analysis parts.

Revision ID: a04820260929
Revises: a03720260929
"""

import sqlalchemy as sa
from alembic import op

revision = "a04820260929"
down_revision = "a03720260929"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_analysis_jobs",
        sa.Column("part_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "paper_analysis_jobs",
        sa.Column("parts_completed", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "ux_paper_analysis_jobs_id_user",
        "paper_analysis_jobs",
        ["id", "user_id"],
        unique=True,
    )
    op.create_table(
        "paper_analysis_parts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("part_index", sa.Integer(), nullable=False),
        sa.Column("section_key", sa.String(80), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="QUEUED", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("response_payload", sa.JSON()),
        sa.Column("provider_response_id", sa.String(200)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("part_index >= 1", name="ck_paper_analysis_part_index"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_paper_analysis_part_attempts"),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'ANALYZING', 'COMPLETED', 'RETRY_WAIT', "
            "'FAILED', 'NEEDS_ATTENTION')",
            name="ck_paper_analysis_part_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_paper_analysis_part_owner_job",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "part_index", name="uq_paper_analysis_part_position"),
    )
    op.create_index(
        "ix_paper_analysis_parts_user_job", "paper_analysis_parts", ["user_id", "job_id"]
    )
    op.create_index(
        "ix_paper_analysis_parts_job_status", "paper_analysis_parts", ["job_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_paper_analysis_parts_job_status", table_name="paper_analysis_parts")
    op.drop_index("ix_paper_analysis_parts_user_job", table_name="paper_analysis_parts")
    op.drop_table("paper_analysis_parts")
    op.drop_index("ux_paper_analysis_jobs_id_user", table_name="paper_analysis_jobs")
    op.drop_column("paper_analysis_jobs", "parts_completed")
    op.drop_column("paper_analysis_jobs", "part_count")
