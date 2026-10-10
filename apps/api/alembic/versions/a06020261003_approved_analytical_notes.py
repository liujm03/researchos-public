"""approved_analytical_notes

Revision ID: a06020261003
Revises: a05920261003
Create Date: 2026-10-03 20:29:26.165062
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a06020261003"
down_revision: str | Sequence[str] | None = "a05920261003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper_analysis_jobs", sa.Column("reasoning_effort", sa.String(16), nullable=True)
    )
    op.add_column("codex_tasks", sa.Column("reasoning_effort", sa.String(16), nullable=True))
    op.create_table(
        "paper_reading_approval_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("paper_version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("collection", sa.String(length=160), nullable=False),
        sa.Column("model_key", sa.String(160), nullable=False),
        sa.Column("reasoning_effort", sa.String(16), nullable=False),
        sa.Column("skill_key", sa.String(length=80), nullable=False),
        sa.Column("skill_version", sa.String(length=80), nullable=False),
        sa.Column("skill_instructions", sa.Text(), nullable=False),
        sa.Column("skill_sha256", sa.String(length=64), nullable=False),
        sa.Column("template_text", sa.Text(), nullable=False),
        sa.Column("template_sha256", sa.String(length=64), nullable=False),
        sa.Column("render_version", sa.String(length=160), nullable=False),
        sa.Column("output_root", sa.Text(), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=False),
        sa.Column("existing_file_sha256", sa.String(length=64), nullable=True),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_reading_plan_attachment_owner",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_paper_reading_approval_plans_paper_id"),
        "paper_reading_approval_plans",
        ["paper_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paper_reading_approval_plans_user_id"),
        "paper_reading_approval_plans",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ux_reading_plan_id_owner", "paper_reading_approval_plans", ["id", "user_id"], unique=True
    )
    op.create_table(
        "canonical_analytical_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=False),
        sa.Column("export_status", sa.String(length=24), server_default="PENDING", nullable=False),
        sa.Column("export_error", sa.String(length=2000), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_canonical_note_attachment_owner",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_canonical_note_job_owner",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["paper_reading_approval_plans.id", "paper_reading_approval_plans.user_id"],
            name="fk_canonical_note_plan_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index(
        op.f("ix_canonical_analytical_notes_user_id"),
        "canonical_analytical_notes",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "paper_reading_approvals",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_reading_approval_job_owner",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["paper_reading_approval_plans.id", "paper_reading_approval_plans.user_id"],
            name="fk_reading_approval_plan_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        op.f("ix_paper_reading_approvals_plan_id"),
        "paper_reading_approvals",
        ["plan_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_paper_reading_approvals_user_id"),
        "paper_reading_approvals",
        ["user_id"],
        unique=False,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_column("paper_analysis_jobs", "reasoning_effort")
    op.drop_column("codex_tasks", "reasoning_effort")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_paper_reading_approvals_user_id"), table_name="paper_reading_approvals")
    op.drop_index(op.f("ix_paper_reading_approvals_plan_id"), table_name="paper_reading_approvals")
    op.drop_table("paper_reading_approvals")
    op.drop_index(
        op.f("ix_canonical_analytical_notes_user_id"), table_name="canonical_analytical_notes"
    )
    op.drop_table("canonical_analytical_notes")
    op.drop_index("ux_reading_plan_id_owner", table_name="paper_reading_approval_plans")
    op.drop_index(
        op.f("ix_paper_reading_approval_plans_user_id"), table_name="paper_reading_approval_plans"
    )
    op.drop_index(
        op.f("ix_paper_reading_approval_plans_paper_id"), table_name="paper_reading_approval_plans"
    )
    op.drop_table("paper_reading_approval_plans")
    # ### end Alembic commands ###
