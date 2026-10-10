"""Frozen, owner-scoped paper reproduction draft provenance."""

from alembic import op
import sqlalchemy as sa

revision = "a05620261002"
down_revision = "a05520261001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("codex_tasks") as batch:
        batch.create_unique_constraint("uq_codex_task_owner", ["id", "user_id"])
    op.create_table(
        "paper_reproduction_contexts",
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("paper_title", sa.String(2000), nullable=False),
        sa.Column("paper_metadata_version", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(24), nullable=False),
        sa.Column("source_scope", sa.String(24), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("paper_research_notes.id"), nullable=True),
        sa.Column("note_revision", sa.Integer(), nullable=True),
        sa.Column("note_review_status", sa.String(24), nullable=True),
        sa.Column("parsed_document_id", sa.Uuid(), sa.ForeignKey("parsed_documents.id"), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), nullable=True),
        sa.Column("parser_name", sa.String(80), nullable=True),
        sa.Column("parser_version", sa.String(80), nullable=True),
        sa.Column("parser_status", sa.String(24), nullable=True),
        sa.Column("context_text", sa.Text(), nullable=False),
        sa.Column("context_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id", "user_id"], ["codex_tasks.id", "codex_tasks.user_id"], name="fk_reproduction_task_owner"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_reproduction_context_owner"),
        sa.UniqueConstraint("task_id", "parsed_document_id", name="uq_reproduction_context_document"),
        sa.CheckConstraint("stage IN ('PLAN','IMPLEMENT_CODE')", name="ck_reproduction_stage"),
        sa.CheckConstraint("source_scope IN ('METADATA_ONLY','ABSTRACT_ONLY','FULL_TEXT')", name="ck_reproduction_scope"),
        sa.CheckConstraint("stage <> 'IMPLEMENT_CODE' OR (source_scope = 'FULL_TEXT' AND parsed_document_id IS NOT NULL)", name="ck_reproduction_implementation_source"),
        sa.CheckConstraint("paper_metadata_version > 0", name="ck_reproduction_metadata_version"),
        sa.CheckConstraint("length(context_text) <= 30000", name="ck_reproduction_context_size"),
    )
    op.create_index("ix_paper_reproduction_contexts_user_id", "paper_reproduction_contexts", ["user_id"])
    op.create_index("ix_paper_reproduction_contexts_paper_id", "paper_reproduction_contexts", ["paper_id"])
    op.create_table(
        "paper_reproduction_source_sections",
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("section_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("parsed_document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_id", "user_id"], ["paper_reproduction_contexts.task_id", "paper_reproduction_contexts.user_id"], name="fk_reproduction_section_owner"),
        sa.ForeignKeyConstraint(["task_id", "parsed_document_id"], ["paper_reproduction_contexts.task_id", "paper_reproduction_contexts.parsed_document_id"], name="fk_reproduction_section_context_document"),
        sa.ForeignKeyConstraint(["parsed_document_id", "section_id"], ["parsed_sections.document_id", "parsed_sections.id"], name="fk_reproduction_selected_document"),
        sa.UniqueConstraint("task_id", "position", name="uq_reproduction_section_order"),
        sa.CheckConstraint("position >= 0", name="ck_reproduction_section_position"),
    )
    op.create_index("ix_paper_reproduction_source_sections_user_id", "paper_reproduction_source_sections", ["user_id"])


def downgrade() -> None:
    op.drop_table("paper_reproduction_source_sections")
    op.drop_table("paper_reproduction_contexts")
    with op.batch_alter_table("codex_tasks") as batch:
        batch.drop_constraint("uq_codex_task_owner", type_="unique")
