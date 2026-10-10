"""Frozen selected code, provenance-bound proposals and fenced file application."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CodeChangePlan(Base):
    __tablename__ = "code_change_plans"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_code_plan_scope"),
        UniqueConstraint("user_id", "project_id", "idempotency_key", name="uq_code_plan_key"),
        UniqueConstraint("task_id", "user_id", name="uq_code_plan_task"),
        UniqueConstraint("id", "task_id", "user_id", name="uq_code_plan_task_source"),
        ForeignKeyConstraint(
            ["binding_id", "project_id", "user_id"],
            [
                "project_archive_bindings.id",
                "project_archive_bindings.project_id",
                "project_archive_bindings.user_id",
            ],
            name="fk_code_plan_binding",
        ),
        ForeignKeyConstraint(
            ["task_id", "user_id"],
            ["codex_tasks.id", "codex_tasks.user_id"],
            name="fk_code_plan_task",
        ),
        CheckConstraint(
            "status IN ('DRAFT','PROPOSED','APPLYING','APPLIED','PARTIAL','NEEDS_ATTENTION','ABANDONED')",
            name="ck_code_plan_status",
        ),
        CheckConstraint(
            "length(preview_sha256)=64 AND length(workspace_fingerprint)=64 AND length(task_request_sha256)=64 AND length(prompt_sha256)=64",
            name="ck_code_plan_hash",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    binding_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    create_sha256: Mapped[str] = mapped_column(String(64))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    workspace_fingerprint: Mapped[str] = mapped_column(String(64))
    binding_facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    instructions: Mapped[str] = mapped_column(Text)
    task_request_sha256: Mapped[str] = mapped_column(String(64))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    approved_source_transfer: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    current_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CodeChangeInputFile(Base):
    __tablename__ = "code_change_input_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "project_id", "user_id"],
            ["code_change_plans.id", "code_change_plans.project_id", "code_change_plans.user_id"],
            name="fk_code_input_plan",
        ),
        UniqueConstraint("plan_id", "position", name="uq_code_input_position"),
        CheckConstraint("size_bytes BETWEEN 0 AND 262144", name="ck_code_input_size"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    path: Mapped[str] = mapped_column(String(240), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    exists: Mapped[bool] = mapped_column(Boolean)
    sha256: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)


class CodeChangeProposal(Base):
    __tablename__ = "code_change_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "source_task_id", "user_id"],
            ["code_change_plans.id", "code_change_plans.task_id", "code_change_plans.user_id"],
            name="fk_code_proposal_exact_task",
        ),
        ForeignKeyConstraint(
            ["plan_id", "project_id", "user_id"],
            ["code_change_plans.id", "code_change_plans.project_id", "code_change_plans.user_id"],
            name="fk_code_proposal_plan",
        ),
        ForeignKeyConstraint(
            ["source_task_id", "user_id"],
            ["codex_tasks.id", "codex_tasks.user_id"],
            name="fk_code_proposal_task",
        ),
        CheckConstraint(
            "length(proposal_sha256)=64 AND length(result_sha256)=64", name="ck_code_proposal_hash"
        ),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result_sha256: Mapped[str] = mapped_column(String(64))
    proposal_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    raw_response: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CodeChangeProposalFile(Base):
    __tablename__ = "code_change_proposal_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id"], ["code_change_proposals.plan_id"], name="fk_code_proposal_file_proposal"
        ),
        ForeignKeyConstraint(
            ["plan_id", "path"],
            ["code_change_input_files.plan_id", "code_change_input_files.path"],
            name="fk_code_proposal_input",
        ),
        ForeignKeyConstraint(
            ["plan_id", "project_id", "user_id"],
            ["code_change_plans.id", "code_change_plans.project_id", "code_change_plans.user_id"],
            name="fk_code_proposal_file_scope",
        ),
        UniqueConstraint("plan_id", "position", name="uq_code_proposal_position"),
        CheckConstraint("size_bytes BETWEEN 0 AND 262144", name="ck_code_proposal_size"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    path: Mapped[str] = mapped_column(String(240), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    before_sha256: Mapped[str | None] = mapped_column(String(64))
    after_sha256: Mapped[str] = mapped_column(String(64))
    after_text: Mapped[str] = mapped_column(Text)
    diff: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)


class CodeChangeApplyAttempt(Base):
    __tablename__ = "code_change_apply_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "project_id", "user_id"],
            ["code_change_plans.id", "code_change_plans.project_id", "code_change_plans.user_id"],
            name="fk_code_apply_plan",
        ),
        UniqueConstraint("plan_id", "idempotency_key", name="uq_code_apply_key"),
        CheckConstraint(
            "status IN ('APPLYING','APPLIED','PARTIAL','NEEDS_ATTENTION','ABANDONED')",
            name="ck_code_apply_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    proposal_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24))
    acknowledge_unknown: Mapped[bool] = mapped_column(Boolean)
    receipts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    observations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
