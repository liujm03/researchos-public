"""Owner-approved finite metadata planning; permits never grant tools or scientific execution."""

import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.pdf_reading import ReadingSkillSource
from app.domain.research_planning import (
    PLANNING_CONTRACT_V2,
    PROFILES,
    PlanningSkillProvider,
    output_contract_payload,
    planning_contract_sha256,
    planning_sources_sha256,
    validate_planning_contract,
)
from app.errors import DomainError
from app.models_research_planning import (
    ResearchExecutionPermit,
    ResearchPlanningAttempt,
    ResearchPlanningJob,
    ResearchPlanningResult,
    ResearchStageGrant,
    ResearchStageSkillFile,
)
from app.providers.registry import research_planning_skill_provider
from app.schemas_research_planning import (
    PlanningAttemptOut,
    PlanningCapabilityOut,
    PlanningGrantApprove,
    PlanningGrantCreate,
    PlanningGrantOut,
    PlanningJobCreate,
    PlanningJobOut,
    PlanningPermitOut,
    PlanningProfileOut,
    PlanningResultOut,
)
from app.services import brief_canonical_sources, brief_idea_sources, research_briefs
from app.services.common import cursor_filter, encode_cursor
from app.services.projects import get_project


def now() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _root_fingerprint() -> str:
    root = get_settings().research_planning_skills_root
    if not root or not Path(root).is_absolute():
        raise DomainError(
            "PLANNING_CONFIGURATION_REQUIRED",
            "An explicit absolute planning skills root is required",
            503,
        )
    return hashlib.sha256(os.path.normcase(os.path.abspath(root)).encode()).hexdigest()


def capability() -> PlanningCapabilityOut:
    settings = get_settings()
    configured = bool(
        settings.research_planning_skills_root
        and Path(settings.research_planning_skills_root).is_absolute()
        and settings.codex_provider == "openai_codex_sdk"
        and settings.codex_model.strip()
        and settings.codex_reasoning_effort.strip()
    )
    return PlanningCapabilityOut(
        enabled=settings.research_planning_enabled and configured,
        profiles=[PlanningProfileOut(key=key, label=key) for key in PROFILES],
        detail="Only the accepted brief, selected metadata/derived notes and frozen skill instructions may be sent to Codex; tools and scientific execution are excluded.",
    )


def _enabled() -> None:
    if not capability().enabled:
        raise DomainError(
            "RESEARCH_PLANNING_DISABLED", "Metadata planning is disabled or not configured", 503
        )


def get_grant(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> ResearchStageGrant:
    get_project(db, owner, project)
    query = select(ResearchStageGrant).where(
        ResearchStageGrant.id == identity,
        ResearchStageGrant.user_id == owner,
        ResearchStageGrant.project_id == project,
    )
    row = db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned planning grant not found", 404)
    return row


def _source_rows(db: Session, grant: ResearchStageGrant) -> list[ResearchStageSkillFile]:
    return list(
        db.scalars(
            select(ResearchStageSkillFile)
            .where(
                ResearchStageSkillFile.grant_id == grant.id,
                ResearchStageSkillFile.project_id == grant.project_id,
                ResearchStageSkillFile.user_id == grant.user_id,
            )
            .order_by(ResearchStageSkillFile.file_key_sha256)
        )
    )


def grant_hash(grant: ResearchStageGrant) -> str:
    fields = {
        key: getattr(grant, key)
        for key in (
            "id",
            "user_id",
            "project_id",
            "brief_id",
            "brief_sha256",
            "profile",
            "skill_key",
            "skill_version",
            "focus",
            "model_key",
            "reasoning_effort",
            "timeout_seconds",
            "max_jobs",
            "scope",
            "no_tools",
            "instructions_sha256",
            "adapter_warnings",
            "source_manifest_sha256",
            "skills_root_fingerprint",
        )
    }
    if grant.output_contract_sha256 is not None:
        fields.update(
            output_contract_version=grant.output_contract_version,
            output_contract_sha256=grant.output_contract_sha256,
        )
    return research_briefs.digest({**fields, "expires_at": utc(grant.expires_at).isoformat()})


def _validate_binding(db: Session, grant: ResearchStageGrant) -> None:
    validate_planning_contract(grant.output_contract_version, grant.output_contract_sha256)
    if grant.output_contract_sha256 is not None and (
        grant.output_contract_payload != output_contract_payload(grant.output_contract_version)
        or research_briefs.digest(grant.output_contract_payload) != grant.output_contract_sha256
    ):
        raise DomainError(
            "PLANNING_CONTRACT_CHANGED",
            "Frozen output schema and supplemental instructions changed",
            409,
        )
    if grant.approved_at is not None and grant.approved_sha256 != grant.sha256:
        raise DomainError(
            "PLANNING_APPROVAL_INVALID",
            "Current scope differs from the exact owner-approved hash",
            409,
        )
    if (
        grant_hash(grant) != grant.sha256
        or grant.scope not in {"BRIEF_METADATA_ONLY", "BRIEF_DERIVED_NOTES"}
        or not grant.no_tools
    ):
        raise DomainError("PLANNING_GRANT_CHANGED", "Frozen stage scope changed", 409)
    settings = get_settings()
    if grant.skills_root_fingerprint != _root_fingerprint() or (
        grant.model_key,
        grant.reasoning_effort,
    ) != (settings.codex_model, settings.codex_reasoning_effort):
        raise DomainError(
            "PLANNING_CONFIGURATION_CHANGED",
            "Planning model or skills root differs from the approved scope",
            409,
        )
    rows = _source_rows(db, grant)
    sources = tuple(
        ReadingSkillSource(row.path, row.role, row.sha256, row.size_bytes, row.content)
        for row in rows
    )
    if (
        not rows
        or len(rows) > 32
        or planning_sources_sha256(sources) != grant.source_manifest_sha256
        or hashlib.sha256(grant.instructions_text.encode()).hexdigest() != grant.instructions_sha256
    ):
        raise DomainError(
            "PLANNING_SOURCE_CHANGED", "Frozen professional skill evidence changed", 409
        )
    for row in rows:
        raw = row.content.encode()
        if (
            row.file_key_sha256 != research_briefs.digest({"path": row.path, "role": row.role})
            or not raw
            or len(raw) != row.size_bytes
            or len(raw) > 256000
            or hashlib.sha256(raw).hexdigest() != row.sha256
            or row.content.removeprefix("\ufeff") not in grant.instructions_text
        ):
            raise DomainError(
                "PLANNING_SOURCE_CHANGED",
                "Actual skill file snapshot differs from the approved instructions",
                409,
            )
    brief = research_briefs.get_brief(db, grant.user_id, grant.project_id, grant.brief_id)
    detail = research_briefs.detail_out(db, brief)
    expected_scope = (
        "BRIEF_DERIVED_NOTES"
        if detail.canonical_note_sources or brief_idea_sources.requires_note_permission(db, brief)
        else "BRIEF_METADATA_ONLY"
    )
    if grant.scope != expected_scope:
        raise DomainError(
            "PLANNING_GRANT_CHANGED", "Grant scope does not match selected sources", 409
        )
    _check_note_transfer(db, brief)
    if (
        brief.sha256 != grant.brief_sha256
        or detail.status != "ACCEPTED"
        or "BRIEF_HASH_INVALID" in detail.gaps
        or not detail.context_current
    ):
        raise DomainError(
            "PLANNING_BRIEF_CHANGED",
            "An intact accepted brief with current metadata is required",
            409,
        )


def _check_note_transfer(db: Session, brief: Any) -> None:
    if not brief_canonical_sources.rows(
        db, brief
    ) and not brief_idea_sources.requires_note_permission(db, brief):
        return
    from app.models import AnalysisSettings

    settings = db.scalar(
        select(AnalysisSettings)
        .where(AnalysisSettings.user_id == brief.user_id)
        .execution_options(populate_existing=True)
    )
    if settings is None or settings.cloud_scope != "FULL_TEXT":
        raise DomainError(
            "PLANNING_FULLTEXT_PERMISSION_REQUIRED",
            "Selected original-PDF-derived notes require the owner's FULL_TEXT cloud transfer permission",
            409,
        )


def validate_grant_for_execution(
    db: Session, grant: ResearchStageGrant, *, check_budget: bool = False
) -> None:
    _enabled()
    _validate_binding(db, grant)
    if grant.state != "ACTIVE" or grant.approved_by != grant.user_id or grant.approved_at is None:
        raise DomainError("PLANNING_GRANT_INACTIVE", "The owner stage grant is not active", 409)
    if utc(grant.expires_at) <= now():
        raise DomainError("PLANNING_GRANT_EXPIRED", "The stage grant has expired", 409)
    if check_budget and grant.used_jobs >= grant.max_jobs:
        raise DomainError("PLANNING_JOB_LIMIT", "All authorized task slots have been consumed", 409)


def _input_snapshot(db: Session, grant: ResearchStageGrant) -> dict[str, Any]:
    brief = research_briefs.get_brief(db, grant.user_id, grant.project_id, grant.brief_id)
    detail = research_briefs.detail_out(db, brief)
    snapshot = {
        "id": str(brief.id),
        "project_id": str(brief.project_id),
        "revision": brief.revision,
        "project_version": brief.project_version,
        "sha256": brief.sha256,
        "idea": brief.idea,
        "stop_rules": brief.stop_rules,
        "sections": [item.model_dump(mode="json") for item in detail.sections],
        "evidence_metadata": [item.model_dump(mode="json") for item in detail.evidence],
        "source_scope": "PAPER_METADATA_NOT_FULLTEXT",
    }
    if detail.canonical_note_sources:
        snapshot["source_scope"] = "DERIVED_NOTE"
        snapshot["canonical_note_sources"] = [
            {
                **brief_canonical_sources.values(item),
                **{
                    key: str(getattr(item, key))
                    for key in (
                        "canonical_note_id",
                        "paper_id",
                        "reading_job_id",
                        "reading_plan_id",
                        "pdf_attachment_id",
                    )
                },
            }
            for item in brief_canonical_sources.rows(db, brief)
        ]
    idea_rows = brief_idea_sources.rows(db, brief)
    if idea_rows:
        snapshot["idea_sources"] = [
            {
                **brief_idea_sources.values(item),
                "idea_id": str(item.idea_id),
                "revision_id": str(item.revision_id),
            }
            for item in idea_rows
        ]
        if brief_idea_sources.requires_note_permission(db, brief):
            snapshot["source_scope"] = "DERIVED_NOTE"
    return snapshot


def _manifest(
    db: Session, grant: ResearchStageGrant, job_id: uuid.UUID, focus: str
) -> dict[str, Any]:
    payload = {
        "schema_version": "research-planning-request-v1",
        "job_id": str(job_id),
        "grant_id": str(grant.id),
        "grant_sha256": grant.sha256,
        "brief_id": str(grant.brief_id),
        "brief_sha256": grant.brief_sha256,
        "profile": grant.profile,
        "skill_key": grant.skill_key,
        "skill_version": grant.skill_version,
        "instructions_sha256": grant.instructions_sha256,
        "source_manifest_sha256": grant.source_manifest_sha256,
        "model_key": grant.model_key,
        "reasoning_effort": grant.reasoning_effort,
        "stage": "PLANNING",
        "scope": grant.scope,
        "no_tools": True,
        "focus": focus,
        "input_snapshot": _input_snapshot(db, grant),
    }
    if grant.output_contract_sha256 is not None:
        payload.update(
            output_contract_version=grant.output_contract_version,
            output_contract_sha256=grant.output_contract_sha256,
        )
    return payload


def validate_manifest(db: Session, job: ResearchPlanningJob) -> dict[str, Any]:
    grant = get_grant(db, job.user_id, job.project_id, job.grant_id)
    validate_grant_for_execution(db, grant)
    payload = job.manifest_payload
    focus = payload.get("focus")
    if (
        not isinstance(focus, str)
        or len(focus) > 12000
        or research_briefs.digest(payload) != job.manifest_sha256
        or payload != _manifest(db, grant, job.id, focus)
    ):
        raise DomainError(
            "PLANNING_MANIFEST_CHANGED",
            "Frozen execution input differs from the permitted request",
            409,
        )
    return payload


async def create_grant(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    body: PlanningGrantCreate,
    *,
    skills: PlanningSkillProvider | None = None,
) -> ResearchStageGrant:
    _enabled()
    brief = research_briefs.get_brief(db, owner, project, body.brief_id)
    detail = research_briefs.detail_out(db, brief)
    if (
        brief.sha256 != body.expected_brief_sha256
        or detail.status != "ACCEPTED"
        or not detail.context_current
        or "BRIEF_HASH_INVALID" in detail.gaps
    ):
        raise DomainError(
            "PLANNING_BRIEF_NOT_ACCEPTED",
            "Review the exact current brief before creating a planning grant",
            409,
        )
    _check_note_transfer(db, brief)
    if body.profile not in PROFILES or body.expires_at <= now():
        raise DomainError(
            "PLANNING_SCOPE_INVALID", "Choose a supported profile and a future expiry", 422
        )
    receipt = await asyncio.to_thread(
        (skills or research_planning_skill_provider()).load, body.profile
    )
    if (
        receipt.profile != body.profile
        or receipt.key != body.profile
        or not receipt.files
        or len(receipt.files) > 32
    ):
        raise DomainError(
            "PLANNING_SKILL_INVALID", "The selected professional skill receipt is invalid", 409
        )
    settings = get_settings()
    grant = ResearchStageGrant(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project,
        brief_id=brief.id,
        brief_sha256=brief.sha256,
        profile=body.profile,
        skill_key=receipt.key,
        skill_version=receipt.version,
        focus=body.focus,
        model_key=settings.codex_model,
        reasoning_effort=settings.codex_reasoning_effort,
        expires_at=utc(body.expires_at),
        timeout_seconds=body.timeout_seconds,
        max_jobs=body.max_jobs,
        used_jobs=0,
        state="DRAFT",
        scope="BRIEF_DERIVED_NOTES"
        if detail.canonical_note_sources or brief_idea_sources.requires_note_permission(db, brief)
        else "BRIEF_METADATA_ONLY",
        no_tools=True,
        instructions_text=receipt.instructions,
        adapter_warnings="\n".join(receipt.warnings),
        output_contract_version=PLANNING_CONTRACT_V2,
        output_contract_sha256=planning_contract_sha256(PLANNING_CONTRACT_V2),
        output_contract_payload=output_contract_payload(PLANNING_CONTRACT_V2),
        instructions_sha256=receipt.instructions_sha256,
        source_manifest_sha256=receipt.manifest_sha256,
        skills_root_fingerprint=_root_fingerprint(),
        sha256="0" * 64,
        created_at=now(),
    )
    grant.sha256 = grant_hash(grant)
    try:
        db.add(grant)
        db.flush()
        db.add_all(
            [
                ResearchStageSkillFile(
                    grant_id=grant.id,
                    project_id=project,
                    user_id=owner,
                    file_key_sha256=research_briefs.digest({"path": file.path, "role": file.role}),
                    path=file.path,
                    role=file.role,
                    sha256=file.sha256,
                    size_bytes=file.size_bytes,
                    content=file.content,
                )
                for file in receipt.files
            ]
        )
        db.flush()
        _validate_binding(db, grant)
        db.commit()
    except DomainError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "PLANNING_SKILL_INVALID",
            "Professional skill source receipt violates the frozen contract",
            409,
        ) from None
    db.refresh(grant)
    return grant


def _enqueue(
    db: Session, grant: ResearchStageGrant, body: PlanningJobCreate
) -> ResearchPlanningJob:
    focus = grant.focus if body.focus is None else body.focus
    existing = db.scalar(
        select(ResearchPlanningJob).where(
            ResearchPlanningJob.grant_id == grant.id,
            ResearchPlanningJob.user_id == grant.user_id,
            ResearchPlanningJob.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None:
        if body.focus is not None and existing.manifest_payload.get("focus") != body.focus:
            raise DomainError(
                "PLANNING_IDEMPOTENCY_CONFLICT",
                "This submission key already identifies a different focus",
                409,
            )
        return existing
    validate_grant_for_execution(db, grant, check_budget=True)
    identity = uuid.uuid4()
    payload = _manifest(db, grant, identity, focus)
    import json

    if len(json.dumps(payload, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise DomainError(
            "PLANNING_INPUT_TOO_LARGE",
            "The selected metadata exceeds the bounded request size",
            422,
        )
    used = grant.used_jobs
    changed = db.execute(
        update(ResearchStageGrant)
        .where(
            ResearchStageGrant.id == grant.id,
            ResearchStageGrant.user_id == grant.user_id,
            ResearchStageGrant.state == "ACTIVE",
            ResearchStageGrant.used_jobs == used,
            ResearchStageGrant.used_jobs < ResearchStageGrant.max_jobs,
            ResearchStageGrant.expires_at > now(),
        )
        .values(used_jobs=used + 1)
        .returning(ResearchStageGrant.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if changed is None:
        raise DomainError(
            "PLANNING_JOB_LIMIT",
            "The grant counter or validity changed; reload the bounded scope",
            409,
        )
    job = ResearchPlanningJob(
        id=identity,
        user_id=grant.user_id,
        project_id=grant.project_id,
        grant_id=grant.id,
        status="QUEUED",
        manifest_payload=payload,
        manifest_sha256=research_briefs.digest(payload),
        idempotency_key=body.idempotency_key,
        created_at=now(),
    )
    db.add(job)
    db.flush()
    db.add(
        ResearchExecutionPermit(
            id=uuid.uuid4(),
            user_id=grant.user_id,
            project_id=grant.project_id,
            grant_id=grant.id,
            job_id=job.id,
            manifest_sha256=job.manifest_sha256,
            nonce=uuid.uuid4(),
            expires_at=grant.expires_at,
            state="RESERVED",
            issued_at=None,
        )
    )
    db.flush()
    return job


def approve_grant(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    identity: uuid.UUID,
    body: PlanningGrantApprove,
) -> ResearchStageGrant:
    grant = get_grant(db, owner, project, identity, lock=True)
    _enabled()
    _validate_binding(db, grant)
    if (
        body.expected_sha256 != grant.sha256
        or utc(grant.expires_at) <= now()
        or grant.state == "REVOKED"
    ):
        raise DomainError(
            "PLANNING_GRANT_CHANGED",
            "The exact active source scope must be approved before its expiry",
            409,
        )
    if grant.state == "ACTIVE":
        return grant
    try:
        grant.state, grant.approved_by, grant.approved_at = "ACTIVE", owner, now()
        grant.approved_sha256 = grant.sha256
        db.flush()
        _enqueue(db, grant, PlanningJobCreate(idempotency_key="initial:" + str(grant.id)))
        db.commit()
    except DomainError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "PLANNING_APPROVAL_CONFLICT",
            "Another exact scope approval was committed; reload its first task",
            409,
        ) from None
    db.refresh(grant)
    return grant


def enqueue_job(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID, body: PlanningJobCreate
) -> ResearchPlanningJob:
    try:
        grant = get_grant(db, owner, project, identity, lock=True)
        job = _enqueue(db, grant, body)
        db.commit()
    except DomainError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "PLANNING_SUBMISSION_CONFLICT",
            "Another bounded submission was committed; reconcile its identity",
            409,
        ) from None
    db.refresh(job)
    return job


def get_job(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ResearchPlanningJob:
    get_project(db, owner, project)
    job = db.scalar(
        select(ResearchPlanningJob).where(
            ResearchPlanningJob.id == identity,
            ResearchPlanningJob.user_id == owner,
            ResearchPlanningJob.project_id == project,
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Owned planning job not found", 404)
    return job


def cancel_job(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ResearchPlanningJob:
    job = get_job(db, owner, project, identity)
    changed = db.execute(
        update(ResearchPlanningJob)
        .where(
            ResearchPlanningJob.id == job.id,
            ResearchPlanningJob.user_id == owner,
            ResearchPlanningJob.status == "QUEUED",
        )
        .values(status="CANCELLED", finished_at=now())
        .returning(ResearchPlanningJob.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if changed is None:
        db.execute(
            update(ResearchPlanningJob)
            .where(
                ResearchPlanningJob.id == job.id,
                ResearchPlanningJob.user_id == owner,
                ResearchPlanningJob.status == "RUNNING",
            )
            .values(status="CANCEL_REQUESTED")
        )
    db.execute(
        update(ResearchExecutionPermit)
        .where(ResearchExecutionPermit.job_id == job.id, ResearchExecutionPermit.user_id == owner)
        .values(state="REVOKED")
    )
    db.commit()
    db.refresh(job)
    return job


def revoke_grant(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ResearchStageGrant:
    grant = get_grant(db, owner, project, identity, lock=True)
    grant.state = "REVOKED"
    queued = list(
        db.scalars(
            select(ResearchPlanningJob.id).where(
                ResearchPlanningJob.grant_id == grant.id,
                ResearchPlanningJob.user_id == owner,
                ResearchPlanningJob.status == "QUEUED",
            )
        )
    )
    for job_id in queued:
        db.execute(
            update(ResearchPlanningJob)
            .where(ResearchPlanningJob.id == job_id, ResearchPlanningJob.status == "QUEUED")
            .values(status="CANCELLED", finished_at=now())
        )
    db.execute(
        update(ResearchPlanningJob)
        .where(
            ResearchPlanningJob.grant_id == grant.id,
            ResearchPlanningJob.user_id == owner,
            ResearchPlanningJob.status == "RUNNING",
        )
        .values(status="CANCEL_REQUESTED")
    )
    db.execute(
        update(ResearchExecutionPermit)
        .where(
            ResearchExecutionPermit.grant_id == grant.id, ResearchExecutionPermit.user_id == owner
        )
        .values(state="REVOKED")
    )
    db.commit()
    db.refresh(grant)
    return grant


def list_grants(
    db: Session, owner: uuid.UUID, project: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[ResearchStageGrant], str | None]:
    get_project(db, owner, project)
    rows = list(
        db.scalars(
            select(ResearchStageGrant)
            .where(
                ResearchStageGrant.user_id == owner,
                ResearchStageGrant.project_id == project,
                cursor_filter(ResearchStageGrant, cursor),
            )
            .order_by(ResearchStageGrant.created_at.desc(), ResearchStageGrant.id.desc())
            .limit(limit + 1)
        )
    )
    next_cursor = (
        encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    )
    return rows[:limit], next_cursor


def list_project_jobs(
    db: Session, owner: uuid.UUID, project: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[ResearchPlanningJob], str | None]:
    get_project(db, owner, project)
    rows = list(
        db.scalars(
            select(ResearchPlanningJob)
            .where(
                ResearchPlanningJob.user_id == owner,
                ResearchPlanningJob.project_id == project,
                cursor_filter(ResearchPlanningJob, cursor),
            )
            .order_by(ResearchPlanningJob.created_at.desc(), ResearchPlanningJob.id.desc())
            .limit(limit + 1)
        )
    )
    next_cursor = (
        encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    )
    return rows[:limit], next_cursor


def list_jobs(
    db: Session, owner: uuid.UUID, project: uuid.UUID, grant_id: uuid.UUID
) -> list[ResearchPlanningJob]:
    get_grant(db, owner, project, grant_id)
    return list(
        db.scalars(
            select(ResearchPlanningJob)
            .where(
                ResearchPlanningJob.user_id == owner,
                ResearchPlanningJob.project_id == project,
                ResearchPlanningJob.grant_id == grant_id,
            )
            .order_by(ResearchPlanningJob.created_at.desc())
            .limit(100)
        )
    )


def grant_out(db: Session, grant: ResearchStageGrant) -> PlanningGrantOut:
    current = True
    try:
        _validate_binding(db, grant)
    except (DomainError, ValueError, TypeError, UnicodeError):
        current = False
    initial = db.scalar(
        select(ResearchPlanningJob.id).where(
            ResearchPlanningJob.user_id == grant.user_id,
            ResearchPlanningJob.grant_id == grant.id,
            ResearchPlanningJob.idempotency_key == "initial:" + str(grant.id),
        )
    )
    fields = {
        key: getattr(grant, key)
        for key in (
            "id",
            "project_id",
            "brief_id",
            "brief_sha256",
            "sha256",
            "profile",
            "focus",
            "skill_key",
            "skill_version",
            "instructions_sha256",
            "source_manifest_sha256",
            "output_contract_version",
            "output_contract_sha256",
            "output_contract_payload",
            "state",
            "scope",
            "no_tools",
            "model_key",
            "reasoning_effort",
            "expires_at",
            "timeout_seconds",
            "max_jobs",
            "used_jobs",
            "approved_at",
            "approved_sha256",
            "created_at",
        )
    }
    return PlanningGrantOut(
        **fields,
        jobs_remaining=grant.max_jobs - grant.used_jobs,
        context_current=current,
        expired=utc(grant.expires_at) <= now(),
        effective_state="EXPIRED"
        if utc(grant.expires_at) <= now() and grant.state != "REVOKED"
        else grant.state,
        warnings=grant.adapter_warnings.splitlines(),
        gaps=["NO_NATIVE_SKILL_TOOLS_OR_SCIENTIFIC_EXECUTION"]
        + (["SOURCE_SCOPE_CHANGED"] if not current else [])
        + (["GRANT_EXPIRED"] if utc(grant.expires_at) <= now() else [])
        + (["PLANNING_CAPABILITY_DISABLED"] if not capability().enabled else [])
        + (["TASK_SLOTS_CONSUMED"] if grant.used_jobs >= grant.max_jobs else []),
        can_submit=current
        and capability().enabled
        and grant.state == "ACTIVE"
        and utc(grant.expires_at) > now()
        and grant.used_jobs < grant.max_jobs,
        initial_job_id=initial,
        files=[
            {
                "path": row.path,
                "role": row.role,
                "sha256": row.sha256,
                "size_bytes": row.size_bytes,
                "content": row.content,
            }
            for row in _source_rows(db, grant)
        ],
        brief=research_briefs.detail_out(
            db, research_briefs.get_brief(db, grant.user_id, grant.project_id, grant.brief_id)
        ),
    )


def job_out(db: Session, job: ResearchPlanningJob) -> PlanningJobOut:
    permit = db.scalar(
        select(ResearchExecutionPermit).where(
            ResearchExecutionPermit.job_id == job.id,
            ResearchExecutionPermit.project_id == job.project_id,
            ResearchExecutionPermit.user_id == job.user_id,
        )
    )
    attempts = list(
        db.scalars(
            select(ResearchPlanningAttempt)
            .where(
                ResearchPlanningAttempt.job_id == job.id,
                ResearchPlanningAttempt.project_id == job.project_id,
                ResearchPlanningAttempt.user_id == job.user_id,
            )
            .order_by(ResearchPlanningAttempt.started_at)
        )
    )
    result = db.scalar(
        select(ResearchPlanningResult).where(
            ResearchPlanningResult.job_id == job.id,
            ResearchPlanningResult.project_id == job.project_id,
            ResearchPlanningResult.user_id == job.user_id,
        )
    )
    return PlanningJobOut(
        id=job.id,
        project_id=job.project_id,
        grant_id=job.grant_id,
        status=job.status,
        manifest_sha256=job.manifest_sha256,
        focus=str(job.manifest_payload.get("focus", "")),
        input_snapshot=job.manifest_payload.get("input_snapshot", {}),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        error_message=job.error_message,
        permit=PlanningPermitOut.model_validate(permit) if permit else None,
        attempts=[PlanningAttemptOut.model_validate(row) for row in attempts],
        result=PlanningResultOut.model_validate(result) if result else None,
    )
