"""Bounded planning grants, one-use permits, real attempts and independent candidates."""

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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ResearchStageGrant(Base):
    __tablename__ = "research_stage_grants"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_stage_grant_owner"),
        ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_stage_grant_brief_owner",
        ),
        CheckConstraint("state IN ('DRAFT','ACTIVE','REVOKED')", name="ck_stage_grant_state"),
        CheckConstraint(
            "scope IN ('BRIEF_METADATA_ONLY','BRIEF_DERIVED_NOTES') AND no_tools = true",
            name="ck_stage_grant_scope",
        ),
        CheckConstraint(
            "max_jobs BETWEEN 1 AND 20 AND used_jobs BETWEEN 0 AND max_jobs AND timeout_seconds BETWEEN 60 AND 1800",
            name="ck_stage_grant_limits",
        ),
        CheckConstraint(
            "length(sha256)=64 AND length(brief_sha256)=64 AND length(instructions_sha256)=64 AND length(source_manifest_sha256)=64 AND length(skills_root_fingerprint)=64",
            name="ck_stage_grant_hashes",
        ),
        CheckConstraint(
            "(state IN ('DRAFT','REVOKED') AND approved_by IS NULL AND approved_at IS NULL AND approved_sha256 IS NULL) OR (state IN ('ACTIVE','REVOKED') AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND approved_sha256 IS NOT NULL AND length(approved_sha256)=64 AND approved_by=user_id AND (state<>'ACTIVE' OR approved_sha256=sha256))",
            name="ck_stage_grant_approval",
        ),
        CheckConstraint(
            "(output_contract_sha256 IS NULL AND output_contract_payload IS NULL AND output_contract_version='planning-markdown-v1') OR (output_contract_sha256 IS NOT NULL AND output_contract_payload IS NOT NULL AND length(output_contract_sha256)=64)",
            name="ck_stage_output_contract_pair",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    brief_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    brief_sha256: Mapped[str] = mapped_column(String(64))
    profile: Mapped[str] = mapped_column(String(80))
    skill_key: Mapped[str] = mapped_column(String(80))
    skill_version: Mapped[str] = mapped_column(String(80))
    focus: Mapped[str] = mapped_column(Text)
    model_key: Mapped[str] = mapped_column(String(160))
    reasoning_effort: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    max_jobs: Mapped[int] = mapped_column(Integer)
    used_jobs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    state: Mapped[str] = mapped_column(String(16), default="DRAFT", server_default="DRAFT")
    scope: Mapped[str] = mapped_column(
        String(24), default="BRIEF_METADATA_ONLY", server_default="BRIEF_METADATA_ONLY"
    )
    no_tools: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    instructions_text: Mapped[str] = mapped_column(Text)
    adapter_warnings: Mapped[str] = mapped_column(Text, default="", server_default="")
    output_contract_version: Mapped[str] = mapped_column(
        String(64), default="planning-markdown-v1", server_default="planning-markdown-v1"
    )
    output_contract_sha256: Mapped[str | None] = mapped_column(String(64))
    output_contract_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    instructions_sha256: Mapped[str] = mapped_column(String(64))
    source_manifest_sha256: Mapped[str] = mapped_column(String(64))
    skills_root_fingerprint: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchStageSkillFile(Base):
    __tablename__ = "research_stage_skill_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["grant_id", "project_id", "user_id"],
            [
                "research_stage_grants.id",
                "research_stage_grants.project_id",
                "research_stage_grants.user_id",
            ],
            name="fk_stage_skill_grant_owner",
        ),
        CheckConstraint(
            "length(file_key_sha256)=64 AND length(sha256)=64 AND size_bytes BETWEEN 1 AND 256000 AND length(path) BETWEEN 1 AND 2000",
            name="ck_stage_skill_bounds",
        ),
        CheckConstraint("role IN ('INSTRUCTION','TEMPLATE')", name="ck_stage_skill_role"),
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    file_key_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    path: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(24))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)


class ResearchPlanningJob(Base):
    __tablename__ = "research_planning_jobs"
    __table_args__ = (
        UniqueConstraint(
            "id", "grant_id", "project_id", "user_id", name="uq_planning_job_grant_owner"
        ),
        UniqueConstraint("id", "project_id", "user_id", name="uq_planning_job_owner"),
        UniqueConstraint("grant_id", "idempotency_key", name="uq_planning_job_key"),
        UniqueConstraint("active_grant_id", name="uq_planning_job_active_grant"),
        ForeignKeyConstraint(
            ["active_grant_id", "project_id", "user_id"],
            [
                "research_stage_grants.id",
                "research_stage_grants.project_id",
                "research_stage_grants.user_id",
            ],
            name="fk_planning_job_active_grant_owner",
        ),
        CheckConstraint(
            "(status IN ('RUNNING','CANCEL_REQUESTED','NEEDS_ATTENTION') AND active_grant_id IS NOT NULL AND active_grant_id=grant_id) OR (status IN ('QUEUED','COMPLETED','FAILED','CANCELLED') AND active_grant_id IS NULL)",
            name="ck_planning_job_active_grant",
        ),
        ForeignKeyConstraint(
            ["grant_id", "project_id", "user_id"],
            [
                "research_stage_grants.id",
                "research_stage_grants.project_id",
                "research_stage_grants.user_id",
            ],
            name="fk_planning_job_grant_owner",
        ),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','CANCEL_REQUESTED','COMPLETED','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_planning_job_status",
        ),
        CheckConstraint(
            "length(manifest_sha256)=64 AND length(CAST(manifest_payload AS TEXT)) <= 2097152",
            name="ck_planning_job_manifest",
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_planning_job_lease",
        ),
        Index("ix_planning_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    active_grant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", server_default="QUEUED")
    manifest_payload: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
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


class ResearchExecutionPermit(Base):
    __tablename__ = "research_execution_permits"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_execution_permit_job"),
        UniqueConstraint("id", "job_id", "project_id", "user_id", name="uq_execution_permit_owner"),
        UniqueConstraint("nonce", name="uq_execution_permit_nonce"),
        ForeignKeyConstraint(
            ["job_id", "grant_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.grant_id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_execution_permit_job_grant_owner",
        ),
        CheckConstraint(
            "state IN ('RESERVED','ISSUED','STARTED','REVOKED') AND length(manifest_sha256)=64",
            name="ck_execution_permit_state_hash",
        ),
        CheckConstraint(
            "(state='RESERVED' AND issued_at IS NULL) OR (state IN ('ISSUED','STARTED') AND issued_at IS NOT NULL) OR state='REVOKED'",
            name="ck_execution_permit_issue_time",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    grant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default="RESERVED", server_default="RESERVED")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchPlanningAttempt(Base):
    __tablename__ = "research_planning_attempts"
    __table_args__ = (
        UniqueConstraint("permit_id", name="uq_planning_attempt_permit"),
        UniqueConstraint(
            "id", "job_id", "project_id", "user_id", name="uq_planning_attempt_job_owner"
        ),
        ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_planning_attempt_job_owner",
        ),
        ForeignKeyConstraint(
            ["permit_id", "job_id", "project_id", "user_id"],
            [
                "research_execution_permits.id",
                "research_execution_permits.job_id",
                "research_execution_permits.project_id",
                "research_execution_permits.user_id",
            ],
            name="fk_planning_attempt_permit_owner",
        ),
        CheckConstraint(
            "status IN ('RUNNING','COMPLETED','FAILED','NEEDS_ATTENTION','CANCELLED')",
            name="ck_planning_attempt_status",
        ),
        CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0)",
            name="ck_planning_attempt_usage",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    permit_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="RUNNING", server_default="RUNNING")
    provider_response_id: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)


class ResearchPlanningResult(Base):
    __tablename__ = "research_planning_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "job_id", "project_id", "user_id"],
            [
                "research_planning_attempts.id",
                "research_planning_attempts.job_id",
                "research_planning_attempts.project_id",
                "research_planning_attempts.user_id",
            ],
            name="fk_planning_result_attempt_owner",
        ),
        ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_planning_result_job_owner",
        ),
        CheckConstraint(
            "length(sha256)=64 AND size_bytes BETWEEN 1 AND 1048576 AND review_status='CANDIDATE'",
            name="ck_planning_result_candidate",
        ),
        CheckConstraint(
            "disposition IN ('AVAILABLE','QUARANTINED')", name="ck_planning_result_disposition"
        ),
        UniqueConstraint("job_id", "project_id", "user_id", name="uq_planning_result_owner"),
        CheckConstraint(
            "normalization_status IN ('AVAILABLE','UNUSABLE','NOT_REQUESTED','NOT_RECORDED','QUARANTINED')",
            name="ck_planning_result_normalization",
        ),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    markdown: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    review_status: Mapped[str] = mapped_column(
        String(24), default="CANDIDATE", server_default="CANDIDATE"
    )
    disposition: Mapped[str] = mapped_column(
        String(24), default="AVAILABLE", server_default="AVAILABLE"
    )
    normalization_status: Mapped[str] = mapped_column(
        String(24), default="NOT_RECORDED", server_default="NOT_RECORDED"
    )
    normalization_issue: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
