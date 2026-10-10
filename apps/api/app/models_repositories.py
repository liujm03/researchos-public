"""Owner-scoped external metadata candidates and append-only source relations."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
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


class RepositoryBinding(Base):
    __tablename__ = "repository_bindings"
    __table_args__ = (
        UniqueConstraint("id", "entity_id", "user_id", name="uq_repository_binding_target_owner"),
        UniqueConstraint(
            "user_id", "provider_key", "repo_kind", "repo_id", name="uq_repository_binding_identity"
        ),
        UniqueConstraint(
            "user_id",
            "provider_key",
            "repo_kind",
            "provider_id",
            name="uq_repository_binding_provider_identity",
        ),
        ForeignKeyConstraint(
            ["entity_id", "user_id"],
            ["research_entities.id", "research_entities.user_id"],
            name="fk_repository_binding_entity_owner",
        ),
        ForeignKeyConstraint(
            ["code_repository_id", "user_id"],
            ["code_repositories.id", "code_repositories.user_id"],
            name="fk_repository_binding_code_owner",
        ),
        CheckConstraint(
            "length(provider_key) BETWEEN 1 AND 40", name="ck_repository_binding_provider"
        ),
        CheckConstraint(
            "(repo_kind IN ('code','space') AND entity_kind='code_repository') OR (repo_kind='model' AND entity_kind='model') OR (repo_kind='dataset' AND entity_kind='dataset')",
            name="ck_repository_binding_target",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(40))
    repo_kind: Mapped[str] = mapped_column(String(16))
    repo_id: Mapped[str] = mapped_column(String(320))
    provider_id: Mapped[str] = mapped_column(String(320))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    entity_kind: Mapped[str] = mapped_column(String(32))
    code_repository_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepositorySourceSnapshot(Base):
    __tablename__ = "repository_source_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_repository_snapshot_owner"),
        UniqueConstraint("binding_id", "source_hash", name="uq_repository_snapshot_version"),
        ForeignKeyConstraint(
            ["binding_id", "entity_id", "user_id"],
            [
                "repository_bindings.id",
                "repository_bindings.entity_id",
                "repository_bindings.user_id",
            ],
            name="fk_repository_snapshot_binding_target",
        ),
        ForeignKeyConstraint(
            ["model_version_id", "entity_id", "user_id"],
            ["model_versions.id", "model_versions.model_id", "model_versions.user_id"],
            name="fk_repository_snapshot_model_target",
        ),
        ForeignKeyConstraint(
            ["dataset_version_id", "entity_id", "user_id"],
            ["dataset_versions.id", "dataset_versions.dataset_id", "dataset_versions.user_id"],
            name="fk_repository_snapshot_dataset_target",
        ),
        CheckConstraint(
            "(entity_kind='model' AND model_version_id IS NOT NULL AND dataset_version_id IS NULL) OR (entity_kind='dataset' AND dataset_version_id IS NOT NULL AND model_version_id IS NULL) OR (entity_kind='code_repository' AND model_version_id IS NULL AND dataset_version_id IS NULL)",
            name="ck_repository_snapshot_version_target",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    binding_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    entity_kind: Mapped[str] = mapped_column(String(32))
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    requested_revision: Mapped[str | None] = mapped_column(String(160))
    canonical_url: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    candidate_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepositoryImportPreview(Base):
    __tablename__ = "repository_import_previews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["confirmed_snapshot_id", "user_id"],
            ["repository_source_snapshots.id", "repository_source_snapshots.user_id"],
            name="fk_repository_preview_confirmed_owner",
        ),
        CheckConstraint("status IN ('PENDING','CONFIRMED')", name="ck_repository_preview_status"),
        CheckConstraint(
            "(status='PENDING' AND confirmed_snapshot_id IS NULL AND confirmed_at IS NULL) OR (status='CONFIRMED' AND confirmed_snapshot_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_repository_preview_confirmation",
        ),
        CheckConstraint(
            "length(provider_key) BETWEEN 1 AND 40 AND repo_kind IN ('code','model','dataset','space')",
            name="ck_repository_preview_identity",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(40))
    repo_kind: Mapped[str] = mapped_column(String(16))
    repo_id: Mapped[str] = mapped_column(String(320))
    provider_id: Mapped[str] = mapped_column(String(320))
    requested_revision: Mapped[str | None] = mapped_column(String(160))
    canonical_url: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    candidate_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", server_default="PENDING")
    confirmed_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
