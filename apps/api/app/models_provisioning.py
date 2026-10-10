"""Explicitly approved project scaffolding and private repository provisioning."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectProvisionPlan(Base):
    __tablename__ = "project_provision_plans"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_provision_plan_project_owner"),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_provision_plan_project_owner",
        ),
        CheckConstraint("length(managed_root_fingerprint) = 64", name="ck_provision_plan_root"),
        CheckConstraint("length(folder_name) BETWEEN 1 AND 160", name="ck_provision_plan_folder"),
        CheckConstraint("length(repository_name) BETWEEN 1 AND 100", name="ck_provision_plan_repo"),
        CheckConstraint("length(github_owner) BETWEEN 1 AND 39", name="ck_provision_plan_owner"),
        CheckConstraint("github_owner_id > 0", name="ck_provision_plan_owner_id"),
        CheckConstraint("length(template_key) BETWEEN 1 AND 40", name="ck_provision_plan_template"),
        CheckConstraint(
            "length(template_sha256) = 64 AND length(plan_sha256) = 64",
            name="ck_provision_plan_hashes",
        ),
        CheckConstraint(
            "length(CAST(files_payload AS TEXT)) <= 2097152", name="ck_provision_plan_payload_size"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    managed_root_fingerprint: Mapped[str] = mapped_column(String(64))
    folder_name: Mapped[str] = mapped_column(String(160))
    repository_name: Mapped[str] = mapped_column(String(100))
    github_owner: Mapped[str] = mapped_column(String(39))
    github_owner_id: Mapped[int] = mapped_column(BigInteger)
    template_key: Mapped[str] = mapped_column(String(40))
    template_sha256: Mapped[str] = mapped_column(String(64))
    plan_sha256: Mapped[str] = mapped_column(String(64))
    files_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectProvisionJob(Base):
    __tablename__ = "project_provision_jobs"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_provision_job_owner"),
        UniqueConstraint("plan_id", name="uq_provision_job_plan"),
        UniqueConstraint("active_project_id", name="uq_provision_job_active_project"),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_provision_job_project_owner",
        ),
        ForeignKeyConstraint(
            ["plan_id", "project_id", "user_id"],
            [
                "project_provision_plans.id",
                "project_provision_plans.project_id",
                "project_provision_plans.user_id",
            ],
            name="fk_provision_job_plan_project_owner",
        ),
        ForeignKeyConstraint(
            ["active_project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_provision_job_active_project_owner",
        ),
        ForeignKeyConstraint(
            ["binding_id", "project_id", "user_id"],
            [
                "project_archive_bindings.id",
                "project_archive_bindings.project_id",
                "project_archive_bindings.user_id",
            ],
            name="fk_provision_job_binding_project_owner",
        ),
        CheckConstraint(
            "status IN ('QUEUED','PREPARING','LOCAL_READY','CREATING_REMOTE','REMOTE_CREATED','BINDING','COMPLETED','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_provision_job_status",
        ),
        CheckConstraint(
            "(status IN ('QUEUED','PREPARING','LOCAL_READY','CREATING_REMOTE','REMOTE_CREATED','BINDING','NEEDS_ATTENTION') AND active_project_id IS NOT NULL AND active_project_id = project_id) OR (status IN ('COMPLETED','FAILED','CANCELLED') AND active_project_id IS NULL)",
            name="ck_provision_job_active_project",
        ),
        CheckConstraint(
            "repository_id IS NULL OR repository_id > 0", name="ck_provision_job_repo_id"
        ),
        CheckConstraint(
            "observed_repository_id IS NULL OR observed_repository_id > 0",
            name="ck_provision_job_observed_id",
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_provision_job_lease_pair",
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR (repository_id IS NOT NULL AND binding_id IS NOT NULL)",
            name="ck_provision_job_completed_binding",
        ),
        Index("ix_project_provision_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    active_project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", server_default="QUEUED")
    repository_id: Mapped[int | None] = mapped_column(BigInteger)
    observed_repository_id: Mapped[int | None] = mapped_column(BigInteger)
    binding_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)


class ProjectProvisionEvent(Base):
    __tablename__ = "project_provision_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["project_provision_jobs.id", "project_provision_jobs.user_id"],
            name="fk_provision_event_job_owner",
        ),
        CheckConstraint("length(event_kind) BETWEEN 1 AND 40", name="ck_provision_event_kind"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    event_kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
