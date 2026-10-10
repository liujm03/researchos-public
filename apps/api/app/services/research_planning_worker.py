"""One-use planning attempts with durable fencing and no unknown-call replay."""

import asyncio
import hashlib
import uuid
from contextlib import suppress
from datetime import timedelta
from time import monotonic
from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.domain.research_planning import (
    PLANNING_CONTRACT_V1,
    PlanningRequest,
    PlanningResponse,
    ResearchPlanningProvider,
    validate_planning_contract,
)
from app.errors import DomainError
from app.models_research_planning import (
    ResearchExecutionPermit,
    ResearchPlanningAttempt,
    ResearchPlanningJob,
    ResearchPlanningResult,
)
from app.providers.registry import research_planning_provider
from app.services import research_planning as policy

POLL_SECONDS = 1.0
CANCEL_WAIT_SECONDS = 10.0
MAX_RESULT_BYTES = 1_048_576
_pending: dict[uuid.UUID, asyncio.Task[PlanningResponse]] = {}


def _owned_job(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> ResearchPlanningJob | None:
    query = select(ResearchPlanningJob).where(
        ResearchPlanningJob.id == identity, ResearchPlanningJob.user_id == owner
    )
    return db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )


def _permit(
    db: Session, job: ResearchPlanningJob, *, lock: bool = False
) -> ResearchExecutionPermit | None:
    query = select(ResearchExecutionPermit).where(
        ResearchExecutionPermit.job_id == job.id,
        ResearchExecutionPermit.user_id == job.user_id,
        ResearchExecutionPermit.project_id == job.project_id,
        ResearchExecutionPermit.grant_id == job.grant_id,
    )
    return db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )


def _attempt(db: Session, job: ResearchPlanningJob) -> ResearchPlanningAttempt | None:
    return db.scalar(
        select(ResearchPlanningAttempt)
        .where(
            ResearchPlanningAttempt.job_id == job.id,
            ResearchPlanningAttempt.user_id == job.user_id,
            ResearchPlanningAttempt.project_id == job.project_id,
        )
        .execution_options(populate_existing=True)
    )


def _release(job: ResearchPlanningJob, status: str, code: str | None = None) -> None:
    job.status, job.error_code = status, code
    job.error_message = (
        "Planning operation ended without a publishable authorized candidate" if code else None
    )
    job.finished_at = policy.now()
    if status != "NEEDS_ATTENTION":
        job.active_grant_id = None
        job.lease_token = job.lease_expires_at = None


def recover_stale(db: Session, owner: uuid.UUID) -> ResearchPlanningJob | None:
    job = db.scalar(
        select(ResearchPlanningJob)
        .where(
            ResearchPlanningJob.user_id == owner,
            ResearchPlanningJob.status.in_(("RUNNING", "CANCEL_REQUESTED")),
            or_(
                ResearchPlanningJob.lease_expires_at <= policy.now(),
                ResearchPlanningJob.lease_token.is_(None),
            ),
        )
        .with_for_update(skip_locked=True)
        .order_by(ResearchPlanningJob.created_at)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if job is None:
        db.rollback()
        return None
    permit, attempt = _permit(db, job, lock=True), _attempt(db, job)
    started = attempt is not None or (permit is not None and permit.state == "STARTED")
    _release(
        job,
        "NEEDS_ATTENTION" if started else "FAILED",
        "PLANNING_OUTCOME_UNKNOWN" if started else "PLANNING_NOT_SUBMITTED",
    )
    if attempt is not None and attempt.status == "RUNNING":
        attempt.status, attempt.error_code, attempt.ended_at = (
            "NEEDS_ATTENTION",
            "PLANNING_OUTCOME_UNKNOWN",
            policy.now(),
        )
    if permit is not None:
        permit.state = "REVOKED"
    db.commit()
    return job


def _claim(db: Session, owner: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    active = aliased(ResearchPlanningJob)
    occupied = exists(
        select(active.id).where(
            active.user_id == owner, active.active_grant_id == ResearchPlanningJob.grant_id
        )
    )
    job = db.scalar(
        select(ResearchPlanningJob)
        .where(
            ResearchPlanningJob.user_id == owner, ResearchPlanningJob.status == "QUEUED", ~occupied
        )
        .order_by(ResearchPlanningJob.created_at, ResearchPlanningJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if job is None:
        db.rollback()
        return None
    token = uuid.uuid4()
    try:
        grant = policy.get_grant(db, owner, job.project_id, job.grant_id, lock=True)
        policy.validate_grant_for_execution(db, grant)
        policy.validate_manifest(db, job)
        permit = _permit(db, job, lock=True)
        if (
            permit is None
            or permit.state not in {"RESERVED", "ISSUED"}
            or permit.manifest_sha256 != job.manifest_sha256
            or _attempt(db, job) is not None
        ):
            raise DomainError(
                "PLANNING_PERMIT_INVALID", "Planning submission has no unused owner permit", 409
            )
        if policy.utc(permit.expires_at) <= policy.now():
            raise DomainError(
                "PLANNING_PERMIT_EXPIRED", "Planning submission permit has expired", 409
            )
        if permit.state == "RESERVED":
            permit.state, permit.issued_at = "ISSUED", policy.now()
            permit.expires_at = min(
                policy.utc(grant.expires_at), policy.now() + timedelta(seconds=60)
            )
        job.status, job.active_grant_id, job.lease_token = "RUNNING", job.grant_id, token
        job.lease_expires_at = policy.now() + timedelta(seconds=grant.timeout_seconds + 60)
        job.started_at = policy.now()
        db.commit()
        return job.id, token
    except IntegrityError:
        db.rollback()
        return None
    except DomainError as error:
        db.rollback()
        fresh = _owned_job(db, owner, job.id, lock=True)
        if fresh is not None and fresh.status == "QUEUED":
            _release(fresh, "FAILED", error.code)
            permit = _permit(db, fresh, lock=True)
            if permit is not None:
                permit.state = "REVOKED"
            db.commit()
        else:
            db.rollback()
        return None


def _uncalled(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, token: uuid.UUID, code: str
) -> None:
    job = _owned_job(db, owner, identity, lock=True)
    if job is None or job.lease_token != token or _attempt(db, job) is not None:
        db.rollback()
        return
    _release(job, "CANCELLED" if job.status == "CANCEL_REQUESTED" else "FAILED", code)
    permit = _permit(db, job, lock=True)
    if permit is not None:
        permit.state = "REVOKED"
    db.commit()


def _start(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
    model_key: str | None = None,
) -> PlanningRequest:
    job = _owned_job(db, owner, identity, lock=True)
    if (
        job is None
        or job.lease_token != token
        or job.status != "RUNNING"
        or job.lease_expires_at is None
        or policy.utc(job.lease_expires_at) <= policy.now()
    ):
        raise DomainError("PLANNING_LEASE_CHANGED", "Planning claim is no longer executable", 409)
    grant = policy.get_grant(db, owner, job.project_id, job.grant_id, lock=True)
    if model_key is not None and grant.model_key != model_key:
        raise DomainError(
            "PLANNING_CONFIGURATION_CHANGED",
            "Planning provider model differs from the approved input",
            409,
        )
    policy.validate_grant_for_execution(db, grant)
    payload = policy.validate_manifest(db, job)
    contract_version = payload.get("output_contract_version", PLANNING_CONTRACT_V1)
    contract_sha256 = payload.get("output_contract_sha256")
    validate_planning_contract(contract_version, contract_sha256)
    permit = _permit(db, job, lock=True)
    if (
        permit is None
        or permit.state != "ISSUED"
        or permit.issued_at is None
        or permit.manifest_sha256 != job.manifest_sha256
        or policy.utc(permit.expires_at) <= policy.now()
        or _attempt(db, job) is not None
    ):
        raise DomainError(
            "PLANNING_PERMIT_INVALID", "No fresh unused submission permit remains", 409
        )
    attempt = ResearchPlanningAttempt(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=job.project_id,
        job_id=job.id,
        permit_id=permit.id,
        status="RUNNING",
        started_at=policy.now(),
    )
    permit.state = "STARTED"
    job.lease_expires_at = policy.now() + timedelta(seconds=grant.timeout_seconds + 60)
    db.add(attempt)
    request = PlanningRequest(
        job.id,
        attempt.id,
        job.manifest_sha256,
        grant.model_key,
        grant.reasoning_effort,
        payload["focus"],
        payload["input_snapshot"],
        grant.instructions_text,
        grant.timeout_seconds,
        permit.nonce,
        contract_version,
        contract_sha256,
    )
    db.commit()
    return request


def _control(
    db: Session, owner: uuid.UUID, request: PlanningRequest, token: uuid.UUID
) -> str | None:
    job = _owned_job(db, owner, request.job_id)
    if (
        job is None
        or job.lease_token != token
        or job.manifest_sha256 != request.manifest_sha256
        or job.lease_expires_at is None
        or policy.utc(job.lease_expires_at) <= policy.now()
    ):
        return "PLANNING_LEASE_CHANGED"
    if job.status != "RUNNING":
        return "PLANNING_CANCEL_REQUESTED"
    permit, attempt = _permit(db, job), _attempt(db, job)
    if (
        permit is None
        or permit.state != "STARTED"
        or attempt is None
        or attempt.id != request.attempt_id
        or attempt.permit_id != permit.id
        or permit.manifest_sha256 != request.manifest_sha256
        or permit.nonce != request.permit_nonce
    ):
        return "PLANNING_PERMIT_REVOKED"
    # STARTED uses the independent grant/request/lease bounds, not submission TTL.
    try:
        validate_planning_contract(request.output_contract_version, request.output_contract_sha256)
        grant = policy.get_grant(db, owner, job.project_id, job.grant_id)
        policy.validate_grant_for_execution(db, grant)
        policy.validate_manifest(db, job)
    except DomainError as error:
        return error.code
    return None


def _metadata(attempt: ResearchPlanningAttempt, values: dict[str, Any]) -> None:
    identity = values.get("provider_response_id")
    if isinstance(identity, str) and len(identity) <= 200 and "\0" not in identity:
        attempt.provider_response_id = identity
    usage = values.get("usage")
    if isinstance(usage, dict):
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key)
            if type(value) is int and value >= 0:
                setattr(attempt, key, value)


def _finish(
    db: Session,
    owner: uuid.UUID,
    request: PlanningRequest,
    token: uuid.UUID,
    response: PlanningResponse | None,
    error: BaseException | None,
    *,
    force_quarantine: bool = False,
) -> bool:
    job = _owned_job(db, owner, request.job_id, lock=True)
    if job is None or job.lease_token != token or job.manifest_sha256 != request.manifest_sha256:
        db.rollback()
        return False
    permit, attempt = _permit(db, job, lock=True), _attempt(db, job)
    if (
        permit is None
        or attempt is None
        or attempt.id != request.attempt_id
        or attempt.permit_id != permit.id
        or permit.manifest_sha256 != request.manifest_sha256
        or permit.nonce != request.permit_nonce
    ):
        db.rollback()
        return False
    reason = _control(db, owner, request, token)
    existing = db.get(ResearchPlanningResult, job.id)
    if response is not None:
        raw = response.markdown.encode("utf-8")
        if not response.markdown.strip() or b"\0" in raw or len(raw) > MAX_RESULT_BYTES:
            error = DomainError(
                "AI_INVALID_OUTPUT",
                "Completed planning Markdown is not usable",
                502,
                details={
                    "provider_completed": True,
                    "provider_response_id": response.provider_response_id,
                    "usage": {
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                    },
                },
            )
            response = None
        elif existing is not None:
            db.rollback()
            return False
        else:
            quarantined = force_quarantine or reason is not None
            result = ResearchPlanningResult(
                job_id=job.id,
                user_id=owner,
                project_id=job.project_id,
                attempt_id=attempt.id,
                markdown=response.markdown,
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
                disposition="QUARANTINED" if quarantined else "AVAILABLE",
                review_status="CANDIDATE",
            )
            db.add(result)
            db.flush()
            if request.output_contract_version != PLANNING_CONTRACT_V1:
                from app.services.planning_brief_proposals import save_normalization

                try:
                    with db.begin_nested():
                        save_normalization(
                            db,
                            result,
                            response.normalization,
                            response.normalization_issue,
                            request.output_contract_version,
                            request.output_contract_sha256,
                        )
                except Exception:
                    # Secondary failure preserves the original result and usage.
                    result.normalization_status = "UNUSABLE"
                    result.normalization_issue = "NORMALIZATION_PERSISTENCE_FAILED"
            _metadata(
                attempt,
                {
                    "provider_response_id": response.provider_response_id,
                    "usage": {
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                    },
                },
            )
            attempt.status, attempt.ended_at = "COMPLETED", policy.now()
            _release(
                job, "CANCELLED" if quarantined else "COMPLETED", reason if quarantined else None
            )
            db.commit()
            return True
    details = (
        error.details if isinstance(error, DomainError) and isinstance(error.details, dict) else {}
    )
    _metadata(attempt, details)
    code = error.code if isinstance(error, DomainError) else "AI_OUTCOME_UNCERTAIN"
    known = (
        details.get("provider_completed") is True
        or details.get("submitted") is False
        or details.get("submission_attempted") is False
        or details.get("turn_status") in {"failed", "completed", "interrupted"}
        or code
        in {"AI_REQUEST_NOT_SENT", "AI_REQUEST_REJECTED", "AI_QUOTA_EXHAUSTED", "AI_RATE_LIMITED"}
    )
    cancelled = reason is not None or job.status == "CANCEL_REQUESTED"
    attempt.status, attempt.error_code, attempt.ended_at = (
        ("CANCELLED" if cancelled and known else "FAILED" if known else "NEEDS_ATTENTION"),
        code,
        policy.now(),
    )
    attempt.error_message = "Planning attempt ended with a classified provider outcome"
    _release(
        job, "CANCELLED" if cancelled and known else "FAILED" if known else "NEEDS_ATTENTION", code
    )
    if not known:
        permit.state = "REVOKED"
    db.commit()
    return True


def _retain_late(
    task: asyncio.Task[PlanningResponse],
    db: Session,
    owner: uuid.UUID,
    request: PlanningRequest,
    token: uuid.UUID,
) -> None:
    bind = db.get_bind()
    _pending[request.attempt_id] = task

    def late(done: asyncio.Task[PlanningResponse]) -> None:
        _pending.pop(request.attempt_id, None)
        with suppress(Exception):
            candidate, failure = None, None
            try:
                candidate = done.result()
            except BaseException as observed:
                failure = observed
            with Session(bind) as final:
                _finish(final, owner, request, token, candidate, failure, force_quarantine=True)

    task.add_done_callback(late)


async def process_next(
    db: Session, owner: uuid.UUID, provider: ResearchPlanningProvider | None = None
) -> ResearchPlanningJob | None:
    recovered = recover_stale(db, owner)
    if recovered is not None:
        return recovered
    if not policy.capability().enabled:
        db.rollback()
        return None
    active = aliased(ResearchPlanningJob)
    occupied = exists(
        select(active.id).where(
            active.user_id == owner, active.active_grant_id == ResearchPlanningJob.grant_id
        )
    )
    queued = db.scalar(
        select(ResearchPlanningJob.id)
        .where(
            ResearchPlanningJob.user_id == owner, ResearchPlanningJob.status == "QUEUED", ~occupied
        )
        .limit(1)
    )
    db.rollback()
    if queued is None:
        return None
    selected = provider if provider is not None else research_planning_provider()
    try:
        descriptor = await asyncio.to_thread(selected.descriptor)
    except Exception:
        return None
    if (
        not descriptor.available
        or not isinstance(descriptor.model_key, str)
        or not descriptor.model_key.strip()
    ):
        return None
    claimed = _claim(db, owner)
    if claimed is None:
        return None
    identity, token = claimed
    try:
        request = _start(db, owner, identity, token, descriptor.model_key)
    except Exception as preflight_error:
        db.rollback()
        _uncalled(
            db,
            owner,
            identity,
            token,
            preflight_error.code
            if isinstance(preflight_error, DomainError)
            else "PLANNING_PREFLIGHT_FAILED",
        )
        return _owned_job(db, owner, identity)
    # No original Session transaction or write lock survives into the model call.
    with Session(db.get_bind()) as final_check:
        before_call = _control(final_check, owner, request, token)
    if before_call is not None:
        _finish(
            db,
            owner,
            request,
            token,
            None,
            DomainError(
                "PLANNING_NOT_SUBMITTED",
                "Planning permission changed before provider invocation",
                409,
                details={"submitted": False},
            ),
        )
        return _owned_job(db, owner, identity)
    task = asyncio.create_task(selected.plan(request))
    response: PlanningResponse | None = None
    error: BaseException | None = None
    interrupted = False
    submission_started = monotonic()
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=POLL_SECONDS)
            with Session(db.get_bind()) as watch:
                reason = _control(watch, owner, request, token)
            if monotonic() - submission_started >= request.timeout_seconds + 30:
                reason = "PLANNING_REQUEST_TIMEOUT"
            if reason is not None and not task.done():
                interrupted = True
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), CANCEL_WAIT_SECONDS)
                except (asyncio.CancelledError, Exception):
                    pass
                break
        if task.done():
            try:
                response = task.result()
            except BaseException as observed:
                error = observed
        else:
            error = DomainError(
                "AI_OUTCOME_UNCERTAIN",
                "Provider stop was not confirmed; original attempt must be reconciled",
                503,
            )
            _retain_late(task, db, owner, request, token)
    except asyncio.CancelledError:
        interrupted = True
        task.cancel()
        with suppress(BaseException):
            await asyncio.wait_for(asyncio.shield(task), CANCEL_WAIT_SECONDS)
        if task.done():
            try:
                response = task.result()
            except BaseException as observed:
                error = observed
        else:
            error = DomainError(
                "AI_OUTCOME_UNCERTAIN",
                "Worker stopped before external completion was confirmed",
                503,
            )
            _retain_late(task, db, owner, request, token)
    _finish(db, owner, request, token, response, error, force_quarantine=interrupted)
    return _owned_job(db, owner, identity)
