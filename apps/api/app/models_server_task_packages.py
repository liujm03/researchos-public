"""Frozen owner-reviewed server handoffs and independently recorded save facts."""

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


class ServerTaskPackage(Base):
    __tablename__ = "server_task_packages"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_server_package_owner"),
        UniqueConstraint("user_id", "project_id", "idempotency_key", name="uq_server_package_key"),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_server_package_project",
        ),
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_server_package_brief",
        ),
        ForeignKeyConstraint(
            ["archive_binding_id", "project_id", "user_id"],
            [
                "project_archive_bindings.id",
                "project_archive_bindings.project_id",
                "project_archive_bindings.user_id",
            ],
            name="fk_server_package_binding",
        ),
        ForeignKeyConstraint(
            ["archive_version_id", "archive_binding_id", "user_id"],
            [
                "project_archive_versions.id",
                "project_archive_versions.binding_id",
                "project_archive_versions.user_id",
            ],
            name="fk_server_package_version",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_server_package_attachment",
        ),
        CheckConstraint(
            "status IN ('SAVING','READY','FAILED','NEEDS_ATTENTION')",
            name="ck_server_package_status",
        ),
        CheckConstraint(
            "readiness IN ('INCOMPLETE','READY_FOR_SERVER_REVIEW') AND NOT execution_authorized AND delivery_status='LOCAL_ONLY'",
            name="ck_server_package_authority",
        ),
        CheckConstraint(
            "length(source_sha256)=64 AND length(preview_sha256)=64 AND length(bundle_sha256)=64 AND bundle_size_bytes BETWEEN 1 AND 2097152",
            name="ck_server_package_hashes",
        ),
        CheckConstraint(
            "length(label) BETWEEN 1 AND 240 AND length(idempotency_key) BETWEEN 1 AND 120",
            name="ck_server_package_bounds",
        ),
        CheckConstraint(
            "(archive_version_id IS NULL AND archive_binding_id IS NULL) OR (archive_version_id IS NOT NULL AND archive_binding_id IS NOT NULL)",
            name="ck_server_package_archive_pair",
        ),
        CheckConstraint(
            "status<>'READY' OR (attachment_id IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_server_package_ready",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    archive_binding_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    archive_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    label: Mapped[str] = mapped_column(String(240))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24))
    readiness: Mapped[str] = mapped_column(String(32))
    source_sha256: Mapped[str] = mapped_column(String(64))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    bundle_size_bytes: Mapped[int] = mapped_column(BigInteger)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    selection_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    gaps: Mapped[list[str]] = mapped_column(JSON)
    execution_authorized: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    delivery_status: Mapped[str] = mapped_column(String(24), default="LOCAL_ONLY")
    active_attempt_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PackageChild:
    package_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)


def child_constraints(name: str) -> tuple[ForeignKeyConstraint, CheckConstraint]:
    return (
        ForeignKeyConstraint(
            ["package_id", "project_id", "user_id"],
            [
                "server_task_packages.id",
                "server_task_packages.project_id",
                "server_task_packages.user_id",
            ],
            name="fk_server_" + name + "_owner",
        ),
        CheckConstraint("position>=0", name="ck_server_" + name + "_position"),
    )


class ServerTaskPackageFile(PackageChild, Base):
    __tablename__ = "server_task_package_files"
    __table_args__ = (
        *child_constraints("file"),
        UniqueConstraint("package_id", "path", name="uq_server_package_file_path"),
        CheckConstraint(
            "length(sha256)=64 AND size_bytes BETWEEN 0 AND 2097152",
            name="ck_server_package_file_bounds",
        ),
    )
    path: Mapped[str] = mapped_column(String(1024))
    content: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)


class ServerTaskPackageAsset(PackageChild, Base):
    __tablename__ = "server_task_package_assets"
    __table_args__ = (
        *child_constraints("asset"),
        CheckConstraint(
            "kind IN ('DATASET','MODEL','OTHER') AND (sha256 IS NULL OR length(sha256)=64)",
            name="ck_server_package_asset",
        ),
    )
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(240))
    location: Mapped[str] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(String(240))
    sha256: Mapped[str | None] = mapped_column(String(64))
    license_note: Mapped[str | None] = mapped_column(Text)


class ServerTaskPackageExpectedArtifact(PackageChild, Base):
    __tablename__ = "server_task_package_expected_artifacts"
    __table_args__ = (*child_constraints("expected"),)
    path: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)


class ServerTaskPackageTask(PackageChild, Base):
    __tablename__ = "server_task_package_tasks"
    __table_args__ = (
        *child_constraints("task"),
        ForeignKeyConstraint(
            ["task_id", "project_id", "user_id"],
            ["tasks.id", "tasks.project_id", "tasks.user_id"],
            name="fk_server_package_task_owner",
        ),
        UniqueConstraint("task_id", name="uq_server_package_task_identity"),
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(320))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(24))
    priority: Mapped[str] = mapped_column(String(16))


class ServerTaskPackageSaveAttempt(Base):
    __tablename__ = "server_task_package_save_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "project_id", "user_id"],
            [
                "server_task_packages.id",
                "server_task_packages.project_id",
                "server_task_packages.user_id",
            ],
            name="fk_server_package_attempt_owner",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_server_package_attempt_attachment",
        ),
        UniqueConstraint("package_id", "attempt_number", name="uq_server_package_attempt_number"),
        UniqueConstraint("token", name="uq_server_package_attempt_token"),
        CheckConstraint(
            "attempt_number>0 AND status IN ('SAVING','SAVED','FAILED','UNKNOWN','QUARANTINED','LATE')",
            name="ck_server_package_attempt_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    attempt_number: Mapped[int] = mapped_column(Integer)
    token: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24))
    storage_provider: Mapped[str | None] = mapped_column(String(64))
    object_key: Mapped[str | None] = mapped_column(String(320))
    observed_sha256: Mapped[str | None] = mapped_column(String(64))
    observed_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    observed_mime_type: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(64))
    owner_acknowledged_unknown: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
