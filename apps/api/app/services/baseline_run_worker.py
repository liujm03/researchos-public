"""One-shot bounded execution, truthful stop evidence and retained candidate artifacts."""

import hashlib
import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.baseline_runs import (
    BaselineInputSeal,
    BaselineRunProvider,
    BaselineRunReceipt,
    BaselineRunRequest,
    run_command_sha256,
    run_container_name,
    run_input_manifest_sha256,
    run_request_sha256,
    run_verifier_command_sha256,
    run_volume_name,
)
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import Attachment, ModelVersion, ResearchEvent
from app.models_baseline_runs import (
    BaselineRunArtifact,
    BaselineRunAttempt,
    BaselineRunJob,
)
from app.services import baseline_runs as service
from app.services import baselines, project_sources

IDENTITY = re.compile(r"^[a-f0-9]{64}$")


def attempt(db: Session, job: BaselineRunJob) -> BaselineRunAttempt | None:
    return db.scalar(
        select(BaselineRunAttempt)
        .where(
            BaselineRunAttempt.job_id == job.id,
            BaselineRunAttempt.plan_id == job.plan_id,
            BaselineRunAttempt.version_id == job.version_id,
            BaselineRunAttempt.project_id == job.project_id,
            BaselineRunAttempt.user_id == job.user_id,
        )
        .execution_options(populate_existing=True)
    )


def terminal(job: BaselineRunJob, status: str, code: str | None = None) -> None:
    job.status = status
    job.error_code = code
    job.error_message = "执行已停止；真实日志和历史产物保留。" if code else None
    if status == "NEEDS_ATTENTION":
        job.error_message = "执行结果或停止状态尚未确认，请只读核查原容器。"
    else:
        job.active_owner_id = None
        job.finished_at = service.now()
    job.lease_token = None
    job.lease_expires_at = None


def recover_stale(db: Session, owner: uuid.UUID) -> BaselineRunJob | None:
    job = db.scalar(
        select(BaselineRunJob)
        .where(
            BaselineRunJob.user_id == owner,
            BaselineRunJob.status.in_(["STARTING", "RUNNING", "CANCEL_REQUESTED"]),
            BaselineRunJob.lease_expires_at <= service.now(),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if job is None:
        db.rollback()
        return None
    terminal(job, "NEEDS_ATTENTION", "BASELINE_RUN_LEASE_EXPIRED")
    previous = attempt(db, job)
    if previous is not None:
        previous.status = "NEEDS_ATTENTION"
    service.event(db, job, "NEEDS_ATTENTION", job.error_code)
    db.commit()
    return job


def claim(db: Session, owner: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    if (
        db.scalar(select(BaselineRunJob.id).where(BaselineRunJob.active_owner_id == owner))
        is not None
    ):
        db.rollback()
        return None
    job = db.scalar(
        select(BaselineRunJob)
        .where(BaselineRunJob.user_id == owner, BaselineRunJob.status == "QUEUED")
        .order_by(BaselineRunJob.created_at, BaselineRunJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if job is None:
        db.rollback()
        return None
    try:
        plan, _ = service.validate_job(db, job)
        token = uuid.uuid4()
        job.status = "STARTING"
        job.active_owner_id = owner
        job.lease_token = token
        job.lease_expires_at = service.now() + timedelta(seconds=plan.timeout_seconds + 120)
        job.started_at = service.now()
        service.event(db, job, "CLAIMED")
        db.commit()
        return job.id, token
    except IntegrityError:
        db.rollback()
        return None
    except DomainError as error:
        terminal(job, "FAILED", error.code)
        service.permit(db, job).state = "REVOKED"
        service.event(db, job, "FAILED", error.code)
        db.commit()
        return None


def check_fence(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
    request: BaselineRunRequest,
    *,
    full: bool = False,
) -> BaselineRunJob:
    job = service.get_job(db, owner, identity)
    if (
        job.lease_token != token
        or job.status not in {"STARTING", "RUNNING"}
        or job.lease_expires_at is None
        or service.utc(job.lease_expires_at) <= service.now()
    ):
        raise DomainError(
            "BASELINE_RUN_LEASE_LOST", "Current execution ownership is no longer active", 409
        )
    service.enabled()
    plan = service.get_plan(db, owner, job.plan_id)
    if (
        plan.state != "ACTIVE"
        or plan.approved_by != owner
        or plan.approved_sha256 != request.grant_sha256
        or plan.sha256 != request.grant_sha256
        or service.utc(plan.expires_at) <= service.now()
    ):
        raise DomainError(
            "BASELINE_RUN_GRANT_CHANGED", "Execution approval changed or expired", 409
        )
    if full:
        service.validate_job(db, job)
    else:
        version = baselines.get_version(db, owner, job.version_id)
        if version.sha256 != request.version_sha256:
            raise DomainError("BASELINE_RUN_VERSION_CHANGED", "Baseline version changed", 409)
        if version.model_version_id:
            model: ModelVersion = baselines._get(db, ModelVersion, owner, version.model_version_id)
            if baselines.model_hash(db, owner, model) != version.model_snapshot_sha256:
                raise DomainError("BASELINE_RUN_MODEL_CHANGED", "Model semantics changed", 409)
        for item in baselines.datasets(db, version):
            if (
                baselines.dataset_snapshot(db, owner, item.dataset_version_id)[2]
                != item.snapshot_sha256
            ):
                raise DomainError("BASELINE_RUN_DATASET_CHANGED", "Dataset semantics changed", 409)
        for source_id in {item.source_scope.plan_id for item in request.inputs}:
            source = project_sources.get_plan(db, owner, request.project_id, source_id)
            binding = project_sources.get_binding(
                db, owner, request.project_id, source.path_binding_id
            )
            if (
                binding.state != "ACTIVE"
                or binding.approved_by != owner
                or binding.approved_hash != binding.scope_sha256
            ):
                raise DomainError("BASELINE_RUN_SOURCE_REVOKED", "Source use was revoked", 409)
    return job


def begin_attempt(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, token: uuid.UUID, evidence: Any
) -> tuple[BaselineRunAttempt, BaselineRunRequest]:
    job = service.get_job(db, owner, identity, lock=True)
    plan, request = service.validate_job(db, job)
    check_fence(db, owner, identity, token, request, full=True)
    service.runtime_valid(plan, evidence)
    p = service.permit(db, job)
    if p.state != "RESERVED" or attempt(db, job) is not None:
        raise DomainError(
            "BASELINE_RUN_REPLAY_FORBIDDEN", "A started execution cannot be replayed", 409
        )
    p.state = "ISSUED"
    p.issued_at = service.now()
    p.expires_at = min(service.utc(plan.expires_at), service.now() + timedelta(seconds=60))
    db.commit()
    job = service.get_job(db, owner, identity, lock=True)
    check_fence(db, owner, identity, token, request, full=True)
    p = service.permit(db, job)
    if p.state != "ISSUED" or service.utc(p.expires_at) <= service.now():
        raise DomainError(
            "BASELINE_RUN_PERMIT_EXPIRED", "Short execution permit expired before submission", 409
        )
    a = BaselineRunAttempt(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=job.project_id,
        version_id=job.version_id,
        plan_id=job.plan_id,
        job_id=job.id,
        permit_id=p.id,
        permit_nonce=p.nonce,
        status="STARTED",
        image_id=request.image_id,
        daemon_id=request.daemon_id,
        input_sealed=False,
        input_seal_payload=None,
        issues_text="[]",
        began_at=service.now(),
    )
    db.add(a)
    p.state = "STARTED"
    job.status = "RUNNING"
    service.event(db, job, "STARTED")
    db.commit()
    db.refresh(a)
    return a, request


def valid_receipt(receipt: BaselineRunReceipt, request: BaselineRunRequest) -> bool:
    if (
        not isinstance(receipt, BaselineRunReceipt)
        or receipt.job_id != request.job_id
        or receipt.container_name != run_container_name(request)
        or receipt.image_id != request.image_id
        or receipt.daemon_id != request.daemon_id
        or receipt.command_sha256 != run_command_sha256(request)
        or receipt.scientific_qualification != "NOT_GRANTED"
    ):
        return False
    if receipt.status not in {
        "EXITED",
        "CANCELLED",
        "TIMED_OUT",
        "LIMIT_EXCEEDED",
        "QUARANTINED",
        "UNKNOWN",
        "REJECTED",
    }:
        return False
    if receipt.container_id is not None and (
        not isinstance(receipt.container_id, str)
        or IDENTITY.fullmatch(receipt.container_id) is None
    ):
        return False
    if (
        receipt.input_manifest_sha256 is not None
        and receipt.input_manifest_sha256 != run_input_manifest_sha256(request)
    ):
        return False
    if (
        type(receipt.container_stopped) not in {bool, type(None)}
        or type(receipt.input_sealed) is not bool
        or type(receipt.retained) is not bool
    ):
        return False
    if receipt.exit_code is not None and type(receipt.exit_code) is not int:
        return False
    if (
        not isinstance(receipt.logs, str)
        or len(receipt.logs.encode("utf-8")) > request.limits.max_log_bytes
    ):
        return False
    if (
        not isinstance(receipt.began_at, datetime)
        or receipt.began_at.utcoffset() is None
        or not isinstance(receipt.ended_at, datetime)
        or receipt.ended_at.utcoffset() is None
        or receipt.ended_at < receipt.began_at
    ):
        return False
    if (
        not isinstance(receipt.issues, tuple)
        or len(receipt.issues) > 1000
        or any(not isinstance(item, str) or len(item) > 2400 for item in receipt.issues)
    ):
        return False
    if (
        not isinstance(receipt.artifacts, tuple)
        or len(receipt.artifacts) > request.limits.max_output_files + 1
    ):
        return False
    seen = set()
    total = 0
    output_files = 0
    for artifact in receipt.artifacts:
        if (
            not isinstance(artifact.path, str)
            or len(artifact.path) > 2000
            or artifact.path.startswith("/")
            or "\\" in artifact.path
            or any(part in {"", ".", ".."} for part in artifact.path.split("/"))
            or artifact.path in seen
            or artifact.path != "stdout.log"
            and not artifact.path.startswith("output/")
            or not isinstance(artifact.sha256, str)
            or IDENTITY.fullmatch(artifact.sha256) is None
            or type(artifact.size_bytes) is not int
            or artifact.size_bytes < 0
        ):
            return False
        seen.add(artifact.path)
        if artifact.path == "stdout.log":
            if artifact.size_bytes > request.limits.max_log_bytes:
                return False
        else:
            total += artifact.size_bytes
            output_files += 1
    if total > request.limits.max_output_bytes or output_files > request.limits.max_output_files:
        return False
    if receipt.input_sealed:
        proof = receipt.input_seal
        if (
            not isinstance(proof, BaselineInputSeal)
            or proof.volume_name != run_volume_name(request)
            or proof.manifest_sha256 != run_input_manifest_sha256(request)
            or proof.verifier_image_id != request.image_id
            or proof.verifier_command_sha256 != run_verifier_command_sha256(request)
            or proof.helper_removed is not True
            or proof.mounted_readonly is not True
            or IDENTITY.fullmatch(proof.helper_container_id) is None
            or receipt.container_id is None
        ):
            return False
    return True


async def save_artifacts(
    db: Session,
    owner: uuid.UUID,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    request: BaselineRunRequest,
    receipt: BaselineRunReceipt,
    provider: BaselineRunProvider,
    storage: StorageProvider,
    *,
    quarantined: bool,
    recovery: bool = False,
) -> bool:
    all_saved = True
    for artifact in receipt.artifacts:
        job = service.get_job(db, owner, job_id)
        existing = db.scalar(
            select(BaselineRunArtifact).where(
                BaselineRunArtifact.attempt_id == attempt_id,
                BaselineRunArtifact.user_id == owner,
                BaselineRunArtifact.path == artifact.path,
                BaselineRunArtifact.disposition != "UNAVAILABLE",
            )
        )
        if existing is not None:
            attachment = db.scalar(
                select(Attachment).where(
                    Attachment.id == existing.attachment_id,
                    Attachment.user_id == owner,
                    Attachment.deleted_at.is_(None),
                )
            )
            if attachment is not None and (attachment.sha256, attachment.size_bytes) == (
                artifact.sha256,
                artifact.size_bytes,
            ):
                key = attachment.object_key
                db.rollback()
                try:
                    digest = hashlib.sha256()
                    size = 0
                    async for chunk in storage.load(key):
                        size += len(chunk)
                        if size > artifact.size_bytes:
                            break
                        digest.update(chunk)
                    if (digest.hexdigest(), size) == (artifact.sha256, artifact.size_bytes):
                        continue
                except Exception:
                    pass
        db.rollback()
        stored = None
        try:
            stored = await storage.save(
                provider.open_artifact(request, artifact.path),
                mime_type="application/octet-stream",
                max_bytes=max(1, artifact.size_bytes),
                allow_empty=True,
            )
            if (stored.sha256, stored.size_bytes) != (artifact.sha256, artifact.size_bytes):
                raise DomainError(
                    "BASELINE_RUN_ARTIFACT_CHANGED",
                    "Output bytes do not match their observed receipt",
                    409,
                )
            job = service.get_job(db, owner, job_id)
            current = attempt(db, job)
            if current is None or current.id != attempt_id:
                raise DomainError(
                    "BASELINE_RUN_ATTEMPT_CHANGED", "Original attempt identity changed", 409
                )
            attachment = Attachment(
                id=uuid.uuid4(),
                user_id=owner,
                storage_provider=storage.provider_key,
                object_key=stored.key,
                original_filename=PurePosixPath(artifact.path).name[:300],
                mime_type="application/octet-stream",
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
            )
            db.add(attachment)
            db.flush()
            disposition = (
                "QUARANTINED"
                if quarantined or job.status != "RUNNING" and not recovery
                else "AVAILABLE"
            )
            db.add(
                BaselineRunArtifact(
                    id=uuid.uuid4(),
                    user_id=owner,
                    project_id=job.project_id,
                    version_id=job.version_id,
                    plan_id=job.plan_id,
                    job_id=job.id,
                    attempt_id=attempt_id,
                    attachment_id=attachment.id,
                    path=artifact.path,
                    sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                    disposition=disposition,
                    created_at=service.now(),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            all_saved = False
            if stored is not None:
                try:
                    await storage.delete(stored.key)
                except Exception:
                    pass
            job = service.get_job(db, owner, job_id)
            if not db.scalar(
                select(BaselineRunArtifact.id).where(
                    BaselineRunArtifact.attempt_id == attempt_id,
                    BaselineRunArtifact.user_id == owner,
                    BaselineRunArtifact.path == artifact.path,
                )
            ):
                db.add(
                    BaselineRunArtifact(
                        id=uuid.uuid4(),
                        user_id=owner,
                        project_id=job.project_id,
                        version_id=job.version_id,
                        plan_id=job.plan_id,
                        job_id=job.id,
                        attempt_id=attempt_id,
                        attachment_id=None,
                        path=artifact.path,
                        sha256=artifact.sha256,
                        size_bytes=artifact.size_bytes,
                        disposition="UNAVAILABLE",
                        created_at=service.now(),
                    )
                )
                db.commit()
    return all_saved


async def record_receipt(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID | None,
    attempt_id: uuid.UUID,
    request: BaselineRunRequest,
    receipt: BaselineRunReceipt,
    provider: BaselineRunProvider,
    storage: StorageProvider,
) -> BaselineRunJob:
    job = service.get_job(db, owner, identity, lock=True)
    a = attempt(db, job)
    if a is None or a.id != attempt_id:
        raise DomainError(
            "BASELINE_RUN_ATTEMPT_CHANGED", "Original execution attempt is unavailable", 409
        )
    if not valid_receipt(receipt, request):
        if job.lease_token == token and job.status not in {
            "COMPLETED_CANDIDATE",
            "FAILED",
            "CANCELLED",
        }:
            terminal(job, "NEEDS_ATTENTION", "BASELINE_RUN_RECEIPT_INVALID")
            a.status = "NEEDS_ATTENTION"
            service.event(db, job, "RECEIPT_INVALID", job.error_code)
            db.commit()
        return job
    recovery = job.status == "FAILED" and job.error_code == "BASELINE_RUN_ARTIFACT_BACKUP_FAILED"
    original_terminal = (
        job.status in {"COMPLETED_CANDIDATE", "FAILED", "CANCELLED"} and not recovery
    )
    scope_valid = True
    try:
        service.validate_job(db, job, active=not recovery)
        recovery_plan = service.get_plan(db, owner, job.plan_id)
        if recovery and (
            recovery_plan.state != "ACTIVE"
            or recovery_plan.approved_sha256 != request.grant_sha256
            or service.utc(recovery_plan.expires_at) <= service.now()
        ):
            scope_valid = False
    except DomainError:
        scope_valid = False
    lease_valid = (
        token is not None
        and job.lease_token == token
        and job.lease_expires_at is not None
        and service.utc(job.lease_expires_at) > service.now()
    )
    cancelled = (
        job.status == "CANCEL_REQUESTED"
        or service.get_plan(db, owner, job.plan_id).state == "REVOKED"
    )
    quarantine = (
        original_terminal
        or not scope_valid
        or cancelled
        or token is not None
        and not lease_valid
        or receipt.status in {"QUARANTINED", "UNKNOWN"}
    )
    if not original_terminal and lease_valid:
        a.container_id = receipt.container_id or a.container_id
        a.container_name = receipt.container_name
        a.command_sha256 = receipt.command_sha256
        a.input_manifest_sha256 = receipt.input_manifest_sha256
        a.exit_code = receipt.exit_code
        a.container_stopped = receipt.container_stopped
        a.input_sealed = receipt.input_sealed
        a.input_seal_payload = (
            service.json_value(asdict(receipt.input_seal)) if receipt.input_seal else None
        )
        a.logs = receipt.logs
        a.receipt_status = receipt.status
        a.issues_text = json.dumps(list(receipt.issues))
        a.ended_at = service.utc(receipt.ended_at)
    else:
        db.add(
            ResearchEvent(
                event_id=uuid.uuid4(),
                user_id=owner,
                event_type="baseline.run.late_receipt",
                occurred_at=service.now(),
                source="baseline-run-worker",
                correlation_id=job.id,
                payload={
                    "job_id": str(job.id),
                    "status": job.status,
                    "code": "BASELINE_RUN_LATE_RECEIPT_QUARANTINED",
                    "receipt": service.json_value(asdict(receipt)),
                },
            )
        )
    db.commit()
    backed_up = await save_artifacts(
        db,
        owner,
        identity,
        attempt_id,
        request,
        receipt,
        provider,
        storage,
        quarantined=quarantine,
        recovery=recovery,
    )
    job = service.get_job(db, owner, identity, lock=True)
    a = attempt(db, job)
    if original_terminal or token is not None and job.lease_token != token:
        db.rollback()
        return job
    # Recheck authority after output backup; the I/O step cannot revive revoked scope.
    try:
        service.validate_job(db, job, active=not recovery)
    except DomainError:
        scope_valid = False
    if a is None or a.id != attempt_id:
        db.rollback()
        return job
    cancelled = (
        cancelled
        or job.status == "CANCEL_REQUESTED"
        or service.get_plan(db, owner, job.plan_id).state == "REVOKED"
    )
    if receipt.container_stopped is not True or receipt.status == "UNKNOWN":
        terminal(job, "NEEDS_ATTENTION", "BASELINE_RUN_OUTCOME_UNKNOWN")
    elif cancelled:
        terminal(job, "CANCELLED", "BASELINE_RUN_CANCELLED")
    elif not scope_valid or quarantine:
        terminal(job, "FAILED", "BASELINE_RUN_SCOPE_CHANGED")
    elif (
        receipt.status == "EXITED"
        and receipt.exit_code == 0
        and any(artifact.path.startswith("output/") for artifact in receipt.artifacts)
        and receipt.input_sealed
        and receipt.input_manifest_sha256 == run_input_manifest_sha256(request)
        and backed_up
    ):
        terminal(job, "COMPLETED_CANDIDATE")
    else:
        terminal(
            job,
            "FAILED",
            "BASELINE_RUN_EXECUTION_FAILED" if backed_up else "BASELINE_RUN_ARTIFACT_BACKUP_FAILED",
        )
    a.status = job.status if job.status != "CANCEL_REQUESTED" else "NEEDS_ATTENTION"
    if job.status != "COMPLETED_CANDIDATE":
        for artifact in db.scalars(
            select(BaselineRunArtifact).where(
                BaselineRunArtifact.job_id == identity,
                BaselineRunArtifact.user_id == owner,
                BaselineRunArtifact.disposition == "AVAILABLE",
            )
        ):
            artifact.disposition = "QUARANTINED"
    service.event(db, job, "OUTCOME_RECORDED", job.error_code)
    db.commit()
    db.refresh(job)
    return job


async def process_next(
    db: Session,
    owner: uuid.UUID,
    provider: BaselineRunProvider | None = None,
    storage: StorageProvider | None = None,
) -> BaselineRunJob | None:
    stale = recover_stale(db, owner)
    if stale is not None:
        return stale
    from app.domain.research_execution_policy import local_research_execution_allowed

    if not local_research_execution_allowed():
        return None
    if not get_settings().baseline_runner_enabled:
        return None
    claimed = claim(db, owner)
    if claimed is None:
        return None
    identity, token = claimed
    adapter = provider or service.provider_port()
    if storage is None:
        from app.providers.registry import storage_provider

        storage = storage_provider()
    started = None
    request = None
    try:
        evidence = await adapter.runtime()
        started, request = begin_attempt(db, owner, identity, token, evidence)
        attempt_id = started.id
        db.rollback()

        async def on_created(container_id: str, container_name: str) -> None:
            if IDENTITY.fullmatch(container_id) is None or container_name != run_container_name(
                request
            ):
                raise DomainError(
                    "BASELINE_RUN_CONTAINER_INVALID",
                    "Actual container identity does not match the frozen request",
                    502,
                )
            with Session(db.get_bind()) as checkpoint:
                job = check_fence(checkpoint, owner, identity, token, request)
                a = attempt(checkpoint, job)
                if a is None or a.id != attempt_id:
                    raise DomainError(
                        "BASELINE_RUN_ATTEMPT_CHANGED", "Original attempt changed", 409
                    )
                a.container_id = container_id
                a.container_name = container_name
                service.event(checkpoint, job, "CONTAINER_CREATED")
                checkpoint.commit()

        async def cancellation() -> bool:
            with Session(db.get_bind()) as watcher:
                try:
                    check_fence(watcher, owner, identity, token, request)
                    return False
                except DomainError:
                    return True

        receipt = await adapter.execute(
            request, on_created=on_created, cancel_requested=cancellation
        )
        return await record_receipt(
            db, owner, identity, token, attempt_id, request, receipt, adapter, storage
        )
    except Exception:
        db.rollback()
        job = service.get_job(db, owner, identity, lock=True)
        if job.lease_token != token:
            db.rollback()
            return job
        current = attempt(db, job)
        if current is None:
            terminal(
                job,
                "CANCELLED" if job.status == "CANCEL_REQUESTED" else "FAILED",
                "BASELINE_RUN_CANCELLED_BEFORE_SUBMISSION"
                if job.status == "CANCEL_REQUESTED"
                else "BASELINE_RUN_PREFLIGHT_FAILED",
            )
            service.permit(db, job).state = "REVOKED"
        else:
            terminal(job, "NEEDS_ATTENTION", "BASELINE_RUN_PROVIDER_OUTCOME_UNKNOWN")
            current.status = "NEEDS_ATTENTION"
        service.event(db, job, "NEEDS_ATTENTION" if current else "FAILED", job.error_code)
        db.commit()
        db.refresh(job)
        return job


async def reconcile_job(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    *,
    provider: BaselineRunProvider | None = None,
    storage: StorageProvider | None = None,
    stop: bool = False,
) -> BaselineRunJob:
    job = service.get_job(db, owner, identity, lock=True)
    if (
        job.status != "NEEDS_ATTENTION"
        and not (job.status == "FAILED" and job.error_code == "BASELINE_RUN_ARTIFACT_BACKUP_FAILED")
    ) or job.lease_token is not None:
        raise DomainError(
            "BASELINE_RUN_RECONCILE_UNAVAILABLE",
            "Only an unowned uncertain execution may be inspected",
            409,
        )
    a = attempt(db, job)
    if a is None:
        terminal(
            job,
            "CANCELLED" if stop else "FAILED",
            "BASELINE_RUN_CANCELLED_BEFORE_SUBMISSION" if stop else "BASELINE_RUN_NOT_SUBMITTED",
        )
        service.permit(db, job).state = "REVOKED"
        service.event(db, job, "NOT_SUBMITTED")
        db.commit()
        return job
    request = service.request_decode(job.manifest_payload)
    reservation = service.permit(db, job)
    if (
        request.request_sha256 != job.manifest_sha256
        or run_request_sha256(request) != job.manifest_sha256
        or reservation.manifest_sha256 != job.manifest_sha256
        or (request.job_id, request.owner_id, request.project_id, request.version_id)
        != (job.id, job.user_id, job.project_id, job.version_id)
        or (a.image_id, a.daemon_id) != (request.image_id, request.daemon_id)
    ):
        raise DomainError(
            "BASELINE_RUN_MANIFEST_CHANGED", "Original execution receipt cannot be verified", 409
        )
    # A reconciliation lease fences concurrent readonly inspectors without authorizing a new execution.
    token = uuid.uuid4()
    job.lease_token = token
    job.lease_expires_at = service.now() + timedelta(seconds=120)
    attempt_id = a.id
    container = a.container_id or run_container_name(request)
    if stop:
        job.status = "CANCEL_REQUESTED"
        service.event(db, job, "UNKNOWN_CANCEL_REQUESTED")
    db.commit()
    try:
        adapter = provider or service.provider_port()
        if storage is None:
            from app.providers.registry import storage_provider

            storage = storage_provider()
        receipt = (
            await adapter.cancel(request, container)
            if stop
            else await adapter.inspect(request, container)
        )
        return await record_receipt(
            db, owner, identity, token, attempt_id, request, receipt, adapter, storage
        )
    except Exception:
        db.rollback()
        job = service.get_job(db, owner, identity, lock=True)
        if job.lease_token == token:
            terminal(job, "NEEDS_ATTENTION", "BASELINE_RUN_INSPECTION_UNAVAILABLE")
            service.event(db, job, "INSPECTION_UNAVAILABLE")
            db.commit()
        return job
