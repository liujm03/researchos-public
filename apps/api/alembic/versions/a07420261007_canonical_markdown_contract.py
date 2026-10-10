"""Freeze the single professional writer's thin Markdown output contract."""

import sqlalchemy as sa

from alembic import op

revision = "a07420261007"
down_revision = "a07320261007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, name in (
        ("paper_reading_approval_plans", "ck_reading_plan_output_contract"),
        ("paper_pdf_reading_sources", "ck_pdf_reading_output_contract"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "note_output_contract",
                    sa.String(32),
                    nullable=False,
                    server_default="PAPER_ANALYSIS_V1",
                )
            )
            batch.create_check_constraint(
                name, "note_output_contract IN ('PAPER_ANALYSIS_V1','CANONICAL_MARKDOWN_V2')"
            )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Reading-contract downgrade requires an online owner-data audit")
    queries = (
        "SELECT COUNT(*) FROM paper_reading_approval_plans WHERE note_output_contract<>'PAPER_ANALYSIS_V1'",
        "SELECT COUNT(*) FROM paper_pdf_reading_sources WHERE note_output_contract<>'PAPER_ANALYSIS_V1'",
        "SELECT COUNT(*) FROM paper_analysis_jobs WHERE prompt_version='2026-10-07-canonical-markdown-v3' OR schema_version='canonical-markdown-v2'",
    )
    if any(op.get_bind().scalar(sa.text(query)) for query in queries):
        raise RuntimeError(
            "New canonical Markdown contract owner data cannot be represented before a074; preserve a complete backup and restore into an isolated compatible database"
        )
    for table, name in (
        ("paper_pdf_reading_sources", "ck_pdf_reading_output_contract"),
        ("paper_reading_approval_plans", "ck_reading_plan_output_contract"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
            batch.drop_column("note_output_contract")
