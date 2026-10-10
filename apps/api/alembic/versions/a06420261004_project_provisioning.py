"""Approved project templates and durable private repository provisioning.

Revision ID: a06420261004
Revises: a06320261004
"""

import sqlalchemy as sa

from alembic import op

revision = "a06420261004"
down_revision = "a06320261004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("project_archive_bindings") as batch:
        batch.add_column(sa.Column("managed_folder_name", sa.String(160), nullable=True))
        batch.add_column(sa.Column("managed_root_fingerprint", sa.String(64), nullable=True))
        batch.create_check_constraint(
            "ck_archive_managed_scope_pair",
            "(managed_folder_name IS NULL AND managed_root_fingerprint IS NULL) OR "
            "(managed_folder_name IS NOT NULL AND managed_root_fingerprint IS NOT NULL AND length(managed_folder_name) BETWEEN 1 AND 160 AND length(managed_root_fingerprint) = 64)",
        )
        batch.create_unique_constraint(
            "uq_project_archive_binding_project_owner", ["id", "project_id", "user_id"]
        )
    op.create_table(
        "project_provision_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("managed_root_fingerprint", sa.String(64), nullable=False),
        sa.Column("folder_name", sa.String(160), nullable=False),
        sa.Column("repository_name", sa.String(100), nullable=False),
        sa.Column("github_owner", sa.String(39), nullable=False),
        sa.Column("github_owner_id", sa.BigInteger(), nullable=False),
        sa.Column("template_key", sa.String(40), nullable=False),
        sa.Column("template_sha256", sa.String(64), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("files_payload", sa.JSON(none_as_null=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_provision_plan_project_owner",
        ),
        sa.UniqueConstraint("id", "project_id", "user_id", name="uq_provision_plan_project_owner"),
        sa.CheckConstraint("length(managed_root_fingerprint) = 64", name="ck_provision_plan_root"),
        sa.CheckConstraint(
            "length(folder_name) BETWEEN 1 AND 160", name="ck_provision_plan_folder"
        ),
        sa.CheckConstraint(
            "length(repository_name) BETWEEN 1 AND 100", name="ck_provision_plan_repo"
        ),
        sa.CheckConstraint("length(github_owner) BETWEEN 1 AND 39", name="ck_provision_plan_owner"),
        sa.CheckConstraint("github_owner_id > 0", name="ck_provision_plan_owner_id"),
        sa.CheckConstraint(
            "length(template_key) BETWEEN 1 AND 40", name="ck_provision_plan_template"
        ),
        sa.CheckConstraint(
            "length(template_sha256) = 64 AND length(plan_sha256) = 64",
            name="ck_provision_plan_hashes",
        ),
        sa.CheckConstraint(
            "length(CAST(files_payload AS TEXT)) <= 2097152", name="ck_provision_plan_payload_size"
        ),
    )
    for column in ("user_id", "project_id"):
        op.create_index(f"ix_project_provision_plans_{column}", "project_provision_plans", [column])
    op.create_table(
        "project_provision_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("active_project_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="QUEUED"),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("observed_repository_id", sa.BigInteger(), nullable=True),
        sa.Column("binding_id", sa.Uuid(), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_provision_job_project_owner",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "project_id", "user_id"],
            [
                "project_provision_plans.id",
                "project_provision_plans.project_id",
                "project_provision_plans.user_id",
            ],
            name="fk_provision_job_plan_project_owner",
        ),
        sa.ForeignKeyConstraint(
            ["active_project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_provision_job_active_project_owner",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id", "project_id", "user_id"],
            [
                "project_archive_bindings.id",
                "project_archive_bindings.project_id",
                "project_archive_bindings.user_id",
            ],
            name="fk_provision_job_binding_project_owner",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_provision_job_owner"),
        sa.UniqueConstraint("plan_id", name="uq_provision_job_plan"),
        sa.UniqueConstraint("active_project_id", name="uq_provision_job_active_project"),
        sa.CheckConstraint(
            "status IN ('QUEUED','PREPARING','LOCAL_READY','CREATING_REMOTE','REMOTE_CREATED','BINDING','COMPLETED','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_provision_job_status",
        ),
        sa.CheckConstraint(
            "(status IN ('QUEUED','PREPARING','LOCAL_READY','CREATING_REMOTE','REMOTE_CREATED','BINDING','NEEDS_ATTENTION') AND active_project_id IS NOT NULL AND active_project_id = project_id) OR (status IN ('COMPLETED','FAILED','CANCELLED') AND active_project_id IS NULL)",
            name="ck_provision_job_active_project",
        ),
        sa.CheckConstraint(
            "repository_id IS NULL OR repository_id > 0", name="ck_provision_job_repo_id"
        ),
        sa.CheckConstraint(
            "observed_repository_id IS NULL OR observed_repository_id > 0",
            name="ck_provision_job_observed_id",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_provision_job_lease_pair",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR (repository_id IS NOT NULL AND binding_id IS NOT NULL)",
            name="ck_provision_job_completed_binding",
        ),
    )
    for column in ("user_id", "project_id", "plan_id"):
        op.create_index(f"ix_project_provision_jobs_{column}", "project_provision_jobs", [column])
    op.create_index(
        "ix_project_provision_jobs_status_created",
        "project_provision_jobs",
        ["status", "created_at"],
    )
    op.create_table(
        "project_provision_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("event_kind", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["project_provision_jobs.id", "project_provision_jobs.user_id"],
            name="fk_provision_event_job_owner",
        ),
        sa.CheckConstraint("length(event_kind) BETWEEN 1 AND 40", name="ck_provision_event_kind"),
    )
    for column in ("user_id", "job_id"):
        op.create_index(
            f"ix_project_provision_events_{column}", "project_provision_events", [column]
        )


def downgrade() -> None:
    op.drop_table("project_provision_events")
    op.drop_table("project_provision_jobs")
    op.drop_table("project_provision_plans")
    with op.batch_alter_table("project_archive_bindings") as batch:
        batch.drop_constraint("uq_project_archive_binding_project_owner", type_="unique")
        batch.drop_constraint("ck_archive_managed_scope_pair", type_="check")
        batch.drop_column("managed_folder_name")
        batch.drop_column("managed_root_fingerprint")
