"""Bounded execution grants, one-shot permits and actual candidate receipts."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def plan_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["plan_id", "version_id", "project_id", "user_id"],
        [
            "baseline_run_plans.id",
            "baseline_run_plans.version_id",
            "baseline_run_plans.project_id",
            "baseline_run_plans.user_id",
        ],
        name=name,
    )


def job_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["job_id", "plan_id", "version_id", "project_id", "user_id"],
        [
            "baseline_run_jobs.id",
            "baseline_run_jobs.plan_id",
            "baseline_run_jobs.version_id",
            "baseline_run_jobs.project_id",
            "baseline_run_jobs.user_id",
        ],
        name=name,
    )


class BaselineRunPlan(Base):
    __tablename__ = "baseline_run_plans"
    __table_args__ = (
        UniqueConstraint(
            "id", "version_id", "project_id", "user_id", name="uq_baseline_run_plan_owner"
        ),
        ForeignKeyConstraint(
            ["version_id", "version_sha256", "project_id", "user_id"],
            [
                "baseline_versions.id",
                "baseline_versions.sha256",
                "baseline_versions.project_id",
                "baseline_versions.user_id",
            ],
            name="fk_baseline_run_version_hash_owner",
        ),
        ForeignKeyConstraint(
            ["material_check_id", "version_id", "project_id", "user_id"],
            [
                "baseline_material_checks.id",
                "baseline_material_checks.version_id",
                "baseline_material_checks.project_id",
                "baseline_material_checks.user_id",
            ],
            name="fk_baseline_run_material_owner",
        ),
        ForeignKeyConstraint(
            ["entry_asset_id", "version_id", "project_id", "user_id"],
            [
                "baseline_assets.id",
                "baseline_assets.version_id",
                "baseline_assets.project_id",
                "baseline_assets.user_id",
            ],
            name="fk_baseline_run_entry_owner",
        ),
        ForeignKeyConstraint(
            ["config_asset_id", "version_id", "project_id", "user_id"],
            [
                "baseline_assets.id",
                "baseline_assets.version_id",
                "baseline_assets.project_id",
                "baseline_assets.user_id",
            ],
            name="fk_baseline_run_config_owner",
        ),
        CheckConstraint(
            "profile='PYTHON_SCRIPT_V1' AND state IN ('DRAFT','ACTIVE','REVOKED') AND length(sha256)=64 AND length(input_manifest_sha256)=64",
            name="ck_baseline_run_plan_scope",
        ),
        CheckConstraint(
            "max_jobs BETWEEN 1 AND 20 AND used_jobs>=0 AND used_jobs<=max_jobs AND random_seed BETWEEN 0 AND 4294967295",
            name="ck_baseline_run_plan_budget",
        ),
        CheckConstraint(
            "state!='ACTIVE' OR (image_id IS NOT NULL AND daemon_id IS NOT NULL AND material_check_id IS NOT NULL AND material_check_sha256 IS NOT NULL AND entry_asset_id IS NOT NULL AND config_asset_id IS NOT NULL)",
            name="ck_baseline_run_active_complete",
        ),
        CheckConstraint(
            "(state IN ('DRAFT','REVOKED') AND approved_sha256 IS NULL AND approved_by IS NULL AND approved_at IS NULL) OR (state IN ('ACTIVE','REVOKED') AND approved_sha256 IS NOT NULL AND approved_sha256=sha256 AND approved_by IS NOT NULL AND approved_by=user_id AND approved_at IS NOT NULL)",
            name="ck_baseline_run_approval",
        ),
        CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 1800 AND cpu_millicores BETWEEN 100 AND 4000 AND memory_bytes BETWEEN 67108864 AND 8589934592 AND pids BETWEEN 8 AND 256 AND max_input_bytes BETWEEN 1 AND 1073741824 AND max_input_files BETWEEN 1 AND 1000 AND max_log_bytes BETWEEN 1024 AND 8388608 AND max_output_bytes BETWEEN 1024 AND 268435456 AND max_output_files BETWEEN 1 AND 1000",
            name="ck_baseline_run_limits",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version_sha256: Mapped[str] = mapped_column(String(64))
    material_check_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    material_check_sha256: Mapped[str | None] = mapped_column(String(64))
    image_id: Mapped[str | None] = mapped_column(String(80))
    daemon_id: Mapped[str | None] = mapped_column(String(200))
    profile: Mapped[str] = mapped_column(String(40))
    entry_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    config_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    random_seed: Mapped[int] = mapped_column(BigInteger)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    cpu_millicores: Mapped[int] = mapped_column(Integer)
    memory_bytes: Mapped[int] = mapped_column(BigInteger)
    pids: Mapped[int] = mapped_column(Integer)
    max_input_bytes: Mapped[int] = mapped_column(BigInteger)
    max_input_files: Mapped[int] = mapped_column(Integer)
    max_log_bytes: Mapped[int] = mapped_column(BigInteger)
    max_output_bytes: Mapped[int] = mapped_column(BigInteger)
    max_output_files: Mapped[int] = mapped_column(Integer)
    input_manifest_sha256: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    gaps_text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="DRAFT", server_default="DRAFT")
    approved_sha256: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_jobs: Mapped[int] = mapped_column(Integer)
    used_jobs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BaselineRunPlanInput(Base):
    __tablename__ = "baseline_run_plan_inputs"
    __table_args__ = (
        plan_fk("fk_baseline_run_input_plan_owner"),
        ForeignKeyConstraint(
            ["version_id", "dataset_version_id", "project_id", "user_id"],
            [
                "baseline_dataset_bindings.version_id",
                "baseline_dataset_bindings.dataset_version_id",
                "baseline_dataset_bindings.project_id",
                "baseline_dataset_bindings.user_id",
            ],
            name="fk_baseline_run_input_dataset_owner",
        ),
        ForeignKeyConstraint(
            ["asset_id", "version_id", "project_id", "user_id"],
            [
                "baseline_assets.id",
                "baseline_assets.version_id",
                "baseline_assets.project_id",
                "baseline_assets.user_id",
            ],
            name="fk_baseline_run_input_asset_owner",
        ),
        UniqueConstraint("plan_id", "asset_id", name="uq_baseline_run_input_asset"),
        UniqueConstraint("plan_id", "path", name="uq_baseline_run_input_path"),
        CheckConstraint(
            "role IN ('CODE','CONFIG','ENVIRONMENT_LOCK','EVALUATOR','WEIGHTS','DATA','SPLIT_MANIFEST') AND length(source_sha256)=64 AND length(input_sha256)=64 AND size_bytes>=0",
            name="ck_baseline_run_input_proof",
        ),
        CheckConstraint(
            "(role='DATA' AND dataset_version_id IS NOT NULL AND dataset_split IS NOT NULL AND dataset_split IN ('TRAIN','VALIDATION') AND sample_id IS NOT NULL AND group_id IS NOT NULL AND projected_content IS NULL) OR (role='SPLIT_MANIFEST' AND dataset_version_id IS NOT NULL AND dataset_split IS NULL AND sample_id IS NULL AND group_id IS NULL AND projected_content IS NOT NULL) OR (role NOT IN ('DATA','SPLIT_MANIFEST') AND dataset_version_id IS NULL AND dataset_split IS NULL AND sample_id IS NULL AND group_id IS NULL AND projected_content IS NULL)",
            name="ck_baseline_run_input_training_scope",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(24))
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    dataset_split: Mapped[str | None] = mapped_column(String(16))
    sample_id: Mapped[str | None] = mapped_column(String(256))
    group_id: Mapped[str | None] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(String(2000))
    source_sha256: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    projected_content: Mapped[str | None] = mapped_column(Text)
    source_scope_payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class BaselineRunJob(Base):
    __tablename__ = "baseline_run_jobs"
    __table_args__ = (
        UniqueConstraint(
            "id", "plan_id", "version_id", "project_id", "user_id", name="uq_baseline_run_job_owner"
        ),
        UniqueConstraint("plan_id", "idempotency_key", name="uq_baseline_run_job_idempotency"),
        UniqueConstraint("active_owner_id", name="uq_baseline_run_active_owner"),
        plan_fk("fk_baseline_run_job_plan_owner"),
        CheckConstraint(
            "status IN ('QUEUED','STARTING','RUNNING','CANCEL_REQUESTED','COMPLETED_CANDIDATE','FAILED','CANCELLED','NEEDS_ATTENTION')",
            name="ck_baseline_run_job_status",
        ),
        CheckConstraint(
            "(status IN ('STARTING','RUNNING','CANCEL_REQUESTED','NEEDS_ATTENTION') AND active_owner_id IS NOT NULL AND active_owner_id=user_id) OR (status IN ('QUEUED','COMPLETED_CANDIDATE','FAILED','CANCELLED') AND active_owner_id IS NULL)",
            name="ck_baseline_run_job_active_slot",
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_baseline_run_job_lease",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    active_owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(
        String(32), default="QUEUED", server_default="QUEUED", index=True
    )
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    manifest_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BaselineRunPermit(Base):
    __tablename__ = "baseline_run_permits"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "job_id",
            "plan_id",
            "version_id",
            "project_id",
            "user_id",
            name="uq_baseline_run_permit_owner",
        ),
        UniqueConstraint("job_id", name="uq_baseline_run_permit_once"),
        UniqueConstraint(
            "id",
            "nonce",
            "job_id",
            "plan_id",
            "version_id",
            "project_id",
            "user_id",
            name="uq_baseline_run_permit_nonce_owner",
        ),
        job_fk("fk_baseline_run_permit_job_owner"),
        CheckConstraint(
            "state IN ('RESERVED','ISSUED','STARTED','REVOKED') AND length(manifest_sha256)=64",
            name="ck_baseline_run_permit_state",
        ),
        CheckConstraint(
            "state IN ('RESERVED','REVOKED') OR issued_at IS NOT NULL",
            name="ck_baseline_run_permit_issue",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    nonce: Mapped[uuid.UUID] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(16), default="RESERVED", server_default="RESERVED")
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BaselineRunAttempt(Base):
    __tablename__ = "baseline_run_attempts"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "job_id",
            "plan_id",
            "version_id",
            "project_id",
            "user_id",
            name="uq_baseline_run_attempt_owner",
        ),
        UniqueConstraint("job_id", name="uq_baseline_run_attempt_once"),
        ForeignKeyConstraint(
            [
                "permit_id",
                "permit_nonce",
                "job_id",
                "plan_id",
                "version_id",
                "project_id",
                "user_id",
            ],
            [
                "baseline_run_permits.id",
                "baseline_run_permits.nonce",
                "baseline_run_permits.job_id",
                "baseline_run_permits.plan_id",
                "baseline_run_permits.version_id",
                "baseline_run_permits.project_id",
                "baseline_run_permits.user_id",
            ],
            name="fk_baseline_run_attempt_permit_owner",
        ),
        CheckConstraint(
            "status IN ('STARTED','COMPLETED_CANDIDATE','FAILED','CANCELLED','NEEDS_ATTENTION')",
            name="ck_baseline_run_attempt_candidate",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    permit_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    permit_nonce: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(32))
    image_id: Mapped[str] = mapped_column(String(80))
    daemon_id: Mapped[str] = mapped_column(String(200))
    container_id: Mapped[str | None] = mapped_column(String(80))
    container_name: Mapped[str | None] = mapped_column(String(160))
    command_sha256: Mapped[str | None] = mapped_column(String(64))
    input_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    container_stopped: Mapped[bool | None] = mapped_column(Boolean)
    input_sealed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    input_seal_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    logs: Mapped[str | None] = mapped_column(Text)
    receipt_status: Mapped[str | None] = mapped_column(String(32))
    issues_text: Mapped[str] = mapped_column(Text)
    began_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BaselineRunArtifact(Base):
    __tablename__ = "baseline_run_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "job_id", "plan_id", "version_id", "project_id", "user_id"],
            [
                "baseline_run_attempts.id",
                "baseline_run_attempts.job_id",
                "baseline_run_attempts.plan_id",
                "baseline_run_attempts.version_id",
                "baseline_run_attempts.project_id",
                "baseline_run_attempts.user_id",
            ],
            name="fk_baseline_run_artifact_attempt_owner",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_baseline_run_artifact_attachment_owner",
        ),
        Index("ix_baseline_run_artifact_attempt_path", "attempt_id", "path"),
        CheckConstraint(
            "disposition IN ('AVAILABLE','QUARANTINED','UNAVAILABLE') AND length(sha256)=64 AND size_bytes>=0",
            name="ck_baseline_run_artifact_fact",
        ),
        CheckConstraint(
            "disposition='UNAVAILABLE' OR attachment_id IS NOT NULL",
            name="ck_baseline_run_artifact_retained",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    path: Mapped[str] = mapped_column(String(2000))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    disposition: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
