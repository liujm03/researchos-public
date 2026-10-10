"""Owner-scoped private project archive inventory.

Revision ID: a06220261004
Revises: a06120261003
"""

import sqlalchemy as sa

from alembic import op

revision = "a06220261004"
down_revision = "a06120261003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("research_projects") as batch:
        batch.create_unique_constraint("uq_research_project_owner", ["id", "user_id"])
    op.create_table(
        "project_archive_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_key", sa.String(80), nullable=False),
        sa.Column("local_project_id", sa.String(160), nullable=False),
        sa.Column("github_owner", sa.String(39), nullable=False),
        sa.Column("github_owner_id", sa.BigInteger(), nullable=False),
        sa.Column("github_repository", sa.String(100), nullable=False),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_project_archive_binding_project_owner",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_project_archive_binding_owner"),
        sa.UniqueConstraint("user_id", "project_id", name="uq_project_archive_binding_project"),
        sa.UniqueConstraint(
            "user_id", "workspace_key", name="uq_project_archive_binding_workspace"
        ),
        sa.UniqueConstraint(
            "user_id", "github_repository_id", name="uq_project_archive_binding_repo"
        ),
        sa.CheckConstraint(
            "length(workspace_key) BETWEEN 1 AND 80", name="ck_archive_workspace_key"
        ),
        sa.CheckConstraint(
            "length(local_project_id) BETWEEN 1 AND 160", name="ck_archive_local_id"
        ),
        sa.CheckConstraint("length(github_owner) BETWEEN 1 AND 39", name="ck_archive_github_owner"),
        sa.CheckConstraint(
            "length(github_repository) BETWEEN 1 AND 100", name="ck_archive_github_repo"
        ),
        sa.CheckConstraint(
            "github_owner_id > 0 AND github_repository_id > 0", name="ck_archive_github_ids"
        ),
    )
    op.create_table(
        "project_archive_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(120), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("parent_commit", sa.String(40), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("remote_tag_commit", sa.String(40), nullable=True),
        sa.Column("remote_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["binding_id", "user_id"],
            ["project_archive_bindings.id", "project_archive_bindings.user_id"],
            name="fk_project_archive_version_binding_owner",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_project_archive_version_owner"),
        sa.UniqueConstraint("binding_id", "tag", name="uq_project_archive_version_tag"),
        sa.CheckConstraint("length(tag) BETWEEN 1 AND 120", name="ck_archive_version_tag"),
        sa.CheckConstraint("length(commit_sha) = 40", name="ck_archive_version_commit"),
        sa.CheckConstraint("length(manifest_sha256) = 64", name="ck_archive_version_manifest"),
        sa.CheckConstraint(
            "parent_commit IS NULL OR length(parent_commit) = 40", name="ck_archive_version_parent"
        ),
        sa.CheckConstraint(
            "file_count >= 0 AND total_bytes >= 0", name="ck_archive_version_totals"
        ),
        sa.CheckConstraint(
            "(remote_tag_commit IS NULL AND remote_verified_at IS NULL) OR (remote_tag_commit IS NOT NULL AND remote_verified_at IS NOT NULL AND remote_tag_commit = commit_sha)",
            name="ck_archive_version_remote_pair",
        ),
    )
    op.create_table(
        "project_archive_files",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("version_id", "path"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["version_id", "user_id"],
            ["project_archive_versions.id", "project_archive_versions.user_id"],
            name="fk_project_archive_file_version_owner",
        ),
        sa.CheckConstraint("length(path) BETWEEN 1 AND 1024", name="ck_archive_file_path"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_archive_file_hash"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_archive_file_size"),
    )
    for table, columns in (
        ("project_archive_bindings", ("user_id", "project_id")),
        ("project_archive_versions", ("user_id", "binding_id")),
        ("project_archive_files", ("user_id",)),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("project_archive_files")
    op.drop_table("project_archive_versions")
    op.drop_table("project_archive_bindings")
    with op.batch_alter_table("research_projects") as batch:
        batch.drop_constraint("uq_research_project_owner", type_="unique")
