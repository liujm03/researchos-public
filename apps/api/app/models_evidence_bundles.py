"""Frozen internal writing evidence and actual Storage save attempts."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EvidenceBundle(Base):
    __tablename__ = "evidence_bundles"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_evidence_bundle_scope"),
        UniqueConstraint("project_id", "user_id", "idempotency_key", name="uq_evidence_bundle_key"),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_evidence_bundle_project",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_evidence_bundle_attachment",
        ),
        CheckConstraint(
            "status IN ('SAVING','READY','FAILED','NEEDS_ATTENTION')",
            name="ck_evidence_bundle_status",
        ),
        CheckConstraint(
            "length(snapshot_sha256)=64 AND length(preview_sha256)=64 AND length(bundle_sha256)=64",
            name="ck_evidence_bundle_hash",
        ),
        CheckConstraint(
            "status<>'READY' OR attachment_id IS NOT NULL", name="ck_evidence_bundle_ready"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    label: Mapped[str] = mapped_column(String(240))
    selection: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    bundle_size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    current_attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvidenceBundleClaim(Base):
    __tablename__ = "evidence_bundle_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bundle_id", "project_id", "user_id"],
            ["evidence_bundles.id", "evidence_bundles.project_id", "evidence_bundles.user_id"],
            name="fk_bundle_claim_bundle",
        ),
        ForeignKeyConstraint(
            ["revision_id", "claim_id", "project_id", "user_id"],
            [
                "claim_revisions.id",
                "claim_revisions.claim_id",
                "claim_revisions.project_id",
                "claim_revisions.user_id",
            ],
            name="fk_bundle_claim_revision",
        ),
        UniqueConstraint("bundle_id", "position", name="uq_bundle_claim_position"),
    )
    bundle_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    revision_sha256: Mapped[str] = mapped_column(String(64))
    evidence_sha256: Mapped[str] = mapped_column(String(64))


class EvidenceBundleFile(Base):
    __tablename__ = "evidence_bundle_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bundle_id", "project_id", "user_id"],
            ["evidence_bundles.id", "evidence_bundles.project_id", "evidence_bundles.user_id"],
            name="fk_bundle_file_bundle",
        ),
        CheckConstraint(
            "size_bytes BETWEEN 0 AND 4194304 AND length(sha256)=64", name="ck_bundle_file_bound"
        ),
    )
    bundle_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    path: Mapped[str] = mapped_column(String(240), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    content: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)


class EvidenceBundleSaveAttempt(Base):
    __tablename__ = "evidence_bundle_save_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bundle_id", "project_id", "user_id"],
            ["evidence_bundles.id", "evidence_bundles.project_id", "evidence_bundles.user_id"],
            name="fk_bundle_attempt_bundle",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_bundle_attempt_attachment",
        ),
        UniqueConstraint("bundle_id", "idempotency_key", name="uq_bundle_save_key"),
        CheckConstraint(
            "status IN ('SAVING','READY','FAILED','NEEDS_ATTENTION','LATE')",
            name="ck_bundle_attempt_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    bundle_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(24))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    observations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
