"""Durable private archive jobs and explicit scheduling policy.

Revision ID: a06320261004
Revises: a06220261004
"""

import sqlalchemy as sa

from alembic import op

revision = "a06320261004"
down_revision = "a06220261004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("project_archive_bindings") as batch:
        batch.add_column(
            sa.Column("auto_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="60")
        )
        batch.add_column(sa.Column("next_archive_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("workspace_fingerprint", sa.String(64), nullable=True))
        batch.create_check_constraint(
            "ck_archive_interval", "interval_minutes BETWEEN 10 AND 10080"
        )
        batch.create_check_constraint(
            "ck_archive_workspace_fingerprint",
            "workspace_fingerprint IS NULL OR length(workspace_fingerprint) = 64",
        )
        batch.create_check_constraint(
            "ck_archive_auto_scope", "NOT auto_enabled OR workspace_fingerprint IS NOT NULL"
        )
    with op.batch_alter_table("project_archive_versions") as batch:
        batch.create_unique_constraint(
            "uq_project_archive_version_binding_owner", ["id", "binding_id", "user_id"]
        )
    op.create_table(
        "project_archive_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(120), nullable=False),
        sa.Column("trigger_kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="QUEUED"),
        sa.Column("active_binding_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_fingerprint", sa.String(64), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=True),
        sa.Column("manifest_payload", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("id", "user_id", name="uq_project_archive_job_owner"),
        sa.UniqueConstraint("binding_id", "tag", name="uq_project_archive_job_tag"),
        sa.UniqueConstraint("active_binding_id", name="uq_project_archive_job_active_binding"),
        sa.ForeignKeyConstraint(
            ["binding_id", "user_id"],
            ["project_archive_bindings.id", "project_archive_bindings.user_id"],
            name="fk_project_archive_job_binding_owner",
        ),
        sa.ForeignKeyConstraint(
            ["active_binding_id", "user_id"],
            ["project_archive_bindings.id", "project_archive_bindings.user_id"],
            name="fk_project_archive_job_active_owner",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "binding_id", "user_id"],
            [
                "project_archive_versions.id",
                "project_archive_versions.binding_id",
                "project_archive_versions.user_id",
            ],
            name="fk_project_archive_job_version_binding_owner",
        ),
        sa.CheckConstraint("length(tag) BETWEEN 1 AND 120", name="ck_archive_job_tag"),
        sa.CheckConstraint("trigger_kind IN ('MANUAL','SCHEDULED')", name="ck_archive_job_trigger"),
        sa.CheckConstraint(
            "status IN ('QUEUED','PREPARING','COMMITTING','PUBLISHING','COMPLETED','UNCHANGED','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_archive_job_status",
        ),
        sa.CheckConstraint(
            "(status IN ('QUEUED','PREPARING','COMMITTING','PUBLISHING','NEEDS_ATTENTION') AND active_binding_id IS NOT NULL AND active_binding_id = binding_id) OR (status IN ('COMPLETED','UNCHANGED','FAILED','CANCELLED') AND active_binding_id IS NULL)",
            name="ck_archive_job_active_binding",
        ),
        sa.CheckConstraint("length(workspace_fingerprint) = 64", name="ck_archive_job_workspace"),
        sa.CheckConstraint(
            "manifest_sha256 IS NULL OR length(manifest_sha256) = 64",
            name="ck_archive_job_manifest",
        ),
        sa.CheckConstraint(
            "manifest_payload IS NULL OR length(CAST(manifest_payload AS TEXT)) <= 2097152",
            name="ck_archive_job_manifest_size",
        ),
        sa.CheckConstraint(
            "commit_sha IS NULL OR length(commit_sha) = 40", name="ck_archive_job_commit"
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_archive_job_lease_pair",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR (version_id IS NOT NULL AND commit_sha IS NOT NULL AND manifest_sha256 IS NOT NULL)",
            name="ck_archive_job_completed_version",
        ),
    )
    op.create_index(
        "ix_project_archive_jobs_status_created", "project_archive_jobs", ["status", "created_at"]
    )
    for column in ("user_id", "binding_id"):
        op.create_index(f"ix_project_archive_jobs_{column}", "project_archive_jobs", [column])
    op.create_table(
        "project_archive_job_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("event_kind", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("id", "user_id", name="uq_project_archive_job_event_owner"),
        sa.ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["project_archive_jobs.id", "project_archive_jobs.user_id"],
            name="fk_project_archive_job_event_owner",
        ),
        sa.CheckConstraint("length(event_kind) BETWEEN 1 AND 40", name="ck_archive_job_event_kind"),
    )
    for column in ("user_id", "job_id"):
        op.create_index(
            f"ix_project_archive_job_events_{column}", "project_archive_job_events", [column]
        )


def downgrade() -> None:
    op.drop_table("project_archive_job_events")
    op.drop_table("project_archive_jobs")
    with op.batch_alter_table("project_archive_versions") as batch:
        batch.drop_constraint("uq_project_archive_version_binding_owner", type_="unique")
    with op.batch_alter_table("project_archive_bindings") as batch:
        for name in (
            "ck_archive_interval",
            "ck_archive_workspace_fingerprint",
            "ck_archive_auto_scope",
        ):
            batch.drop_constraint(name, type_="check")
        for column in (
            "auto_enabled",
            "interval_minutes",
            "next_archive_at",
            "workspace_fingerprint",
        ):
            batch.drop_column(column)
