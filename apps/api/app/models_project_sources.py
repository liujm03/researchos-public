"""Approved local source-cache paths and actual copy receipts; no execution authority."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectPathBinding(Base):
    __tablename__ = "project_path_bindings"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_project_path_binding_owner"),
        UniqueConstraint("archive_binding_id", "relative_path", name="uq_project_path_destination"),
        ForeignKeyConstraint(
            ["archive_binding_id", "project_id", "user_id"],
            [
                "project_archive_bindings.id",
                "project_archive_bindings.project_id",
                "project_archive_bindings.user_id",
            ],
            name="fk_project_path_archive_owner",
        ),
        CheckConstraint(
            "state IN ('PROPOSED','ACTIVE','REVOKED') AND purpose='REPOSITORY_SOURCE' AND no_execution=true",
            name="ck_project_path_scope",
        ),
        CheckConstraint(
            "length(root_fingerprint)=64 AND length(source_root_fingerprint)=64 AND length(scope_sha256)=64",
            name="ck_project_path_hashes",
        ),
        CheckConstraint(
            "(state IN ('PROPOSED','REVOKED') AND approved_hash IS NULL AND approved_by IS NULL AND approved_at IS NULL) OR (state IN ('ACTIVE','REVOKED') AND approved_hash IS NOT NULL AND approved_hash=scope_sha256 AND approved_by IS NOT NULL AND approved_by=user_id AND approved_at IS NOT NULL)",
            name="ck_project_path_approval",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    archive_binding_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    root_fingerprint: Mapped[str] = mapped_column(String(64))
    source_root_fingerprint: Mapped[str] = mapped_column(String(64))
    relative_path: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(
        String(24), default="REPOSITORY_SOURCE", server_default="REPOSITORY_SOURCE"
    )
    no_execution: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    scope_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="PROPOSED", server_default="PROPOSED")
    approved_hash: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectSourcePlan(Base):
    __tablename__ = "project_source_plans"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_project_source_plan_owner"),
        UniqueConstraint(
            "id",
            "asset_snapshot_id",
            "project_id",
            "user_id",
            name="uq_project_source_plan_asset_owner",
        ),
        UniqueConstraint("path_binding_id", name="uq_project_source_plan_binding"),
        UniqueConstraint(
            "id",
            "path_binding_id",
            "project_id",
            "user_id",
            name="uq_project_source_plan_path_owner",
        ),
        ForeignKeyConstraint(
            ["path_binding_id", "project_id", "user_id"],
            [
                "project_path_bindings.id",
                "project_path_bindings.project_id",
                "project_path_bindings.user_id",
            ],
            name="fk_project_source_plan_path_owner",
        ),
        ForeignKeyConstraint(
            ["asset_snapshot_id", "user_id"],
            ["repository_asset_snapshots.id", "repository_asset_snapshots.user_id"],
            name="fk_project_source_plan_snapshot_owner",
        ),
        ForeignKeyConstraint(
            ["source_snapshot_id", "user_id"],
            ["repository_source_snapshots.id", "repository_source_snapshots.user_id"],
            name="fk_project_source_plan_source_owner",
        ),
        CheckConstraint(
            "source_status IN ('MATERIALIZED','PARTIAL') AND state IN ('DRAFT','APPROVED')",
            name="ck_project_source_plan_state",
        ),
        CheckConstraint(
            "length(asset_manifest_sha256)=64 AND length(archive_identity_sha256)=64 AND length(plan_sha256)=64 AND length(commit_sha)=40 AND file_count>0 AND total_bytes>=0",
            name="ck_project_source_plan_limits",
        ),
        CheckConstraint(
            "(state='DRAFT' AND approved_hash IS NULL AND approved_by IS NULL AND approved_at IS NULL) OR (state='APPROVED' AND approved_hash IS NOT NULL AND approved_hash=plan_sha256 AND approved_by IS NOT NULL AND approved_by=user_id AND approved_at IS NOT NULL)",
            name="ck_project_source_plan_approval",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    path_binding_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    asset_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    asset_manifest_sha256: Mapped[str] = mapped_column(String(64))
    archive_identity_sha256: Mapped[str] = mapped_column(String(64))
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider_key: Mapped[str] = mapped_column(String(40))
    repo_kind: Mapped[str] = mapped_column(String(16))
    repo_id: Mapped[str] = mapped_column(String(320))
    provider_id: Mapped[str] = mapped_column(String(320))
    commit_sha: Mapped[str] = mapped_column(String(40))
    source_status: Mapped[str] = mapped_column(String(24))
    gaps_text: Mapped[str] = mapped_column(Text)
    file_count: Mapped[int] = mapped_column(Integer)
    total_bytes: Mapped[int] = mapped_column(BigInteger)
    plan_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="DRAFT", server_default="DRAFT")
    approved_hash: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectSourcePlanFile(Base):
    __tablename__ = "project_source_plan_files"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "file_key_sha256",
            "project_id",
            "user_id",
            name="uq_project_source_plan_file_owner",
        ),
        ForeignKeyConstraint(
            ["plan_id", "asset_snapshot_id", "project_id", "user_id"],
            [
                "project_source_plans.id",
                "project_source_plans.asset_snapshot_id",
                "project_source_plans.project_id",
                "project_source_plans.user_id",
            ],
            name="fk_project_source_file_plan_owner",
        ),
        ForeignKeyConstraint(
            ["asset_file_id", "asset_snapshot_id", "user_id"],
            [
                "repository_asset_files.id",
                "repository_asset_files.snapshot_id",
                "repository_asset_files.user_id",
            ],
            name="fk_project_source_file_snapshot_member",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_project_source_file_attachment_owner",
        ),
        CheckConstraint(
            "length(file_key_sha256)=64 AND length(sha256)=64 AND size_bytes>=0 AND length(path) BETWEEN 1 AND 2000",
            name="ck_project_source_file_bounds",
        ),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    file_key_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    asset_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    asset_file_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)


class ProjectSourceJob(Base):
    __tablename__ = "project_source_jobs"
    __table_args__ = (
        UniqueConstraint(
            "id", "plan_id", "project_id", "user_id", name="uq_project_source_job_owner"
        ),
        UniqueConstraint("active_binding_id", name="uq_project_source_job_active_binding"),
        ForeignKeyConstraint(
            ["plan_id", "path_binding_id", "project_id", "user_id"],
            [
                "project_source_plans.id",
                "project_source_plans.path_binding_id",
                "project_source_plans.project_id",
                "project_source_plans.user_id",
            ],
            name="fk_project_source_job_plan_owner",
        ),
        ForeignKeyConstraint(
            ["active_binding_id", "project_id", "user_id"],
            [
                "project_path_bindings.id",
                "project_path_bindings.project_id",
                "project_path_bindings.user_id",
            ],
            name="fk_project_source_job_active_owner",
        ),
        CheckConstraint(
            "status IN ('QUEUED','COPYING','CANCEL_REQUESTED','COMPLETED','FAILED','CANCELLED','NEEDS_ATTENTION')",
            name="ck_project_source_job_status",
        ),
        CheckConstraint(
            "(status IN ('QUEUED','COPYING','CANCEL_REQUESTED','NEEDS_ATTENTION') AND active_binding_id IS NOT NULL AND active_binding_id=path_binding_id) OR (status IN ('COMPLETED','FAILED','CANCELLED') AND active_binding_id IS NULL)",
            name="ck_project_source_job_slot",
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_project_source_job_lease",
        ),
        CheckConstraint(
            "copied_files>=0 AND copied_bytes>=0", name="ck_project_source_job_progress"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    path_binding_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    active_binding_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", server_default="QUEUED")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    copied_files: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    copied_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    receipt_path: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectSourceFile(Base):
    __tablename__ = "project_source_files"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "job_id",
            "plan_id",
            "file_key_sha256",
            "project_id",
            "user_id",
            name="uq_project_source_checkpoint_identity_owner",
        ),
        ForeignKeyConstraint(
            ["job_id", "plan_id", "project_id", "user_id"],
            [
                "project_source_jobs.id",
                "project_source_jobs.plan_id",
                "project_source_jobs.project_id",
                "project_source_jobs.user_id",
            ],
            name="fk_project_source_receipt_job_owner",
        ),
        ForeignKeyConstraint(
            ["plan_id", "file_key_sha256", "project_id", "user_id"],
            [
                "project_source_plan_files.plan_id",
                "project_source_plan_files.file_key_sha256",
                "project_source_plan_files.project_id",
                "project_source_plan_files.user_id",
            ],
            name="fk_project_source_receipt_file_owner",
        ),
        CheckConstraint(
            "status IN ('COPIED','REUSED','FAILED','QUARANTINED')",
            name="ck_project_source_receipt_status",
        ),
        CheckConstraint(
            "status='FAILED' OR (actual_sha256 IS NOT NULL AND length(actual_sha256)=64 AND actual_size_bytes IS NOT NULL AND actual_size_bytes>=0 AND verified_at IS NOT NULL)",
            name="ck_project_source_receipt_proof",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    file_key_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    actual_sha256: Mapped[str | None] = mapped_column(String(64))
    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    relative_path: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
