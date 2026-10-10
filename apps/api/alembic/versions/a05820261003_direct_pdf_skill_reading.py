"""Bind direct original-PDF pages and frozen reading instructions to analysis."""

from alembic import op
import sqlalchemy as sa

revision = "a05820261003"
down_revision = "a05720261003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attachments") as batch:
        batch.create_unique_constraint("uq_attachment_owner", ["id", "user_id"])
    with op.batch_alter_table("paper_analysis_jobs") as batch:
        batch.add_column(
            sa.Column("source_type", sa.String(8), nullable=False, server_default="TEXT")
        )
        batch.create_check_constraint("ck_analysis_source_type", "source_type IN ('TEXT', 'PDF')")
    op.create_table(
        "paper_pdf_reading_sources",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), sa.ForeignKey("attachments.id"), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("skill_key", sa.String(80), nullable=False),
        sa.Column("skill_version", sa.String(80), nullable=False),
        sa.Column("skill_instructions", sa.Text(), nullable=False),
        sa.Column("skill_sha256", sa.String(64), nullable=False),
        sa.Column("render_version", sa.String(160), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["paper_analysis_jobs.id", "paper_analysis_jobs.user_id"],
            name="fk_pdf_reading_job_owner",
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_pdf_reading_attachment_owner",
        ),
        sa.CheckConstraint("page_count > 0", name="ck_pdf_reading_page_count"),
    )
    op.create_index(
        "ix_paper_pdf_reading_sources_user_id", "paper_pdf_reading_sources", ["user_id"]
    )
    op.create_index(
        "ix_paper_pdf_reading_sources_attachment_id", "paper_pdf_reading_sources", ["attachment_id"]
    )


def downgrade() -> None:
    op.drop_table("paper_pdf_reading_sources")
    with op.batch_alter_table("paper_analysis_jobs") as batch:
        batch.drop_constraint("ck_analysis_source_type", type_="check")
        batch.drop_column("source_type")
    with op.batch_alter_table("attachments") as batch:
        batch.drop_constraint("uq_attachment_owner", type_="unique")
