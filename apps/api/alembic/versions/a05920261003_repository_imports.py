"""repository_imports

Revision ID: a05920261003
Revises: a05820261003
Create Date: 2026-10-03 20:16:49.767532
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a05920261003"
down_revision: Union[str, Sequence[str], None] = "a05820261003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("code_repositories") as batch:
        batch.alter_column(
            "external_id",
            existing_type=sa.String(240),
            type_=sa.String(320),
            existing_nullable=True,
        )
        batch.create_unique_constraint("uq_code_repository_owner", ["id", "user_id"])
    with op.batch_alter_table("dataset_versions") as batch:
        batch.create_unique_constraint(
            "uq_dataset_version_source_owner", ["id", "dataset_id", "user_id"]
        )
    with op.batch_alter_table("model_versions") as batch:
        batch.create_unique_constraint(
            "uq_model_version_source_owner", ["id", "model_id", "user_id"]
        )
    with op.batch_alter_table("research_entities") as batch:
        batch.create_unique_constraint("uq_research_entity_owner", ["id", "user_id"])
    op.create_table(
        "repository_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("repo_kind", sa.String(length=16), nullable=False),
        sa.Column("repo_id", sa.String(length=320), nullable=False),
        sa.Column("provider_id", sa.String(length=320), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("code_repository_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(repo_kind IN ('code','space') AND entity_kind='code_repository') OR (repo_kind='model' AND entity_kind='model') OR (repo_kind='dataset' AND entity_kind='dataset')",
            name="ck_repository_binding_target",
        ),
        sa.CheckConstraint(
            "length(provider_key) BETWEEN 1 AND 40", name="ck_repository_binding_provider"
        ),
        sa.ForeignKeyConstraint(
            ["code_repository_id", "user_id"],
            ["code_repositories.id", "code_repositories.user_id"],
            name="fk_repository_binding_code_owner",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "user_id"],
            ["research_entities.id", "research_entities.user_id"],
            name="fk_repository_binding_entity_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "entity_id", "user_id", name="uq_repository_binding_target_owner"
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider_key",
            "repo_kind",
            "provider_id",
            name="uq_repository_binding_provider_identity",
        ),
        sa.UniqueConstraint(
            "user_id", "provider_key", "repo_kind", "repo_id", name="uq_repository_binding_identity"
        ),
    )
    op.create_index(
        op.f("ix_repository_bindings_code_repository_id"),
        "repository_bindings",
        ["code_repository_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repository_bindings_entity_id"), "repository_bindings", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_repository_bindings_user_id"), "repository_bindings", ["user_id"], unique=False
    )
    op.create_table(
        "repository_source_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("requested_revision", sa.String(length=160), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("candidate_payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(entity_kind='model' AND model_version_id IS NOT NULL AND dataset_version_id IS NULL) OR (entity_kind='dataset' AND dataset_version_id IS NOT NULL AND model_version_id IS NULL) OR (entity_kind='code_repository' AND model_version_id IS NULL AND dataset_version_id IS NULL)",
            name="ck_repository_snapshot_version_target",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id", "entity_id", "user_id"],
            [
                "repository_bindings.id",
                "repository_bindings.entity_id",
                "repository_bindings.user_id",
            ],
            name="fk_repository_snapshot_binding_target",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id", "entity_id", "user_id"],
            ["dataset_versions.id", "dataset_versions.dataset_id", "dataset_versions.user_id"],
            name="fk_repository_snapshot_dataset_target",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id", "entity_id", "user_id"],
            ["model_versions.id", "model_versions.model_id", "model_versions.user_id"],
            name="fk_repository_snapshot_model_target",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "source_hash", name="uq_repository_snapshot_version"),
        sa.UniqueConstraint("id", "user_id", name="uq_repository_snapshot_owner"),
    )
    op.create_index(
        op.f("ix_repository_source_snapshots_binding_id"),
        "repository_source_snapshots",
        ["binding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repository_source_snapshots_dataset_version_id"),
        "repository_source_snapshots",
        ["dataset_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repository_source_snapshots_entity_id"),
        "repository_source_snapshots",
        ["entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repository_source_snapshots_model_version_id"),
        "repository_source_snapshots",
        ["model_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repository_source_snapshots_user_id"),
        "repository_source_snapshots",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "repository_import_previews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("repo_kind", sa.String(length=16), nullable=False),
        sa.Column("repo_id", sa.String(length=320), nullable=False),
        sa.Column("provider_id", sa.String(length=320), nullable=False),
        sa.Column("requested_revision", sa.String(length=160), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("candidate_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("confirmed_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status='PENDING' AND confirmed_snapshot_id IS NULL AND confirmed_at IS NULL) OR (status='CONFIRMED' AND confirmed_snapshot_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_repository_preview_confirmation",
        ),
        sa.CheckConstraint(
            "length(provider_key) BETWEEN 1 AND 40 AND repo_kind IN ('code','model','dataset','space')",
            name="ck_repository_preview_identity",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','CONFIRMED')", name="ck_repository_preview_status"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_snapshot_id", "user_id"],
            ["repository_source_snapshots.id", "repository_source_snapshots.user_id"],
            name="fk_repository_preview_confirmed_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_repository_import_previews_confirmed_snapshot_id"),
        "repository_import_previews",
        ["confirmed_snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repository_import_previews_user_id"),
        "repository_import_previews",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_repository_import_previews_user_id"), table_name="repository_import_previews"
    )
    op.drop_index(
        op.f("ix_repository_import_previews_confirmed_snapshot_id"),
        table_name="repository_import_previews",
    )
    op.drop_table("repository_import_previews")
    op.drop_index(
        op.f("ix_repository_source_snapshots_user_id"), table_name="repository_source_snapshots"
    )
    op.drop_index(
        op.f("ix_repository_source_snapshots_model_version_id"),
        table_name="repository_source_snapshots",
    )
    op.drop_index(
        op.f("ix_repository_source_snapshots_entity_id"), table_name="repository_source_snapshots"
    )
    op.drop_index(
        op.f("ix_repository_source_snapshots_dataset_version_id"),
        table_name="repository_source_snapshots",
    )
    op.drop_index(
        op.f("ix_repository_source_snapshots_binding_id"), table_name="repository_source_snapshots"
    )
    op.drop_table("repository_source_snapshots")
    op.drop_index(op.f("ix_repository_bindings_user_id"), table_name="repository_bindings")
    op.drop_index(op.f("ix_repository_bindings_entity_id"), table_name="repository_bindings")
    op.drop_index(
        op.f("ix_repository_bindings_code_repository_id"), table_name="repository_bindings"
    )
    op.drop_table("repository_bindings")
    with op.batch_alter_table("research_entities") as batch:
        batch.drop_constraint("uq_research_entity_owner", type_="unique")
    with op.batch_alter_table("model_versions") as batch:
        batch.drop_constraint("uq_model_version_source_owner", type_="unique")
    with op.batch_alter_table("dataset_versions") as batch:
        batch.drop_constraint("uq_dataset_version_source_owner", type_="unique")
    with op.batch_alter_table("code_repositories") as batch:
        batch.drop_constraint("uq_code_repository_owner", type_="unique")
        batch.alter_column(
            "external_id",
            existing_type=sa.String(320),
            type_=sa.String(240),
            existing_nullable=True,
        )
