"""Preserve actual PDF headings, hierarchy and document order."""

from alembic import op
import sqlalchemy as sa

revision = "a05320261001"
down_revision = "a05220261001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("parsed_sections") as batch:
        batch.alter_column("title", existing_type=sa.String(320), type_=sa.Text(), existing_nullable=True)
        batch.add_column(sa.Column("semantic_key", sa.String(48), nullable=True))
        batch.add_column(sa.Column("heading_level", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("parent_section_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("section_order", sa.Integer(), nullable=True))
        batch.create_unique_constraint("uq_parsed_section_document_id", ["document_id", "id"])
        batch.create_foreign_key("fk_parsed_section_parent_document", "parsed_sections", ["document_id", "parent_section_id"], ["document_id", "id"])
        batch.create_check_constraint("ck_parsed_section_level", "heading_level IS NULL OR heading_level > 0")
        batch.create_check_constraint("ck_parsed_section_order", "section_order IS NULL OR section_order >= 0")
        batch.create_check_constraint("ck_parsed_section_not_self", "parent_section_id IS NULL OR parent_section_id <> id")


def downgrade() -> None:
    # Keep Text titles on downgrade: narrowing to 320 could truncate owner data.
    with op.batch_alter_table("parsed_sections") as batch:
        batch.drop_constraint("fk_parsed_section_parent_document", type_="foreignkey")
        batch.drop_constraint("uq_parsed_section_document_id", type_="unique")
        for name in ("ck_parsed_section_level", "ck_parsed_section_order", "ck_parsed_section_not_self"):
            batch.drop_constraint(name, type_="check")
        for name in ("section_order", "parent_section_id", "heading_level", "semantic_key"):
            batch.drop_column(name)
