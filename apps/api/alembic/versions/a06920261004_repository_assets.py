"""Pinned public repository assets and verified owner cache receipts. Revision a06920261004."""

import sqlalchemy as sa
from alembic import op

revision = "a06920261004"
down_revision = "a06820261004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_asset_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("repo_kind", sa.String(length=16), nullable=False),
        sa.Column("repo_id", sa.String(length=320), nullable=False),
        sa.Column("license_id", sa.String(length=500), nullable=True),
        sa.Column("provider_id", sa.String(length=320), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("selected_files", sa.Integer(), nullable=False),
        sa.Column("selected_bytes", sa.BigInteger(), nullable=False),
        sa.Column("max_bytes", sa.BigInteger(), nullable=False),
        sa.Column("max_files", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("inventory_complete", sa.Boolean(), nullable=False),
        sa.Column("gaps_text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="DRAFT"),
        sa.Column("approved_hash", sa.String(length=64), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(state='DRAFT' AND approved_hash IS NULL AND approved_by IS NULL AND approved_at IS NULL) OR (state='APPROVED' AND approved_hash IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND approved_by=user_id AND approved_hash=plan_sha256)",
            name="ck_asset_plan_approval",
        ),
        sa.CheckConstraint(
            "length(commit_sha)=40 AND length(plan_sha256)=64 AND length(manifest_sha256)=64 AND length(source_snapshot_sha256)=64",
            name="ck_asset_plan_hashes",
        ),
        sa.CheckConstraint(
            "max_bytes BETWEEN 1 AND 1073741824 AND max_files BETWEEN 1 AND 10000 AND selected_files BETWEEN 0 AND total_files AND total_files <= 10000 AND selected_bytes>=0 AND (total_bytes IS NULL OR total_bytes>=selected_bytes)",
            name="ck_asset_plan_limits",
        ),
        sa.CheckConstraint(
            "scope IN ('FULL_INVENTORY','SELECTED_SUBSET') AND state IN ('DRAFT','APPROVED')",
            name="ck_asset_plan_scope_state",
        ),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id", "user_id"],
            ["repository_source_snapshots.id", "repository_source_snapshots.user_id"],
            name="fk_asset_plan_source_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_asset_plan_owner"),
        sa.UniqueConstraint(
            "id", "source_snapshot_id", "user_id", name="uq_asset_plan_source_owner"
        ),
    )
    op.create_index(
        "ix_repository_asset_plans_source_snapshot_id",
        "repository_asset_plans",
        ["source_snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_repository_asset_plans_user_id", "repository_asset_plans", ["user_id"], unique=False
    )
    op.create_table(
        "repository_asset_plan_files",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("file_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("digest_algorithm", sa.String(length=24), nullable=True),
        sa.Column("digest", sa.String(length=64), nullable=True),
        sa.Column("file_kind", sa.String(length=16), nullable=False),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("issue", sa.String(length=160), nullable=True),
        sa.Column("remote_identity", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(file_key_sha256)=64 AND length(path) BETWEEN 1 AND 2000 AND (size_bytes IS NULL OR size_bytes>=0)",
            name="ck_asset_plan_file_bounds",
        ),
        sa.CheckConstraint(
            "digest_algorithm IS NULL OR digest_algorithm IN ('GIT_BLOB_SHA1','SHA256')",
            name="ck_asset_plan_file_digest",
        ),
        sa.CheckConstraint(
            "file_kind IN ('REGULAR','LFS','SYMLINK','SUBMODULE')", name="ck_asset_plan_file_kind"
        ),
        sa.CheckConstraint(
            "NOT selected OR (supported=true AND size_bytes IS NOT NULL AND digest_algorithm IS NOT NULL AND digest IS NOT NULL)",
            name="ck_asset_plan_selected_payload",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["repository_asset_plans.id", "repository_asset_plans.user_id"],
            name="fk_asset_plan_file_owner",
        ),
        sa.PrimaryKeyConstraint("plan_id", "file_key_sha256"),
        sa.UniqueConstraint(
            "plan_id", "file_key_sha256", "user_id", name="uq_asset_plan_file_owner"
        ),
    )
    op.create_index(
        "ix_repository_asset_plan_files_user_id",
        "repository_asset_plan_files",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "repository_asset_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("active_plan_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="QUEUED"),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stored_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stored_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status IN ('QUEUED','DOWNLOADING','CANCEL_REQUESTED','NEEDS_ATTENTION') AND active_plan_id IS NOT NULL AND active_plan_id=plan_id) OR (status IN ('COMPLETED','FAILED','CANCELLED') AND active_plan_id IS NULL)",
            name="ck_asset_job_active_plan",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_asset_job_lease",
        ),
        sa.CheckConstraint("stored_files>=0 AND stored_bytes>=0", name="ck_asset_job_progress"),
        sa.CheckConstraint(
            "status IN ('QUEUED','DOWNLOADING','CANCEL_REQUESTED','COMPLETED','FAILED','CANCELLED','NEEDS_ATTENTION')",
            name="ck_asset_job_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["active_plan_id", "user_id"],
            ["repository_asset_plans.id", "repository_asset_plans.user_id"],
            name="fk_asset_job_active_owner",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["repository_asset_plans.id", "repository_asset_plans.user_id"],
            name="fk_asset_job_plan_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_plan_id", name="uq_asset_job_active_plan"),
        sa.UniqueConstraint("id", "plan_id", "user_id", name="uq_asset_job_plan_owner"),
    )
    op.create_index(
        "ix_asset_jobs_status_created",
        "repository_asset_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_repository_asset_jobs_plan_id", "repository_asset_jobs", ["plan_id"], unique=False
    )
    op.create_index(
        "ix_repository_asset_jobs_user_id", "repository_asset_jobs", ["user_id"], unique=False
    )
    op.create_table(
        "repository_asset_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("stored_files", sa.Integer(), nullable=False),
        sa.Column("stored_bytes", sa.BigInteger(), nullable=False),
        sa.Column("gaps_text", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('MATERIALIZED','PARTIAL') AND length(manifest_sha256)=64 AND stored_files>=0 AND stored_bytes>=0",
            name="ck_asset_snapshot_proof",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["job_id", "plan_id", "user_id"],
            [
                "repository_asset_jobs.id",
                "repository_asset_jobs.plan_id",
                "repository_asset_jobs.user_id",
            ],
            name="fk_asset_snapshot_job_owner",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "source_snapshot_id", "user_id"],
            [
                "repository_asset_plans.id",
                "repository_asset_plans.source_snapshot_id",
                "repository_asset_plans.user_id",
            ],
            name="fk_asset_snapshot_source_plan_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_asset_snapshot_job"),
        sa.UniqueConstraint(
            "id", "job_id", "plan_id", "user_id", name="uq_asset_snapshot_job_owner"
        ),
    )
    op.create_index(
        "ix_repository_asset_snapshots_user_id",
        "repository_asset_snapshots",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "repository_asset_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("file_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("actual_sha256", sa.String(length=64), nullable=True),
        sa.Column("actual_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("remote_verified", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('STORING','STORED','FAILED','UNSUPPORTED','QUARANTINED')",
            name="ck_asset_file_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('STORED','QUARANTINED') OR (attachment_id IS NOT NULL AND actual_sha256 IS NOT NULL AND length(actual_sha256)=64 AND actual_size_bytes IS NOT NULL AND actual_size_bytes>=0 AND remote_verified=true)",
            name="ck_asset_file_stored_proof",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_asset_file_attachment_owner",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "file_key_sha256", "user_id"],
            [
                "repository_asset_plan_files.plan_id",
                "repository_asset_plan_files.file_key_sha256",
                "repository_asset_plan_files.user_id",
            ],
            name="fk_asset_file_inventory_owner",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "plan_id", "user_id"],
            [
                "repository_asset_jobs.id",
                "repository_asset_jobs.plan_id",
                "repository_asset_jobs.user_id",
            ],
            name="fk_asset_file_job_owner",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "job_id", "plan_id", "user_id"],
            [
                "repository_asset_snapshots.id",
                "repository_asset_snapshots.job_id",
                "repository_asset_snapshots.plan_id",
                "repository_asset_snapshots.user_id",
            ],
            name="fk_asset_file_snapshot_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repository_asset_files_job_id", "repository_asset_files", ["job_id"], unique=False
    )
    op.create_index(
        "ix_repository_asset_files_user_id", "repository_asset_files", ["user_id"], unique=False
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Asset downgrade requires an online owner-data audit")
    if any(
        op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM " + table))
        for table in (
            "repository_asset_plans",
            "repository_asset_plan_files",
            "repository_asset_jobs",
            "repository_asset_files",
            "repository_asset_snapshots",
        )
    ):
        raise RuntimeError(
            "Asset owner data is not representable before a069; preserve backup and restore into an isolated compatible database"
        )
    op.drop_table("repository_asset_files")
    op.drop_table("repository_asset_snapshots")
    op.drop_table("repository_asset_jobs")
    op.drop_table("repository_asset_plan_files")
    op.drop_table("repository_asset_plans")
