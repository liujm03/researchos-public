"""Owner/project baseline declarations and append-only measured material evidence."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def version_owner_fk(prefix: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["version_id", "project_id", "user_id"],
        ["baseline_versions.id", "baseline_versions.project_id", "baseline_versions.user_id"],
        name=prefix,
    )


class Baseline(Base):
    __tablename__ = "baselines"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_baseline_owner"),
        UniqueConstraint("project_id", "name", name="uq_baseline_project_name"),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_baseline_project_owner",
        ),
        CheckConstraint("length(name) BETWEEN 1 AND 240", name="ck_baseline_name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(240))
    purpose: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BaselineVersion(Base):
    __tablename__ = "baseline_versions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_baseline_version_owner"),
        UniqueConstraint(
            "id", "baseline_id", "project_id", "user_id", name="uq_baseline_version_parent_owner"
        ),
        UniqueConstraint(
            "id", "sha256", "project_id", "user_id", name="uq_baseline_version_hash_owner"
        ),
        UniqueConstraint("baseline_id", "version", name="uq_baseline_version_label"),
        ForeignKeyConstraint(
            ["baseline_id", "project_id", "user_id"],
            ["baselines.id", "baselines.project_id", "baselines.user_id"],
            name="fk_baseline_version_owner",
        ),
        ForeignKeyConstraint(
            ["parent_version_id", "baseline_id", "project_id", "user_id"],
            [
                "baseline_versions.id",
                "baseline_versions.baseline_id",
                "baseline_versions.project_id",
                "baseline_versions.user_id",
            ],
            name="fk_baseline_version_parent_owner",
        ),
        ForeignKeyConstraint(
            ["parent_version_id", "parent_sha256", "project_id", "user_id"],
            [
                "baseline_versions.id",
                "baseline_versions.sha256",
                "baseline_versions.project_id",
                "baseline_versions.user_id",
            ],
            name="fk_baseline_version_parent_hash_owner",
        ),
        ForeignKeyConstraint(
            ["model_version_id", "model_id", "user_id"],
            ["model_versions.id", "model_versions.model_id", "model_versions.user_id"],
            name="fk_baseline_model_owner",
        ),
        ForeignKeyConstraint(
            ["paper_id", "user_id"], ["papers.id", "papers.user_id"], name="fk_baseline_paper_owner"
        ),
        CheckConstraint(
            "weight_mode IN ('PRETRAINED','FROM_SCRATCH') AND length(version) BETWEEN 1 AND 120 AND length(sha256)=64",
            name="ck_baseline_version_scope",
        ),
        CheckConstraint(
            "(parent_version_id IS NULL AND parent_sha256 IS NULL) OR (parent_version_id IS NOT NULL AND parent_sha256 IS NOT NULL AND length(parent_sha256)=64)",
            name="ck_baseline_parent_pair",
        ),
        CheckConstraint(
            "(model_version_id IS NULL AND model_id IS NULL AND model_snapshot_sha256 IS NULL) OR (model_version_id IS NOT NULL AND model_id IS NOT NULL AND model_snapshot_sha256 IS NOT NULL)",
            name="ck_baseline_model_pair",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    baseline_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version: Mapped[str] = mapped_column(String(120))
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    parent_sha256: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    model_snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    weight_mode: Mapped[str] = mapped_column(String(24))
    purpose: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BaselineDatasetBinding(Base):
    __tablename__ = "baseline_dataset_bindings"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "dataset_version_id",
            "project_id",
            "user_id",
            name="uq_baseline_dataset_owner",
        ),
        version_owner_fk("fk_baseline_dataset_version_owner"),
        ForeignKeyConstraint(
            ["dataset_version_id", "dataset_id", "user_id"],
            ["dataset_versions.id", "dataset_versions.dataset_id", "dataset_versions.user_id"],
            name="fk_baseline_dataset_owner",
        ),
        CheckConstraint(
            "length(snapshot_sha256)=64 AND length(license_confirmation)>0 AND length(usage_scope)>0",
            name="ck_baseline_dataset_declaration",
        ),
    )
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    dataset_name: Mapped[str] = mapped_column(String(240))
    dataset_version: Mapped[str] = mapped_column(String(120))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    license_confirmation: Mapped[str] = mapped_column(Text)
    usage_scope: Mapped[str] = mapped_column(Text)


class BaselineAsset(Base):
    __tablename__ = "baseline_assets"
    __table_args__ = (
        UniqueConstraint(
            "id", "version_id", "project_id", "user_id", name="uq_baseline_asset_owner"
        ),
        version_owner_fk("fk_baseline_asset_version_owner"),
        ForeignKeyConstraint(
            ["source_job_id", "source_plan_id", "project_id", "user_id"],
            [
                "project_source_jobs.id",
                "project_source_jobs.plan_id",
                "project_source_jobs.project_id",
                "project_source_jobs.user_id",
            ],
            name="fk_baseline_asset_source_job_owner",
        ),
        ForeignKeyConstraint(
            [
                "source_file_id",
                "source_job_id",
                "source_plan_id",
                "file_key_sha256",
                "project_id",
                "user_id",
            ],
            [
                "project_source_files.id",
                "project_source_files.job_id",
                "project_source_files.plan_id",
                "project_source_files.file_key_sha256",
                "project_source_files.project_id",
                "project_source_files.user_id",
            ],
            name="fk_baseline_asset_source_checkpoint_owner",
        ),
        ForeignKeyConstraint(
            ["source_plan_id", "file_key_sha256", "project_id", "user_id"],
            [
                "project_source_plan_files.plan_id",
                "project_source_plan_files.file_key_sha256",
                "project_source_plan_files.project_id",
                "project_source_plan_files.user_id",
            ],
            name="fk_baseline_asset_source_file_owner",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_baseline_asset_attachment_owner",
        ),
        ForeignKeyConstraint(
            ["version_id", "dataset_version_id", "project_id", "user_id"],
            [
                "baseline_dataset_bindings.version_id",
                "baseline_dataset_bindings.dataset_version_id",
                "baseline_dataset_bindings.project_id",
                "baseline_dataset_bindings.user_id",
            ],
            name="fk_baseline_asset_dataset_owner",
        ),
        CheckConstraint(
            "role IN ('CODE','CONFIG','ENVIRONMENT_LOCK','EVALUATOR','WEIGHTS','DATA','SPLIT_MANIFEST')",
            name="ck_baseline_asset_role",
        ),
        CheckConstraint(
            "(role IN ('DATA','SPLIT_MANIFEST') AND dataset_version_id IS NOT NULL) OR (role NOT IN ('DATA','SPLIT_MANIFEST') AND dataset_version_id IS NULL)",
            name="ck_baseline_asset_dataset_role",
        ),
        CheckConstraint(
            "size_bytes>=0 AND length(sha256)=64 AND length(file_key_sha256)=64 AND length(source_plan_sha256)=64 AND length(source_receipt_sha256)=64 AND length(commit_sha)=40",
            name="ck_baseline_asset_proof",
        ),
        CheckConstraint(
            "source_status IN ('MATERIALIZED','PARTIAL')", name="ck_baseline_asset_source_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    role: Mapped[str] = mapped_column(String(24))
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_file_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    file_key_sha256: Mapped[str] = mapped_column(String(64))
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    commit_sha: Mapped[str] = mapped_column(String(40))
    source_plan_sha256: Mapped[str] = mapped_column(String(64))
    source_receipt_sha256: Mapped[str] = mapped_column(String(64))
    source_status: Mapped[str] = mapped_column(String(24))
    source_gaps_text: Mapped[str] = mapped_column(Text)


class BaselineMaterialCheck(Base):
    __tablename__ = "baseline_material_checks"
    __table_args__ = (
        UniqueConstraint(
            "id", "version_id", "project_id", "user_id", name="uq_baseline_check_owner"
        ),
        version_owner_fk("fk_baseline_check_version_owner"),
        CheckConstraint(
            "outcome IN ('MATERIALIZED','INCOMPLETE','FAILED') AND length(checker_sha256)=64 AND length(version_sha256)=64",
            name="ck_baseline_check_outcome",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version_sha256: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24))
    checker_version: Mapped[str] = mapped_column(String(80))
    checker_sha256: Mapped[str] = mapped_column(String(64))
    gaps_text: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BaselineAssetObservation(Base):
    __tablename__ = "baseline_asset_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["check_id", "version_id", "project_id", "user_id"],
            [
                "baseline_material_checks.id",
                "baseline_material_checks.version_id",
                "baseline_material_checks.project_id",
                "baseline_material_checks.user_id",
            ],
            name="fk_baseline_observation_check_owner",
        ),
        ForeignKeyConstraint(
            ["asset_id", "version_id", "project_id", "user_id"],
            [
                "baseline_assets.id",
                "baseline_assets.version_id",
                "baseline_assets.project_id",
                "baseline_assets.user_id",
            ],
            name="fk_baseline_observation_asset_owner",
        ),
        CheckConstraint(
            "status IN ('VERIFIED','MISSING','CHANGED','UNSAFE','UNAVAILABLE')",
            name="ck_baseline_observation_status",
        ),
        CheckConstraint(
            "status!='VERIFIED' OR (actual_sha256 IS NOT NULL AND length(actual_sha256)=64 AND actual_size_bytes IS NOT NULL AND actual_size_bytes>=0)",
            name="ck_baseline_observation_verified",
        ),
    )
    check_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24))
    actual_sha256: Mapped[str | None] = mapped_column(String(64))
    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    issue: Mapped[str | None] = mapped_column(String(160))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
