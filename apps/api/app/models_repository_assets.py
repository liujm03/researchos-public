"""Approved immutable public-repository inventory and measured stored byte receipts."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RepositoryAssetPlan(Base):
    __tablename__ = "repository_asset_plans"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_asset_plan_owner"),
        UniqueConstraint("id", "source_snapshot_id", "user_id", name="uq_asset_plan_source_owner"),
        ForeignKeyConstraint(
            ["source_snapshot_id", "user_id"],
            ["repository_source_snapshots.id", "repository_source_snapshots.user_id"],
            name="fk_asset_plan_source_owner",
        ),
        CheckConstraint(
            "scope IN ('FULL_INVENTORY','SELECTED_SUBSET') AND state IN ('DRAFT','APPROVED')",
            name="ck_asset_plan_scope_state",
        ),
        CheckConstraint(
            "max_bytes BETWEEN 1 AND 1073741824 AND max_files BETWEEN 1 AND 10000 AND selected_files BETWEEN 0 AND total_files AND total_files <= 10000 AND selected_bytes>=0 AND (total_bytes IS NULL OR total_bytes>=selected_bytes)",
            name="ck_asset_plan_limits",
        ),
        CheckConstraint(
            "length(commit_sha)=40 AND length(plan_sha256)=64 AND length(manifest_sha256)=64 AND length(source_snapshot_sha256)=64",
            name="ck_asset_plan_hashes",
        ),
        CheckConstraint(
            "(state='DRAFT' AND approved_hash IS NULL AND approved_by IS NULL AND approved_at IS NULL) OR (state='APPROVED' AND approved_hash IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND approved_by=user_id AND approved_hash=plan_sha256)",
            name="ck_asset_plan_approval",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    source_snapshot_sha256: Mapped[str] = mapped_column(String(64))
    provider_key: Mapped[str] = mapped_column(String(40))
    repo_kind: Mapped[str] = mapped_column(String(16))
    repo_id: Mapped[str] = mapped_column(String(320))
    license_id: Mapped[str | None] = mapped_column(String(500))
    provider_id: Mapped[str] = mapped_column(String(320))
    commit_sha: Mapped[str] = mapped_column(String(40))
    plan_sha256: Mapped[str] = mapped_column(String(64))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    total_files: Mapped[int] = mapped_column(Integer)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    selected_files: Mapped[int] = mapped_column(Integer)
    selected_bytes: Mapped[int] = mapped_column(BigInteger)
    max_bytes: Mapped[int] = mapped_column(BigInteger)
    max_files: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(24))
    inventory_complete: Mapped[bool] = mapped_column(Boolean)
    gaps_text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="DRAFT", server_default="DRAFT")
    approved_hash: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepositoryAssetPlanFile(Base):
    __tablename__ = "repository_asset_plan_files"
    __table_args__ = (
        UniqueConstraint("plan_id", "file_key_sha256", "user_id", name="uq_asset_plan_file_owner"),
        ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["repository_asset_plans.id", "repository_asset_plans.user_id"],
            name="fk_asset_plan_file_owner",
        ),
        CheckConstraint(
            "length(file_key_sha256)=64 AND length(path) BETWEEN 1 AND 2000 AND (size_bytes IS NULL OR size_bytes>=0)",
            name="ck_asset_plan_file_bounds",
        ),
        CheckConstraint(
            "file_kind IN ('REGULAR','LFS','SYMLINK','SUBMODULE')", name="ck_asset_plan_file_kind"
        ),
        CheckConstraint(
            "digest_algorithm IS NULL OR digest_algorithm IN ('GIT_BLOB_SHA1','SHA256')",
            name="ck_asset_plan_file_digest",
        ),
        CheckConstraint(
            "NOT selected OR (supported=true AND size_bytes IS NOT NULL AND digest_algorithm IS NOT NULL AND digest IS NOT NULL)",
            name="ck_asset_plan_selected_payload",
        ),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    file_key_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    digest_algorithm: Mapped[str | None] = mapped_column(String(24))
    digest: Mapped[str | None] = mapped_column(String(64))
    file_kind: Mapped[str] = mapped_column(String(16))
    supported: Mapped[bool] = mapped_column(Boolean)
    selected: Mapped[bool] = mapped_column(Boolean)
    issue: Mapped[str | None] = mapped_column(String(160))
    remote_identity: Mapped[str] = mapped_column(Text)


class RepositoryAssetJob(Base):
    __tablename__ = "repository_asset_jobs"
    __table_args__ = (
        UniqueConstraint("id", "plan_id", "user_id", name="uq_asset_job_plan_owner"),
        UniqueConstraint("active_plan_id", name="uq_asset_job_active_plan"),
        ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["repository_asset_plans.id", "repository_asset_plans.user_id"],
            name="fk_asset_job_plan_owner",
        ),
        ForeignKeyConstraint(
            ["active_plan_id", "user_id"],
            ["repository_asset_plans.id", "repository_asset_plans.user_id"],
            name="fk_asset_job_active_owner",
        ),
        CheckConstraint(
            "status IN ('QUEUED','DOWNLOADING','CANCEL_REQUESTED','COMPLETED','FAILED','CANCELLED','NEEDS_ATTENTION')",
            name="ck_asset_job_status",
        ),
        CheckConstraint(
            "(status IN ('QUEUED','DOWNLOADING','CANCEL_REQUESTED','NEEDS_ATTENTION') AND active_plan_id IS NOT NULL AND active_plan_id=plan_id) OR (status IN ('COMPLETED','FAILED','CANCELLED') AND active_plan_id IS NULL)",
            name="ck_asset_job_active_plan",
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_asset_job_lease",
        ),
        CheckConstraint("stored_files>=0 AND stored_bytes>=0", name="ck_asset_job_progress"),
        Index("ix_asset_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    active_plan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", server_default="QUEUED")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stored_files: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stored_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RepositoryAssetFile(Base):
    __tablename__ = "repository_asset_files"
    __table_args__ = (
        UniqueConstraint(
            "id", "snapshot_id", "user_id", name="uq_asset_file_snapshot_member_owner"
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "job_id", "plan_id", "user_id"],
            [
                "repository_asset_snapshots.id",
                "repository_asset_snapshots.job_id",
                "repository_asset_snapshots.plan_id",
                "repository_asset_snapshots.user_id",
            ],
            name="fk_asset_file_snapshot_owner",
        ),
        ForeignKeyConstraint(
            ["job_id", "plan_id", "user_id"],
            [
                "repository_asset_jobs.id",
                "repository_asset_jobs.plan_id",
                "repository_asset_jobs.user_id",
            ],
            name="fk_asset_file_job_owner",
        ),
        ForeignKeyConstraint(
            ["plan_id", "file_key_sha256", "user_id"],
            [
                "repository_asset_plan_files.plan_id",
                "repository_asset_plan_files.file_key_sha256",
                "repository_asset_plan_files.user_id",
            ],
            name="fk_asset_file_inventory_owner",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_asset_file_attachment_owner",
        ),
        CheckConstraint(
            "status IN ('STORING','STORED','FAILED','UNSUPPORTED','QUARANTINED')",
            name="ck_asset_file_status",
        ),
        CheckConstraint(
            "status NOT IN ('STORED','QUARANTINED') OR (attachment_id IS NOT NULL AND actual_sha256 IS NOT NULL AND length(actual_sha256)=64 AND actual_size_bytes IS NOT NULL AND actual_size_bytes>=0 AND remote_verified=true)",
            name="ck_asset_file_stored_proof",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    file_key_sha256: Mapped[str] = mapped_column(String(64))
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24))
    actual_sha256: Mapped[str | None] = mapped_column(String(64))
    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    remote_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepositoryAssetSnapshot(Base):
    __tablename__ = "repository_asset_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_asset_snapshot_owner"),
        UniqueConstraint("job_id", name="uq_asset_snapshot_job"),
        UniqueConstraint("id", "job_id", "plan_id", "user_id", name="uq_asset_snapshot_job_owner"),
        ForeignKeyConstraint(
            ["job_id", "plan_id", "user_id"],
            [
                "repository_asset_jobs.id",
                "repository_asset_jobs.plan_id",
                "repository_asset_jobs.user_id",
            ],
            name="fk_asset_snapshot_job_owner",
        ),
        ForeignKeyConstraint(
            ["plan_id", "source_snapshot_id", "user_id"],
            [
                "repository_asset_plans.id",
                "repository_asset_plans.source_snapshot_id",
                "repository_asset_plans.user_id",
            ],
            name="fk_asset_snapshot_source_plan_owner",
        ),
        CheckConstraint(
            "status IN ('MATERIALIZED','PARTIAL') AND length(manifest_sha256)=64 AND stored_files>=0 AND stored_bytes>=0",
            name="ck_asset_snapshot_proof",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    stored_files: Mapped[int] = mapped_column(Integer)
    stored_bytes: Mapped[int] = mapped_column(BigInteger)
    gaps_text: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
