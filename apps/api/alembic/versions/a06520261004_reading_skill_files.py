"""Freeze actual original-PDF reading instruction and template source files.

Revision ID: a06520261004
Revises: a06420261004
"""

import sqlalchemy as sa

from alembic import op

revision = "a06520261004"
down_revision = "a06420261004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("paper_reading_approval_plans") as batch:
        batch.add_column(sa.Column("source_manifest_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("source_binding_version", sa.String(40), nullable=True))
        batch.create_check_constraint(
            "ck_reading_plan_source_pair",
            "(source_manifest_sha256 IS NULL AND source_binding_version IS NULL) OR "
            "(source_manifest_sha256 IS NOT NULL AND source_binding_version IS NOT NULL AND length(source_manifest_sha256) = 64 AND source_binding_version = 'original-pdf-files-v1')",
        )
    op.create_table(
        "paper_reading_skill_files",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("file_key_sha256", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("plan_id", "file_key_sha256"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["paper_reading_approval_plans.id", "paper_reading_approval_plans.user_id"],
            name="fk_reading_skill_file_plan_owner",
        ),
        sa.CheckConstraint("length(file_key_sha256) = 64", name="ck_reading_skill_file_key"),
        sa.CheckConstraint("length(path) BETWEEN 1 AND 2000", name="ck_reading_skill_file_path"),
        sa.CheckConstraint("role IN ('INSTRUCTION','TEMPLATE')", name="ck_reading_skill_file_role"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_reading_skill_file_hash"),
        sa.CheckConstraint("size_bytes BETWEEN 0 AND 256000", name="ck_reading_skill_file_size"),
        sa.CheckConstraint("length(content) <= 256000", name="ck_reading_skill_file_content"),
    )
    op.create_index(
        "ix_paper_reading_skill_files_user_id", "paper_reading_skill_files", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("paper_reading_skill_files")
    with op.batch_alter_table("paper_reading_approval_plans") as batch:
        batch.drop_constraint("ck_reading_plan_source_pair", type_="check")
        batch.drop_column("source_manifest_sha256")
        batch.drop_column("source_binding_version")
