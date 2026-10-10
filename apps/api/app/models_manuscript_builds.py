"""Frozen document files/provenance and fenced actual compilation/save attempts."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
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


class ManuscriptBuild(Base):
    __tablename__ = "manuscript_builds"
    __table_args__ = (
        UniqueConstraint(
            "id", "publication_id", "project_id", "user_id", name="uq_manuscript_build_owner"
        ),
        UniqueConstraint("publication_id", "user_id", "create_key", name="uq_manuscript_build_key"),
        ForeignKeyConstraint(
            ["revision_id", "publication_id", "project_id", "user_id"],
            [
                "publication_revisions.id",
                "publication_revisions.publication_id",
                "publication_revisions.project_id",
                "publication_revisions.user_id",
            ],
            name="fk_build_publication_revision",
        ),
        *[
            ForeignKeyConstraint(
                [name, "user_id"],
                ["attachments.id", "attachments.user_id"],
                name="fk_build_" + name,
            )
            for name in (
                "input_source_attachment_id",
                "source_attachment_id",
                "pdf_attachment_id",
                "log_attachment_id",
            )
        ],
        CheckConstraint(
            "status IN ('SAVING','QUEUED','RUNNING','CANCEL_REQUESTED','READY','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_build_status",
        ),
        CheckConstraint(
            "status NOT IN ('QUEUED','RUNNING','READY') OR input_source_attachment_id IS NOT NULL",
            name="ck_build_saved_input",
        ),
        CheckConstraint(
            "status<>'READY' OR (source_attachment_id IS NOT NULL AND source_zip_sha256 IS NOT NULL AND source_zip_size_bytes IS NOT NULL AND pdf_attachment_id IS NOT NULL AND log_attachment_id IS NOT NULL)",
            name="ck_build_ready_outputs",
        ),
        CheckConstraint(
            "length(preview_sha256)=64 AND length(source_sha256)=64 AND length(compile_source_sha256)=64 AND length(compiler_manifest_sha256)=64 AND length(request_sha256)=64",
            name="ck_build_hashes",
        ),
        CheckConstraint("length(input_source_zip_sha256)=64", name="ck_build_input_hash"),
        CheckConstraint(
            "(source_zip_sha256 IS NULL AND source_zip_size_bytes IS NULL) OR (length(source_zip_sha256)=64 AND source_zip_size_bytes BETWEEN 1 AND 41943040)",
            name="ck_build_output_zip",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    publication_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    create_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    compile_source_sha256: Mapped[str] = mapped_column(String(64))
    compiler_manifest_sha256: Mapped[str] = mapped_column(String(64))
    input_source_zip_sha256: Mapped[str] = mapped_column(String(64))
    selection: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    preview_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_zip_sha256: Mapped[str | None] = mapped_column(String(64))
    source_zip_size_bytes: Mapped[int | None] = mapped_column(Integer)
    input_source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    pdf_attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    log_attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def build_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["build_id", "publication_id", "project_id", "user_id"],
        [
            "manuscript_builds.id",
            "manuscript_builds.publication_id",
            "manuscript_builds.project_id",
            "manuscript_builds.user_id",
        ],
        name="fk_build_" + name + "_owner",
    )


class BuildChild:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    build_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    publication_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)


class ManuscriptBuildFile(BuildChild, Base):
    __tablename__ = "manuscript_build_files"
    __table_args__ = (
        build_fk("file"),
        UniqueConstraint("build_id", "path", name="uq_build_file_path"),
        CheckConstraint(
            "size_bytes BETWEEN 0 AND 8388608 AND length(sha256)=64", name="ck_build_file_bound"
        ),
    )
    path: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_text: Mapped[str | None] = mapped_column(Text)
    compile_input: Mapped[bool] = mapped_column(default=False)


class ManuscriptBuildFigure(BuildChild, Base):
    __tablename__ = "manuscript_build_figures"
    __table_args__ = (
        build_fk("figure"),
        UniqueConstraint("build_id", "path", name="uq_build_figure_path"),
        ForeignKeyConstraint(
            ["artifact_id", "result_id", "project_id", "user_id"],
            [
                "server_result_artifacts.id",
                "server_result_artifacts.result_id",
                "server_result_artifacts.project_id",
                "server_result_artifacts.user_id",
            ],
            name="fk_build_figure_artifact",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_build_figure_attachment",
        ),
    )
    result_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    artifact_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    result_sha256: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(240))
    caption: Mapped[str] = mapped_column(Text)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)


class ManuscriptBuildTable(BuildChild, Base):
    __tablename__ = "manuscript_build_tables"
    __table_args__ = (
        build_fk("table"),
        UniqueConstraint(
            "id", "build_id", "publication_id", "project_id", "user_id", name="uq_build_table_owner"
        ),
        UniqueConstraint("build_id", "key", name="uq_build_table_key"),
    )
    key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(240))
    position: Mapped[int] = mapped_column(Integer)


class ManuscriptBuildMetric(BuildChild, Base):
    __tablename__ = "manuscript_build_metrics"
    __table_args__ = (
        build_fk("metric"),
        ForeignKeyConstraint(
            ["table_id", "build_id", "publication_id", "project_id", "user_id"],
            [
                "manuscript_build_tables.id",
                "manuscript_build_tables.build_id",
                "manuscript_build_tables.publication_id",
                "manuscript_build_tables.project_id",
                "manuscript_build_tables.user_id",
            ],
            name="fk_build_metric_table",
        ),
        ForeignKeyConstraint(
            ["metric_id", "result_id", "project_id", "user_id"],
            [
                "server_result_metrics.id",
                "server_result_metrics.result_id",
                "server_result_metrics.project_id",
                "server_result_metrics.user_id",
            ],
            name="fk_build_metric_source",
        ),
        UniqueConstraint("table_id", "position", name="uq_build_metric_position"),
    )
    table_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    result_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    metric_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    result_sha256: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(80))
    split: Mapped[str | None] = mapped_column(String(80))
    evaluation_protocol: Mapped[str | None] = mapped_column(Text)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)


class ManuscriptBuildAttempt(BuildChild, Base):
    __tablename__ = "manuscript_build_attempts"
    __table_args__ = (
        build_fk("attempt"),
        CheckConstraint("kind IN ('SOURCE_SAVE','COMPILE')", name="ck_build_attempt_kind"),
        CheckConstraint(
            "status IN ('SAVING','RUNNING','READY','FAILED','UNAVAILABLE','TIMED_OUT','NEEDS_ATTENTION','CANCELLED','LATE')",
            name="ck_build_attempt_status",
        ),
        CheckConstraint(
            "(source_zip_sha256 IS NULL AND source_zip_size_bytes IS NULL) OR (length(source_zip_sha256)=64 AND source_zip_size_bytes BETWEEN 1 AND 41943040)",
            name="ck_build_attempt_zip",
        ),
        *[
            ForeignKeyConstraint(
                [name, "user_id"],
                ["attachments.id", "attachments.user_id"],
                name="fk_build_attempt_" + name,
            )
            for name in ("source_attachment_id", "pdf_attachment_id", "log_attachment_id")
        ],
    )
    status: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(16))
    image_id: Mapped[str | None] = mapped_column(String(80))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    observations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_zip_sha256: Mapped[str | None] = mapped_column(String(64))
    source_zip_size_bytes: Mapped[int | None] = mapped_column(Integer)
    pdf_attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    log_attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManuscriptBuildOperation(BuildChild, Base):
    __tablename__ = "manuscript_build_operations"
    __table_args__ = (
        build_fk("operation"),
        UniqueConstraint("build_id", "kind", "idempotency_key", name="uq_build_operation_key"),
        CheckConstraint(
            "kind IN ('cancel','retry') AND length(request_sha256)=64", name="ck_build_operation"
        ),
    )
    kind: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
