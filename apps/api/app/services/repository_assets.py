"""Exact inventory consent and owner storage receipts; repository code is never executed."""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select, true, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import get_settings
from app.domain.repository_assets import (
    AssetInventory,
    AssetInventoryFile,
    AssetRemoteRef,
    RemoteAssetProvider,
    asset_inventory_sha256,
)
from app.errors import DomainError
from app.models import Attachment, ResearchEvent
from app.models_repositories import RepositoryBinding, RepositorySourceSnapshot
from app.models_repository_assets import (
    RepositoryAssetFile,
    RepositoryAssetJob,
    RepositoryAssetPlan,
    RepositoryAssetPlanFile,
    RepositoryAssetSnapshot,
)
from app.providers.registry import repository_asset_provider
from app.schemas_repository_assets import (
    AssetCapabilityOut,
    AssetEventOut,
    AssetFileOut,
    AssetJobOut,
    AssetPlanApprove,
    AssetPlanCreate,
    AssetPlanOut,
    AssetSnapshotChoiceOut,
    AssetSnapshotOut,
)
from app.services import repository_imports
from app.services.common import cursor_filter, decode_cursor, encode_cursor
from app.services.research_briefs import digest


def now() -> datetime:
    return datetime.now(UTC)


def list_snapshot_choices(
    db: Session, owner: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[AssetSnapshotChoiceOut], str | None]:
    """Persisted owner receipts only; selecting one does not probe or authorize a copy."""
    position: ColumnElement[bool] = true()
    if cursor is not None:
        _, identity = decode_cursor(cursor)
        # Compare the stored DB timestamp, including SQLite's legacy seconds-only
        # values, instead of rebinding it with a different fractional format.
        timestamp = (
            select(RepositoryAssetSnapshot.created_at)
            .where(RepositoryAssetSnapshot.id == identity, RepositoryAssetSnapshot.user_id == owner)
            .correlate(None)
            .scalar_subquery()
        )
        position = tuple_(RepositoryAssetSnapshot.created_at, RepositoryAssetSnapshot.id) < tuple_(
            timestamp, identity
        )
    rows = db.execute(
        select(RepositoryAssetSnapshot, RepositoryAssetPlan)
        .join(
            RepositoryAssetPlan,
            (RepositoryAssetPlan.id == RepositoryAssetSnapshot.plan_id)
            & (RepositoryAssetPlan.user_id == RepositoryAssetSnapshot.user_id),
        )
        .join(
            RepositoryAssetJob,
            (RepositoryAssetJob.id == RepositoryAssetSnapshot.job_id)
            & (RepositoryAssetJob.plan_id == RepositoryAssetSnapshot.plan_id)
            & (RepositoryAssetJob.user_id == RepositoryAssetSnapshot.user_id),
        )
        .where(
            RepositoryAssetSnapshot.user_id == owner,
            RepositoryAssetJob.status == "COMPLETED",
            RepositoryAssetSnapshot.stored_files > 0,
            position,
        )
        .order_by(RepositoryAssetSnapshot.created_at.desc(), RepositoryAssetSnapshot.id.desc())
        .limit(limit + 1)
    ).all()
    items = [
        AssetSnapshotChoiceOut(
            asset_snapshot_id=snapshot.id,
            job_id=snapshot.job_id,
            plan_id=snapshot.plan_id,
            source_snapshot_id=snapshot.source_snapshot_id,
            provider_key=plan.provider_key,
            repo_kind=plan.repo_kind,
            repo_id=plan.repo_id,
            commit_sha=plan.commit_sha,
            status=snapshot.status,
            stored_files=snapshot.stored_files,
            stored_bytes=snapshot.stored_bytes,
            gaps=json.loads(snapshot.gaps_text),
            created_at=snapshot.created_at,
        )
        for snapshot, plan in rows[:limit]
    ]
    return items, (
        encode_cursor(rows[limit - 1][0].created_at, rows[limit - 1][0].id)
        if len(rows) > limit
        else None
    )


def capability() -> AssetCapabilityOut:
    settings = get_settings()
    return AssetCapabilityOut(
        enabled=settings.repository_assets_enabled,
        max_bytes=settings.repository_asset_max_bytes,
        max_files=settings.repository_asset_max_files,
        detail="Only public pinned repository bytes are cached; no code execution, workspace checkout, model loading, training or baseline qualification.",
    )


def _enabled() -> None:
    if not get_settings().repository_assets_enabled:
        raise DomainError(
            "REPOSITORY_ASSETS_DISABLED",
            "Repository payload downloading is disabled on this host",
            503,
        )


def _source(
    db: Session, owner: uuid.UUID, identity: uuid.UUID
) -> tuple[RepositorySourceSnapshot, AssetRemoteRef, str | None]:
    source = db.scalar(
        select(RepositorySourceSnapshot)
        .where(RepositorySourceSnapshot.id == identity, RepositorySourceSnapshot.user_id == owner)
        .execution_options(populate_existing=True)
    )
    if source is None:
        raise DomainError("NOT_FOUND", "Owned confirmed repository source not found", 404)
    candidate = repository_imports._candidate(source)
    binding = db.scalar(
        select(RepositoryBinding)
        .where(
            RepositoryBinding.id == source.binding_id,
            RepositoryBinding.user_id == owner,
            RepositoryBinding.entity_id == source.entity_id,
        )
        .execution_options(populate_existing=True)
    )
    if (
        binding is None
        or (binding.provider_key, binding.repo_kind, binding.repo_id, binding.provider_id)
        != (candidate.provider_key, candidate.repo_kind, candidate.repo_id, candidate.provider_id)
        or source.commit_sha != candidate.commit_sha
        or not isinstance(source.commit_sha, str)
        or not re.fullmatch(r"[a-f0-9]{40}", source.commit_sha)
    ):
        raise DomainError(
            "ASSET_SOURCE_REVISION_INVALID",
            "Confirmed stable repository identity and exact commit are required",
            409,
        )
    return (
        source,
        AssetRemoteRef(
            candidate.provider_key,
            candidate.repo_kind,
            candidate.repo_id,
            candidate.provider_id,
            source.commit_sha,
        ),
        candidate.license_id,
    )


def _path(path: str) -> None:
    parsed = PurePosixPath(path)
    if (
        not path
        or len(path) > 2000
        or parsed.is_absolute()
        or parsed.as_posix() != path
        or "\\" in path
        or ":" in path
        or any(part in {".", ".."} for part in parsed.parts)
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
    ):
        raise DomainError(
            "ASSET_PATH_INVALID", "Inventory paths must be canonical relative repository paths", 409
        )


def get_plan(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> RepositoryAssetPlan:
    query = select(RepositoryAssetPlan).where(
        RepositoryAssetPlan.id == identity, RepositoryAssetPlan.user_id == owner
    )
    row = db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned asset plan not found", 404)
    return row


def get_job(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> RepositoryAssetJob:
    query = select(RepositoryAssetJob).where(
        RepositoryAssetJob.id == identity, RepositoryAssetJob.user_id == owner
    )
    row = db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned asset job not found", 404)
    return row


def plan_reference(plan: RepositoryAssetPlan) -> AssetRemoteRef:
    return AssetRemoteRef(
        plan.provider_key, plan.repo_kind, plan.repo_id, plan.provider_id, plan.commit_sha
    )


def file_remote(row: RepositoryAssetPlanFile) -> AssetInventoryFile:
    return TypeAdapter(AssetInventoryFile).validate_python(
        {
            "path": row.path,
            "kind": row.file_kind,
            "size_bytes": row.size_bytes,
            "digest_algorithm": row.digest_algorithm,
            "digest": row.digest,
            "supported": row.supported,
            "issue": row.issue,
        }
    )


def plan_files(db: Session, plan: RepositoryAssetPlan) -> list[RepositoryAssetPlanFile]:
    return list(
        db.scalars(
            select(RepositoryAssetPlanFile)
            .where(
                RepositoryAssetPlanFile.plan_id == plan.id,
                RepositoryAssetPlanFile.user_id == plan.user_id,
            )
            .order_by(RepositoryAssetPlanFile.path)
            .execution_options(populate_existing=True)
        )
    )


def plan_hash(plan: RepositoryAssetPlan, files: list[RepositoryAssetPlanFile]) -> str:
    fields = {
        key: getattr(plan, key)
        for key in (
            "id",
            "user_id",
            "source_snapshot_id",
            "source_snapshot_sha256",
            "provider_key",
            "repo_kind",
            "repo_id",
            "provider_id",
            "license_id",
            "commit_sha",
            "manifest_sha256",
            "total_files",
            "total_bytes",
            "selected_files",
            "selected_bytes",
            "max_bytes",
            "max_files",
            "scope",
            "inventory_complete",
            "gaps_text",
        )
    }
    return digest(
        {
            **fields,
            "files": [
                {
                    "path": row.path,
                    "file_key_sha256": row.file_key_sha256,
                    "selected": row.selected,
                    "remote_identity": row.remote_identity,
                }
                for row in sorted(files, key=lambda row: row.path)
            ],
        }
    )


def _validate_plan(db: Session, plan: RepositoryAssetPlan) -> None:
    source, reference, _ = _source(db, plan.user_id, plan.source_snapshot_id)
    files = plan_files(db, plan)
    inventory = AssetInventory(
        plan_reference(plan),
        tuple(file_remote(row) for row in files),
        plan.inventory_complete,
        tuple(json.loads(plan.gaps_text)),
    )
    if (
        reference != plan_reference(plan)
        or source.snapshot_sha256 != plan.source_snapshot_sha256
        or asset_inventory_sha256(inventory) != plan.manifest_sha256
        or plan_hash(plan, files) != plan.plan_sha256
        or not plan.inventory_complete
        or len(files) != plan.total_files
    ):
        raise DomainError(
            "ASSET_PLAN_CHANGED", "Frozen source inventory or selected file scope changed", 409
        )
    selected = [row for row in files if row.selected]
    if (
        len(selected) != plan.selected_files
        or not selected
        or sum(row.size_bytes or 0 for row in selected) != plan.selected_bytes
        or plan.selected_files > plan.max_files
        or plan.selected_bytes > plan.max_bytes
    ):
        raise DomainError(
            "ASSET_PLAN_LIMITS_INVALID",
            "Selected file inventory exceeds its exact consent limits",
            409,
        )
    for row in files:
        _path(row.path)
        if row.file_key_sha256 != digest({"path": row.path}) or row.remote_identity != row.path:
            raise DomainError("ASSET_PLAN_CHANGED", "Frozen relative file identity changed", 409)
        if row.selected and (
            not row.supported
            or row.file_kind not in {"REGULAR", "LFS"}
            or row.size_bytes is None
            or row.digest_algorithm is None
            or row.digest is None
            or not re.fullmatch(
                r"[a-f0-9]{40}" if row.digest_algorithm == "GIT_BLOB_SHA1" else r"[a-f0-9]{64}",
                row.digest,
            )
        ):
            raise DomainError(
                "ASSET_SELECTED_PAYLOAD_UNKNOWN",
                "Selected payload requires known type, byte size and remote digest",
                409,
            )


def validate_plan(db: Session, job: RepositoryAssetJob) -> RepositoryAssetPlan:
    _enabled()
    plan = get_plan(db, job.user_id, job.plan_id)
    _validate_plan(db, plan)
    settings = get_settings()
    if (
        plan.state != "APPROVED"
        or plan.approved_hash != plan.plan_sha256
        or plan.approved_by != job.user_id
        or plan.approved_at is None
    ):
        raise DomainError(
            "ASSET_PLAN_NOT_APPROVED",
            "The exact file scope has not been approved by its owner",
            409,
        )
    if (
        plan.max_bytes > settings.repository_asset_max_bytes
        or plan.max_files > settings.repository_asset_max_files
    ):
        raise DomainError(
            "ASSET_HOST_LIMIT_CHANGED",
            "Host asset limits changed; no new payload may be fetched",
            409,
        )
    return plan


async def create_plan(
    db: Session,
    owner: uuid.UUID,
    source_id: uuid.UUID,
    body: AssetPlanCreate,
    *,
    provider: RemoteAssetProvider | None = None,
) -> RepositoryAssetPlan:
    _enabled()
    source, reference, license_id = _source(db, owner, source_id)
    limits = capability()
    max_bytes = body.max_bytes or limits.max_bytes
    max_files = body.max_files or limits.max_files
    if max_bytes > limits.max_bytes or max_files > limits.max_files:
        raise DomainError(
            "ASSET_LIMIT_EXCEEDS_HOST", "Requested asset limits exceed configured host bounds", 422
        )
    inventory = await (provider or repository_asset_provider(reference.provider_key)).manifest(
        reference
    )
    if (
        inventory.ref != reference
        or not inventory.complete
        or len(inventory.files) > 10000
        or len({row.path for row in inventory.files}) != len(inventory.files)
    ):
        raise DomainError(
            "ASSET_INVENTORY_INCOMPLETE",
            "Only a complete bounded fixed-revision inventory can be approved",
            409,
        )
    explicit = set(body.selected_paths) if body.selected_paths is not None else None
    if explicit is not None and not explicit.issubset({row.path for row in inventory.files}):
        raise DomainError(
            "ASSET_PATH_NOT_IN_INVENTORY",
            "Selected paths are not in the complete frozen inventory",
            422,
        )
    plan = RepositoryAssetPlan(
        id=uuid.uuid4(),
        user_id=owner,
        source_snapshot_id=source_id,
        source_snapshot_sha256=source.snapshot_sha256,
        provider_key=reference.provider_key,
        repo_kind=reference.repo_kind,
        repo_id=reference.repo_id,
        provider_id=reference.provider_id,
        license_id=license_id,
        commit_sha=reference.commit_sha,
        manifest_sha256=asset_inventory_sha256(inventory),
        plan_sha256="0" * 64,
        total_files=len(inventory.files),
        total_bytes=sum(row.size_bytes for row in inventory.files if row.size_bytes is not None)
        if all(row.size_bytes is not None for row in inventory.files)
        else None,
        selected_files=0,
        selected_bytes=0,
        max_bytes=max_bytes,
        max_files=max_files,
        scope="SELECTED_SUBSET" if explicit is not None else "FULL_INVENTORY",
        inventory_complete=True,
        gaps_text=json.dumps(inventory.gaps),
        state="DRAFT",
        created_at=now(),
    )
    files = []
    for item in inventory.files:
        _path(item.path)
        chosen = (
            item.path in explicit
            if explicit is not None
            else item.supported and item.kind in {"REGULAR", "LFS"}
        )
        if chosen and (
            not item.supported
            or item.kind not in {"REGULAR", "LFS"}
            or item.size_bytes is None
            or item.digest is None
            or item.digest_algorithm is None
        ):
            raise DomainError(
                "ASSET_SELECTED_PAYLOAD_UNKNOWN",
                "Selected payload has unsupported type or unknown size/digest",
                409,
            )
        files.append(
            RepositoryAssetPlanFile(
                plan_id=plan.id,
                user_id=owner,
                file_key_sha256=digest({"path": item.path}),
                path=item.path,
                size_bytes=item.size_bytes,
                digest_algorithm=item.digest_algorithm,
                digest=item.digest,
                file_kind=item.kind,
                supported=item.supported,
                selected=chosen,
                issue=item.issue,
                remote_identity=item.path,
            )
        )
    plan.selected_files = sum(row.selected for row in files)
    plan.selected_bytes = sum(row.size_bytes or 0 for row in files if row.selected)
    if (
        not plan.selected_files
        or plan.selected_files > max_files
        or plan.selected_bytes > max_bytes
    ):
        raise DomainError(
            "ASSET_SELECTED_LIMIT_EXCEEDED",
            "Select a nonempty bounded set of supported payloads",
            422,
        )
    plan.plan_sha256 = plan_hash(plan, files)
    try:
        db.add(plan)
        db.flush()
        db.add_all(files)
        db.flush()
        _validate_plan(db, plan)
        db.commit()
    except (DomainError, ValidationError):
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "ASSET_INVENTORY_INVALID", "Inventory receipt violates the frozen file contract", 409
        ) from None
    db.refresh(plan)
    return plan


def event(db: Session, job: RepositoryAssetJob, kind: str, code: str | None = None) -> None:
    db.add(
        ResearchEvent(
            event_id=uuid.uuid4(),
            user_id=job.user_id,
            event_type="repository.asset." + kind.lower(),
            occurred_at=now(),
            source="repository-asset-worker",
            correlation_id=job.id,
            payload={
                "job_id": str(job.id),
                "plan_id": str(job.plan_id),
                "status": job.status,
                "code": code,
            },
        )
    )


def approve_plan(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, body: AssetPlanApprove
) -> RepositoryAssetPlan:
    plan = get_plan(db, owner, identity, lock=True)
    if body.expected_sha256 != plan.plan_sha256:
        raise DomainError(
            "ASSET_APPROVAL_HASH_CHANGED",
            "Review the exact inventory before approving payload download",
            409,
        )
    if plan.state == "APPROVED":
        return plan
    _enabled()
    _validate_plan(db, plan)
    try:
        plan.state, plan.approved_hash, plan.approved_by, plan.approved_at = (
            "APPROVED",
            plan.plan_sha256,
            owner,
            now(),
        )
        job = RepositoryAssetJob(
            id=uuid.uuid4(),
            user_id=owner,
            plan_id=plan.id,
            active_plan_id=plan.id,
            status="QUEUED",
            created_at=now(),
        )
        db.add(job)
        db.flush()
        event(db, job, "QUEUED")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "ASSET_APPROVAL_CONFLICT",
            "Another exact inventory approval already created its job",
            409,
        ) from None
    db.refresh(plan)
    return plan


def cancel_job(db: Session, owner: uuid.UUID, identity: uuid.UUID) -> RepositoryAssetJob:
    job = get_job(db, owner, identity, lock=True)
    if job.status == "QUEUED":
        job.status, job.active_plan_id, job.finished_at = "CANCELLED", None, now()
    elif job.status == "DOWNLOADING":
        job.status = "CANCEL_REQUESTED"
    event(db, job, "CANCEL_REQUESTED" if job.status == "CANCEL_REQUESTED" else "CANCEL_OBSERVED")
    db.commit()
    db.refresh(job)
    return job


def resume_job(db: Session, owner: uuid.UUID, identity: uuid.UUID) -> RepositoryAssetJob:
    job = get_job(db, owner, identity, lock=True)
    validate_plan(db, job)
    if job.status not in {"FAILED", "CANCELLED"} or job.lease_token is not None:
        raise DomainError(
            "ASSET_RESUME_NOT_AVAILABLE",
            "Only a confirmed failed/cancelled job without a live lease may resume",
            409,
        )
    job.status, job.active_plan_id, job.error_code, job.error_message, job.finished_at = (
        "QUEUED",
        job.plan_id,
        None,
        None,
        None,
    )
    try:
        event(db, job, "RESUMED")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "ASSET_JOB_ACTIVE", "Another active materialization already owns this plan", 409
        ) from None
    db.refresh(job)
    return job


def snapshot_manifest(
    db: Session, job: RepositoryAssetJob, verified_file_ids: list[uuid.UUID] | None = None
) -> dict[str, object]:
    snapshot = (
        db.scalar(
            select(RepositoryAssetSnapshot).where(
                RepositoryAssetSnapshot.job_id == job.id,
                RepositoryAssetSnapshot.plan_id == job.plan_id,
                RepositoryAssetSnapshot.user_id == job.user_id,
            )
        )
        if verified_file_ids is None
        else None
    )
    if verified_file_ids is None and snapshot is None:
        return {"job_id": str(job.id), "plan_id": str(job.plan_id), "files": []}
    if verified_file_ids is not None:
        membership: ColumnElement[bool] = RepositoryAssetFile.id.in_(verified_file_ids)
    else:
        assert snapshot is not None
        membership = RepositoryAssetFile.snapshot_id == snapshot.id
    rows = list(
        db.scalars(
            select(RepositoryAssetFile)
            .where(
                RepositoryAssetFile.job_id == job.id,
                RepositoryAssetFile.plan_id == job.plan_id,
                RepositoryAssetFile.user_id == job.user_id,
                RepositoryAssetFile.status == "STORED",
                membership,
            )
            .order_by(RepositoryAssetFile.created_at, RepositoryAssetFile.id)
        )
    )
    if verified_file_ids is not None and len(rows) != len(set(verified_file_ids)):
        raise DomainError(
            "ASSET_SNAPSHOT_REFERENCES_INVALID",
            "Snapshot receipts must be owned confirmed stored files",
            409,
        )
    if len({row.file_key_sha256 for row in rows}) != len(rows):
        raise DomainError(
            "ASSET_SNAPSHOT_REFERENCES_INVALID",
            "A measured snapshot selects one current receipt per source file",
            409,
        )
    for row in rows:
        attachment = db.scalar(
            select(Attachment).where(
                Attachment.id == row.attachment_id,
                Attachment.user_id == job.user_id,
                Attachment.deleted_at.is_(None),
            )
        )
        planned = db.scalar(
            select(RepositoryAssetPlanFile).where(
                RepositoryAssetPlanFile.plan_id == job.plan_id,
                RepositoryAssetPlanFile.user_id == job.user_id,
                RepositoryAssetPlanFile.file_key_sha256 == row.file_key_sha256,
            )
        )
        if (
            attachment is None
            or planned is None
            or not planned.selected
            or not row.remote_verified
            or (attachment.sha256, attachment.size_bytes)
            != (row.actual_sha256, row.actual_size_bytes)
        ):
            raise DomainError(
                "ASSET_SNAPSHOT_REFERENCES_INVALID",
                "Stored attachment identity differs from its approved verified source receipt",
                409,
            )
    latest = {row.file_key_sha256: row for row in rows}
    return {
        "job_id": str(job.id),
        "plan_id": str(job.plan_id),
        "files": [
            {
                "file_key_sha256": key,
                "receipt_id": str(row.id),
                "attachment_id": str(row.attachment_id),
                "sha256": row.actual_sha256,
                "size_bytes": row.actual_size_bytes,
            }
            for key, row in sorted(latest.items())
        ],
    }


def plan_out(db: Session, plan: RepositoryAssetPlan) -> AssetPlanOut:
    valid = True
    try:
        _validate_plan(db, plan)
    except (DomainError, ValidationError, ValueError, TypeError):
        valid = False
    initial = db.scalar(
        select(RepositoryAssetJob.id)
        .where(RepositoryAssetJob.plan_id == plan.id, RepositoryAssetJob.user_id == plan.user_id)
        .order_by(RepositoryAssetJob.created_at)
        .limit(1)
    )
    gaps = list(json.loads(plan.gaps_text))
    if plan.total_bytes is None:
        gaps.append("INVENTORY_TOTAL_BYTES_UNKNOWN")
    if plan.scope == "SELECTED_SUBSET":
        gaps.append("ONLY_EXPLICIT_SELECTED_SUBSET")
    if any(not row.supported for row in plan_files(db, plan)):
        gaps.append("UNSUPPORTED_INVENTORY_ENTRIES_NOT_MATERIALIZED")
    if not valid:
        gaps.append("FROZEN_PLAN_INVALID")
    fields = {
        key: getattr(plan, key)
        for key in AssetPlanOut.model_fields
        if key not in {"gaps", "initial_job_id", "can_approve", "execution_authorized"}
    }
    return AssetPlanOut(
        **fields,
        gaps=gaps,
        initial_job_id=initial,
        can_approve=valid and capability().enabled and plan.state == "DRAFT",
    )


def job_out(db: Session, job: RepositoryAssetJob) -> AssetJobOut:
    snapshot = db.scalar(
        select(RepositoryAssetSnapshot).where(
            RepositoryAssetSnapshot.job_id == job.id,
            RepositoryAssetSnapshot.plan_id == job.plan_id,
            RepositoryAssetSnapshot.user_id == job.user_id,
        )
    )
    fields = {
        key: getattr(job, key)
        for key in (
            "id",
            "plan_id",
            "status",
            "stored_files",
            "stored_bytes",
            "error_code",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
        )
    }
    snap = (
        AssetSnapshotOut.model_validate(
            {
                **{
                    key: getattr(snapshot, key)
                    for key in (
                        "id",
                        "status",
                        "manifest_sha256",
                        "stored_files",
                        "stored_bytes",
                        "created_at",
                    )
                },
                "gaps": json.loads(snapshot.gaps_text),
            }
        )
        if snapshot
        else None
    )
    resumable = False
    if job.status in {"FAILED", "CANCELLED"} and job.lease_token is None:
        try:
            validate_plan(db, job)
            resumable = True
        except (DomainError, ValidationError, ValueError, TypeError):
            pass
    return AssetJobOut(
        **fields,
        snapshot=snap,
        can_resume=resumable,
        can_cancel=job.status in {"QUEUED", "DOWNLOADING", "CANCEL_REQUESTED"},
    )


def files_out(
    db: Session, job: RepositoryAssetJob, limit: int = 20, cursor: str | None = None
) -> tuple[list[AssetFileOut], str | None]:
    rows = list(
        db.execute(
            select(RepositoryAssetFile, RepositoryAssetPlanFile.path)
            .join(
                RepositoryAssetPlanFile,
                (RepositoryAssetPlanFile.plan_id == RepositoryAssetFile.plan_id)
                & (RepositoryAssetPlanFile.file_key_sha256 == RepositoryAssetFile.file_key_sha256)
                & (RepositoryAssetPlanFile.user_id == RepositoryAssetFile.user_id),
            )
            .where(
                RepositoryAssetFile.job_id == job.id,
                RepositoryAssetFile.user_id == job.user_id,
                cursor_filter(RepositoryAssetFile, cursor),
            )
            .order_by(RepositoryAssetFile.created_at.desc(), RepositoryAssetFile.id.desc())
            .limit(limit + 1)
        )
    )
    next_cursor = (
        encode_cursor(rows[limit - 1][0].created_at, rows[limit - 1][0].id)
        if len(rows) > limit
        else None
    )
    output = []
    for row, path in rows[:limit]:
        owned = (
            db.scalar(
                select(Attachment.id).where(
                    Attachment.id == row.attachment_id,
                    Attachment.user_id == job.user_id,
                    Attachment.deleted_at.is_(None),
                )
            )
            if row.attachment_id
            else None
        )
        output.append(
            AssetFileOut(
                id=row.id,
                file_key_sha256=row.file_key_sha256,
                path=path,
                attachment_id=row.attachment_id if owned else None,
                status=row.status,
                actual_sha256=row.actual_sha256,
                actual_size_bytes=row.actual_size_bytes,
                remote_verified=row.remote_verified,
                error_code=row.error_code,
                created_at=row.created_at,
                download_url=f"/api/v1/attachments/{owned}/download"
                if owned and row.status in {"STORED", "QUARANTINED"}
                else None,
            )
        )
    return output, next_cursor


def events_out(db: Session, job: RepositoryAssetJob) -> list[AssetEventOut]:
    return [
        AssetEventOut(
            id=row.event_id,
            event_type=row.event_type,
            occurred_at=row.occurred_at,
            status=row.payload.get("status")
            if isinstance(row.payload.get("status"), str)
            else None,
            code=row.payload.get("code") if isinstance(row.payload.get("code"), str) else None,
        )
        for row in db.scalars(
            select(ResearchEvent)
            .where(
                ResearchEvent.user_id == job.user_id,
                ResearchEvent.correlation_id == job.id,
                ResearchEvent.event_type.like("repository.asset.%"),
            )
            .order_by(ResearchEvent.occurred_at, ResearchEvent.id)
        )
    ]


def list_plans(
    db: Session, owner: uuid.UUID, source_id: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[RepositoryAssetPlan], str | None]:
    _source(db, owner, source_id)
    rows = list(
        db.scalars(
            select(RepositoryAssetPlan)
            .where(
                RepositoryAssetPlan.user_id == owner,
                RepositoryAssetPlan.source_snapshot_id == source_id,
                cursor_filter(RepositoryAssetPlan, cursor),
            )
            .order_by(RepositoryAssetPlan.created_at.desc(), RepositoryAssetPlan.id.desc())
            .limit(limit + 1)
        )
    )
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None


def list_jobs(
    db: Session, owner: uuid.UUID, plan_id: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[RepositoryAssetJob], str | None]:
    get_plan(db, owner, plan_id)
    rows = list(
        db.scalars(
            select(RepositoryAssetJob)
            .where(
                RepositoryAssetJob.user_id == owner,
                RepositoryAssetJob.plan_id == plan_id,
                cursor_filter(RepositoryAssetJob, cursor),
            )
            .order_by(RepositoryAssetJob.created_at.desc(), RepositoryAssetJob.id.desc())
            .limit(limit + 1)
        )
    )
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None
