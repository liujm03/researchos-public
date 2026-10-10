"""Frozen writing inputs, actual Skill bytes, original candidates and adoption receipts."""

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


class WritingPlan(Base):
    __tablename__ = "writing_plans"
    __table_args__ = (
        UniqueConstraint(
            "id", "publication_id", "project_id", "user_id", name="uq_writing_plan_owner"
        ),
        UniqueConstraint("publication_id", "user_id", "create_key", name="uq_writing_plan_key"),
        UniqueConstraint("task_id", name="uq_writing_task"),
        ForeignKeyConstraint(
            ["revision_id", "publication_id", "project_id", "user_id"],
            [
                "publication_revisions.id",
                "publication_revisions.publication_id",
                "publication_revisions.project_id",
                "publication_revisions.user_id",
            ],
            name="fk_writing_publication_revision",
        ),
        ForeignKeyConstraint(
            ["task_id", "user_id"],
            ["codex_tasks.id", "codex_tasks.user_id"],
            name="fk_writing_task_owner",
        ),
        CheckConstraint(
            "length(preview_sha256)=64 AND length(create_sha256)=64 AND length(prompt_sha256)=64",
            name="ck_writing_plan_hash",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    publication_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    create_key: Mapped[str] = mapped_column(String(120))
    create_sha256: Mapped[str] = mapped_column(String(64))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    preview_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    instructions: Mapped[str] = mapped_column(Text)
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    task_request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def plan_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["plan_id", "publication_id", "project_id", "user_id"],
        [
            "writing_plans.id",
            "writing_plans.publication_id",
            "writing_plans.project_id",
            "writing_plans.user_id",
        ],
        name="fk_writing_" + name + "_plan",
    )


class WritingChild:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    publication_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)


class WritingSkillFile(WritingChild, Base):
    __tablename__ = "writing_skill_files"
    __table_args__ = (
        plan_fk("skill"),
        UniqueConstraint("plan_id", "path", name="uq_writing_skill_path"),
        CheckConstraint(
            "size_bytes BETWEEN 1 AND 256000 AND length(sha256)=64", name="ck_writing_skill_file"
        ),
    )
    path: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(24))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)


class WritingCandidate(WritingChild, Base):
    __tablename__ = "writing_candidates"
    __table_args__ = (
        plan_fk("candidate"),
        UniqueConstraint("plan_id", name="uq_writing_candidate_plan"),
        CheckConstraint(
            "length(sha256)=64 AND length(task_response_sha256)=64 AND length(request_sha256)=64",
            name="ck_writing_candidate_hash",
        ),
    )
    markdown: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    task_response_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WritingOperation(WritingChild, Base):
    __tablename__ = "writing_operations"
    __table_args__ = (
        plan_fk("operation"),
        UniqueConstraint("plan_id", "kind", "idempotency_key", name="uq_writing_operation_key"),
        ForeignKeyConstraint(
            ["publication_revision_id", "publication_id", "project_id", "user_id"],
            [
                "publication_revisions.id",
                "publication_revisions.publication_id",
                "publication_revisions.project_id",
                "publication_revisions.user_id",
            ],
            name="fk_writing_adoption_revision",
        ),
        CheckConstraint(
            "kind IN ('start','import','adopt','issue') AND length(request_sha256)=64",
            name="ck_writing_operation_kind",
        ),
        ForeignKeyConstraint(
            ["task_id", "project_id", "user_id"],
            ["tasks.id", "tasks.project_id", "tasks.user_id"],
            name="fk_writing_issue_task",
        ),
        CheckConstraint(
            "(kind='issue' AND task_id IS NOT NULL AND severity IN ('CRITICAL','MAJOR','MINOR')) OR (kind<>'issue' AND task_id IS NULL AND severity IS NULL)",
            name="ck_writing_issue_receipt",
        ),
    )
    kind: Mapped[str] = mapped_column(String(16))
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    severity: Mapped[str | None] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    publication_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    revision_sha256: Mapped[str | None] = mapped_column(String(64))
    exact_quote: Mapped[str | None] = mapped_column(Text)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
