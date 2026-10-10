"""Relational inventory of locally bound private project archive versions."""

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
    UniqueConstraint,
    Uuid,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectArchiveBinding(Base):
    __tablename__ = "project_archive_bindings"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_project_archive_binding_owner"),
        UniqueConstraint(
            "id", "project_id", "user_id", name="uq_project_archive_binding_project_owner"
        ),
        UniqueConstraint("user_id", "project_id", name="uq_project_archive_binding_project"),
        UniqueConstraint("user_id", "workspace_key", name="uq_project_archive_binding_workspace"),
        UniqueConstraint("user_id", "github_repository_id", name="uq_project_archive_binding_repo"),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_project_archive_binding_project_owner",
        ),
        CheckConstraint("length(workspace_key) BETWEEN 1 AND 80", name="ck_archive_workspace_key"),
        CheckConstraint("length(local_project_id) BETWEEN 1 AND 160", name="ck_archive_local_id"),
        CheckConstraint("length(github_owner) BETWEEN 1 AND 39", name="ck_archive_github_owner"),
        CheckConstraint(
            "length(github_repository) BETWEEN 1 AND 100", name="ck_archive_github_repo"
        ),
        CheckConstraint(
            "github_owner_id > 0 AND github_repository_id > 0", name="ck_archive_github_ids"
        ),
        CheckConstraint("interval_minutes BETWEEN 10 AND 10080", name="ck_archive_interval"),
        CheckConstraint(
            "workspace_fingerprint IS NULL OR length(workspace_fingerprint) = 64",
            name="ck_archive_workspace_fingerprint",
        ),
        CheckConstraint(
            "NOT auto_enabled OR workspace_fingerprint IS NOT NULL", name="ck_archive_auto_scope"
        ),
        CheckConstraint(
            "(managed_folder_name IS NULL AND managed_root_fingerprint IS NULL) OR "
            "(managed_folder_name IS NOT NULL AND managed_root_fingerprint IS NOT NULL AND length(managed_folder_name) BETWEEN 1 AND 160 AND length(managed_root_fingerprint) = 64)",
            name="ck_archive_managed_scope_pair",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    workspace_key: Mapped[str] = mapped_column(String(80))
    local_project_id: Mapped[str] = mapped_column(String(160))
    github_owner: Mapped[str] = mapped_column(String(39))
    github_owner_id: Mapped[int] = mapped_column(BigInteger)
    github_repository: Mapped[str] = mapped_column(String(100))
    github_repository_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    auto_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    next_archive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workspace_fingerprint: Mapped[str | None] = mapped_column(String(64))
    managed_folder_name: Mapped[str | None] = mapped_column(String(160))
    managed_root_fingerprint: Mapped[str | None] = mapped_column(String(64))


class ProjectArchiveVersion(Base):
    __tablename__ = "project_archive_versions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_project_archive_version_owner"),
        UniqueConstraint(
            "id", "binding_id", "user_id", name="uq_project_archive_version_binding_owner"
        ),
        UniqueConstraint("binding_id", "tag", name="uq_project_archive_version_tag"),
        ForeignKeyConstraint(
            ["binding_id", "user_id"],
            ["project_archive_bindings.id", "project_archive_bindings.user_id"],
            name="fk_project_archive_version_binding_owner",
        ),
        CheckConstraint("length(tag) BETWEEN 1 AND 120", name="ck_archive_version_tag"),
        CheckConstraint("length(commit_sha) = 40", name="ck_archive_version_commit"),
        CheckConstraint("length(manifest_sha256) = 64", name="ck_archive_version_manifest"),
        CheckConstraint(
            "parent_commit IS NULL OR length(parent_commit) = 40", name="ck_archive_version_parent"
        ),
        CheckConstraint("file_count >= 0 AND total_bytes >= 0", name="ck_archive_version_totals"),
        CheckConstraint(
            "(remote_tag_commit IS NULL AND remote_verified_at IS NULL) OR "
            "(remote_tag_commit IS NOT NULL AND remote_verified_at IS NOT NULL AND remote_tag_commit = commit_sha)",
            name="ck_archive_version_remote_pair",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    binding_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    tag: Mapped[str] = mapped_column(String(120))
    commit_sha: Mapped[str] = mapped_column(String(40))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    parent_commit: Mapped[str | None] = mapped_column(String(40))
    file_count: Mapped[int] = mapped_column(Integer)
    total_bytes: Mapped[int] = mapped_column(BigInteger)
    remote_tag_commit: Mapped[str | None] = mapped_column(String(40))
    remote_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectArchiveFile(Base):
    __tablename__ = "project_archive_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "user_id"],
            ["project_archive_versions.id", "project_archive_versions.user_id"],
            name="fk_project_archive_file_version_owner",
        ),
        CheckConstraint("length(path) BETWEEN 1 AND 1024", name="ck_archive_file_path"),
        CheckConstraint("length(sha256) = 64", name="ck_archive_file_hash"),
        CheckConstraint("size_bytes >= 0", name="ck_archive_file_size"),
    )
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
