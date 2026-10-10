"""Durable, owner-scoped private archive scheduling and execution records."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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


class ProjectArchiveJob(Base):
    __tablename__ = "project_archive_jobs"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_project_archive_job_owner"),
        UniqueConstraint("binding_id", "tag", name="uq_project_archive_job_tag"),
        UniqueConstraint("active_binding_id", name="uq_project_archive_job_active_binding"),
        ForeignKeyConstraint(
            ["binding_id", "user_id"],
            ["project_archive_bindings.id", "project_archive_bindings.user_id"],
            name="fk_project_archive_job_binding_owner",
        ),
        ForeignKeyConstraint(
            ["active_binding_id", "user_id"],
            ["project_archive_bindings.id", "project_archive_bindings.user_id"],
            name="fk_project_archive_job_active_owner",
        ),
        ForeignKeyConstraint(
            ["version_id", "binding_id", "user_id"],
            [
                "project_archive_versions.id",
                "project_archive_versions.binding_id",
                "project_archive_versions.user_id",
            ],
            name="fk_project_archive_job_version_binding_owner",
        ),
        CheckConstraint("length(tag) BETWEEN 1 AND 120", name="ck_archive_job_tag"),
        CheckConstraint("trigger_kind IN ('MANUAL','SCHEDULED')", name="ck_archive_job_trigger"),
        CheckConstraint(
            "status IN ('QUEUED','PREPARING','COMMITTING','PUBLISHING','COMPLETED','UNCHANGED','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_archive_job_status",
        ),
        CheckConstraint(
            "(status IN ('QUEUED','PREPARING','COMMITTING','PUBLISHING','NEEDS_ATTENTION') AND active_binding_id IS NOT NULL AND active_binding_id = binding_id) OR "
            "(status IN ('COMPLETED','UNCHANGED','FAILED','CANCELLED') AND active_binding_id IS NULL)",
            name="ck_archive_job_active_binding",
        ),
        CheckConstraint("length(workspace_fingerprint) = 64", name="ck_archive_job_workspace"),
        CheckConstraint(
            "manifest_sha256 IS NULL OR length(manifest_sha256) = 64",
            name="ck_archive_job_manifest",
        ),
        CheckConstraint(
            "manifest_payload IS NULL OR length(CAST(manifest_payload AS TEXT)) <= 2097152",
            name="ck_archive_job_manifest_size",
        ),
        CheckConstraint(
            "commit_sha IS NULL OR length(commit_sha) = 40", name="ck_archive_job_commit"
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_archive_job_lease_pair",
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR (version_id IS NOT NULL AND commit_sha IS NOT NULL AND manifest_sha256 IS NOT NULL)",
            name="ck_archive_job_completed_version",
        ),
        Index("ix_project_archive_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    binding_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    tag: Mapped[str] = mapped_column(String(120))
    trigger_kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", server_default="QUEUED")
    active_binding_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    workspace_fingerprint: Mapped[str] = mapped_column(String(64))
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    manifest_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
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


class ProjectArchiveJobEvent(Base):
    __tablename__ = "project_archive_job_events"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_project_archive_job_event_owner"),
        ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["project_archive_jobs.id", "project_archive_jobs.user_id"],
            name="fk_project_archive_job_event_owner",
        ),
        CheckConstraint("length(event_kind) BETWEEN 1 AND 40", name="ck_archive_job_event_kind"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    event_kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
