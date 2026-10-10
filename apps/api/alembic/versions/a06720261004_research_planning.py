"""Scoped planning grants, permits, attempts and candidates. Revision a06720261004."""

import sqlalchemy as sa
from alembic import op

revision = "a06720261004"
down_revision = "a06620261004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_stage_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("brief_id", sa.Uuid(), nullable=False),
        sa.Column("brief_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile", sa.String(length=80), nullable=False),
        sa.Column("skill_key", sa.String(length=80), nullable=False),
        sa.Column("skill_version", sa.String(length=80), nullable=False),
        sa.Column("focus", sa.Text(), nullable=False),
        sa.Column("model_key", sa.String(length=160), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_jobs", sa.Integer(), nullable=False),
        sa.Column("used_jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="DRAFT"),
        sa.Column(
            "scope", sa.String(length=24), nullable=False, server_default="BRIEF_METADATA_ONLY"
        ),
        sa.Column("no_tools", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("instructions_text", sa.Text(), nullable=False),
        sa.Column("adapter_warnings", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("skills_root_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(state IN ('DRAFT','REVOKED') AND approved_by IS NULL AND approved_at IS NULL AND approved_sha256 IS NULL) OR (state IN ('ACTIVE','REVOKED') AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND approved_sha256 IS NOT NULL AND length(approved_sha256)=64 AND approved_by=user_id AND (state<>'ACTIVE' OR approved_sha256=sha256))",
            name="ck_stage_grant_approval",
        ),
        sa.CheckConstraint(
            "length(sha256)=64 AND length(brief_sha256)=64 AND length(instructions_sha256)=64 AND length(source_manifest_sha256)=64 AND length(skills_root_fingerprint)=64",
            name="ck_stage_grant_hashes",
        ),
        sa.CheckConstraint(
            "max_jobs BETWEEN 1 AND 20 AND used_jobs BETWEEN 0 AND max_jobs AND timeout_seconds BETWEEN 60 AND 1800",
            name="ck_stage_grant_limits",
        ),
        sa.CheckConstraint(
            "scope = 'BRIEF_METADATA_ONLY' AND no_tools = true", name="ck_stage_grant_scope"
        ),
        sa.CheckConstraint("state IN ('DRAFT','ACTIVE','REVOKED')", name="ck_stage_grant_state"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_stage_grant_brief_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "user_id", name="uq_stage_grant_owner"),
    )
    op.create_index(
        "ix_research_stage_grants_project_id", "research_stage_grants", ["project_id"], unique=False
    )
    op.create_index(
        "ix_research_stage_grants_user_id", "research_stage_grants", ["user_id"], unique=False
    )
    op.create_table(
        "research_stage_skill_files",
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("file_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(file_key_sha256)=64 AND length(sha256)=64 AND size_bytes BETWEEN 1 AND 256000 AND length(path) BETWEEN 1 AND 2000",
            name="ck_stage_skill_bounds",
        ),
        sa.CheckConstraint("role IN ('INSTRUCTION','TEMPLATE')", name="ck_stage_skill_role"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["grant_id", "project_id", "user_id"],
            [
                "research_stage_grants.id",
                "research_stage_grants.project_id",
                "research_stage_grants.user_id",
            ],
            name="fk_stage_skill_grant_owner",
        ),
        sa.PrimaryKeyConstraint("grant_id", "file_key_sha256"),
    )
    op.create_index(
        "ix_research_stage_skill_files_user_id",
        "research_stage_skill_files",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "research_planning_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("active_grant_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="QUEUED"),
        sa.Column("manifest_payload", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
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
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(status IN ('RUNNING','CANCEL_REQUESTED','NEEDS_ATTENTION') AND active_grant_id IS NOT NULL AND active_grant_id=grant_id) OR (status IN ('QUEUED','COMPLETED','FAILED','CANCELLED') AND active_grant_id IS NULL)",
            name="ck_planning_job_active_grant",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_planning_job_lease",
        ),
        sa.CheckConstraint(
            "length(manifest_sha256)=64 AND length(CAST(manifest_payload AS TEXT)) <= 2097152",
            name="ck_planning_job_manifest",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','CANCEL_REQUESTED','COMPLETED','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_planning_job_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["active_grant_id", "project_id", "user_id"],
            [
                "research_stage_grants.id",
                "research_stage_grants.project_id",
                "research_stage_grants.user_id",
            ],
            name="fk_planning_job_active_grant_owner",
        ),
        sa.ForeignKeyConstraint(
            ["grant_id", "project_id", "user_id"],
            [
                "research_stage_grants.id",
                "research_stage_grants.project_id",
                "research_stage_grants.user_id",
            ],
            name="fk_planning_job_grant_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_grant_id", name="uq_planning_job_active_grant"),
        sa.UniqueConstraint(
            "id", "grant_id", "project_id", "user_id", name="uq_planning_job_grant_owner"
        ),
        sa.UniqueConstraint("grant_id", "idempotency_key", name="uq_planning_job_key"),
        sa.UniqueConstraint("id", "project_id", "user_id", name="uq_planning_job_owner"),
    )
    op.create_index(
        "ix_planning_jobs_status_created",
        "research_planning_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_research_planning_jobs_grant_id", "research_planning_jobs", ["grant_id"], unique=False
    )
    op.create_index(
        "ix_research_planning_jobs_project_id",
        "research_planning_jobs",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_planning_jobs_user_id", "research_planning_jobs", ["user_id"], unique=False
    )
    op.create_table(
        "research_execution_permits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="RESERVED"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(state='RESERVED' AND issued_at IS NULL) OR (state IN ('ISSUED','STARTED') AND issued_at IS NOT NULL) OR state='REVOKED'",
            name="ck_execution_permit_issue_time",
        ),
        sa.CheckConstraint(
            "state IN ('RESERVED','ISSUED','STARTED','REVOKED') AND length(manifest_sha256)=64",
            name="ck_execution_permit_state_hash",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["job_id", "grant_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.grant_id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_execution_permit_job_grant_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_execution_permit_job"),
        sa.UniqueConstraint("nonce", name="uq_execution_permit_nonce"),
        sa.UniqueConstraint(
            "id", "job_id", "project_id", "user_id", name="uq_execution_permit_owner"
        ),
    )
    op.create_index(
        "ix_research_execution_permits_job_id",
        "research_execution_permits",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_execution_permits_user_id",
        "research_execution_permits",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "research_planning_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("permit_id", sa.Uuid(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="RUNNING"),
        sa.Column("provider_response_id", sa.String(length=200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('RUNNING','COMPLETED','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_planning_attempt_status",
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0)",
            name="ck_planning_attempt_usage",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_planning_attempt_job_owner",
        ),
        sa.ForeignKeyConstraint(
            ["permit_id", "job_id", "project_id", "user_id"],
            [
                "research_execution_permits.id",
                "research_execution_permits.job_id",
                "research_execution_permits.project_id",
                "research_execution_permits.user_id",
            ],
            name="fk_planning_attempt_permit_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "job_id", "project_id", "user_id", name="uq_planning_attempt_job_owner"
        ),
        sa.UniqueConstraint("permit_id", name="uq_planning_attempt_permit"),
    )
    op.create_index(
        "ix_research_planning_attempts_job_id",
        "research_planning_attempts",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_planning_attempts_user_id",
        "research_planning_attempts",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "research_planning_results",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "review_status", sa.String(length=24), nullable=False, server_default="CANDIDATE"
        ),
        sa.Column("disposition", sa.String(length=24), nullable=False, server_default="AVAILABLE"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "length(sha256)=64 AND size_bytes BETWEEN 1 AND 1048576 AND review_status='CANDIDATE'",
            name="ck_planning_result_candidate",
        ),
        sa.CheckConstraint(
            "disposition IN ('AVAILABLE','QUARANTINED')", name="ck_planning_result_disposition"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["attempt_id", "job_id", "project_id", "user_id"],
            [
                "research_planning_attempts.id",
                "research_planning_attempts.job_id",
                "research_planning_attempts.project_id",
                "research_planning_attempts.user_id",
            ],
            name="fk_planning_result_attempt_owner",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_planning_result_job_owner",
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_research_planning_results_user_id",
        "research_planning_results",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("research_planning_results")
    op.drop_table("research_planning_attempts")
    op.drop_table("research_execution_permits")
    op.drop_table("research_planning_jobs")
    op.drop_table("research_stage_skill_files")
    op.drop_table("research_stage_grants")
