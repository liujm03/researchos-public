"""Owner-scoped server evidence, append-only reviews and explicit feedback links."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
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


class ServerResult(Base):
    __tablename__ = "server_results"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_server_result_owner"),
        UniqueConstraint("user_id", "project_id", "idempotency_key", name="uq_server_result_key"),
        UniqueConstraint(
            "user_id",
            "package_id",
            "server_identity",
            "receipt_id",
            name="uq_server_result_receipt",
        ),
        ForeignKeyConstraint(
            ["package_id", "project_id", "user_id"],
            [
                "server_task_packages.id",
                "server_task_packages.project_id",
                "server_task_packages.user_id",
            ],
            name="fk_server_result_package",
        ),
        ForeignKeyConstraint(
            ["input_attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_server_result_input",
        ),
        CheckConstraint(
            "status IN ('IMPORTING','READY','NEEDS_ATTENTION','FAILED')",
            name="ck_server_result_status",
        ),
        CheckConstraint(
            "validation_status IN ('MATCHED','GAPS','MISMATCH')", name="ck_server_result_validation"
        ),
        CheckConstraint(
            "origin_verification IN ('OWNER_UPLOADED_UNVERIFIED','CONFIGURED_KEY_SIGNATURE','INVALID_SIGNATURE')",
            name="ck_server_result_origin",
        ),
        CheckConstraint(
            "review_status IN ('UNREVIEWED','ACCEPTED','REJECTED')", name="ck_server_result_review"
        ),
        CheckConstraint(
            "length(result_sha256)=64 AND length(receipt_sha256)=64 AND length(input_sha256)=64",
            name="ck_server_result_hash",
        ),
        CheckConstraint(
            "status<>'READY' OR input_attachment_id IS NOT NULL", name="ck_server_result_ready"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    package_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[str] = mapped_column(String(120))
    server_identity: Mapped[str] = mapped_column(String(80))
    server_id: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24))
    validation_status: Mapped[str] = mapped_column(String(24))
    origin_verification: Mapped[str] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(24), default="UNREVIEWED")
    result_sha256: Mapped[str] = mapped_column(String(64))
    receipt_sha256: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    input_attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    import_token: Mapped[uuid.UUID] = mapped_column(Uuid)
    raw_envelope: Mapped[dict[str, Any]] = mapped_column(JSON)
    match_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    storage_observations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON)
    claimed_run_status: Mapped[str] = mapped_column(String(24))
    claimed_job_id: Mapped[str | None] = mapped_column(String(160))
    git_commit: Mapped[str | None] = mapped_column(String(40))
    protocol_sha256: Mapped[str | None] = mapped_column(String(64))
    config_sha256: Mapped[str | None] = mapped_column(String(64))
    dataset_sha256: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResultChild:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    result_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)


def child_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["result_id", "project_id", "user_id"],
        ["server_results.id", "server_results.project_id", "server_results.user_id"],
        name="fk_server_result_" + name,
    )


class ServerResultMetric(ResultChild, Base):
    __tablename__ = "server_result_metrics"
    __table_args__ = (
        child_fk("metric"),
        UniqueConstraint("id", "result_id", "project_id", "user_id", name="uq_server_metric_owner"),
        UniqueConstraint("result_id", "position", name="uq_server_result_metric_position"),
        CheckConstraint("position>=0", name="ck_server_result_metric_position"),
    )
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(80))
    split: Mapped[str | None] = mapped_column(String(80))
    evaluation_protocol: Mapped[str | None] = mapped_column(Text)


class ServerResultArtifact(ResultChild, Base):
    __tablename__ = "server_result_artifacts"
    __table_args__ = (
        child_fk("artifact"),
        UniqueConstraint("id", "result_id", "project_id", "user_id", name="uq_server_artifact_owner"),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_server_result_artifact_attachment",
        ),
        UniqueConstraint("result_id", "path", name="uq_server_result_artifact_path"),
        CheckConstraint(
            "verification IN ('BYTES_VERIFIED','DECLARED_NOT_INCLUDED','MISMATCH','MISSING')",
            name="ck_server_result_artifact_verification",
        ),
        CheckConstraint(
            "verification<>'BYTES_VERIFIED' OR attachment_id IS NOT NULL",
            name="ck_server_result_artifact_verified",
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(120))
    included: Mapped[bool] = mapped_column(Boolean)
    verification: Mapped[str] = mapped_column(String(24))
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actual_sha256: Mapped[str | None] = mapped_column(String(64))
    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger)


class ServerResultReview(ResultChild, Base):
    __tablename__ = "server_result_reviews"
    __table_args__ = (
        child_fk("review"),
        UniqueConstraint(
            "id", "result_id", "project_id", "user_id", name="uq_server_result_review_owner"
        ),
        UniqueConstraint("result_id", "idempotency_key", name="uq_server_result_review_key"),
        CheckConstraint(
            "decision IN ('ACCEPT','REJECT','COMMENT')", name="ck_server_result_review_decision"
        ),
    )
    result_sha256: Mapped[str] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    decision: Mapped[str] = mapped_column(String(16))
    conclusion: Mapped[str] = mapped_column(Text)
    acknowledge_gaps: Mapped[bool] = mapped_column(Boolean)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ServerResultTaskAction(ResultChild, Base):
    __tablename__ = "server_result_task_actions"
    __table_args__ = (
        child_fk("task_action"),
        ForeignKeyConstraint(
            ["review_id", "result_id", "project_id", "user_id"],
            [
                "server_result_reviews.id",
                "server_result_reviews.result_id",
                "server_result_reviews.project_id",
                "server_result_reviews.user_id",
            ],
            name="fk_server_result_action_review",
        ),
        ForeignKeyConstraint(
            ["task_id", "project_id", "user_id"],
            ["tasks.id", "tasks.project_id", "tasks.user_id"],
            name="fk_server_result_action_task",
        ),
        UniqueConstraint("review_id", "task_id", name="uq_server_result_action_task"),
    )
    review_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    before_status: Mapped[str] = mapped_column(String(24))
    after_status: Mapped[str] = mapped_column(String(24))
    before_version: Mapped[int] = mapped_column(Integer)
    after_version: Mapped[int] = mapped_column(Integer)


class ServerResultBriefLink(ResultChild, Base):
    __tablename__ = "server_result_brief_links"
    __table_args__ = (
        child_fk("brief_link"),
        ForeignKeyConstraint(
            ["review_id", "result_id", "project_id", "user_id"],
            [
                "server_result_reviews.id",
                "server_result_reviews.result_id",
                "server_result_reviews.project_id",
                "server_result_reviews.user_id",
            ],
            name="fk_server_result_link_review",
        ),
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_server_result_link_brief",
        ),
        UniqueConstraint("result_id", "idempotency_key", name="uq_server_result_link_key"),
    )
    review_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    result_sha256: Mapped[str] = mapped_column(String(64))
    request_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
