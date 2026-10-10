"""Measured owner asset checkpoints; public download never executes repository code."""

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.repository_assets import (
    AssetInventoryFile,
    RemoteAssetProvider,
    asset_inventory_sha256,
)
from app.domain.storage import StorageProvider, StoredObject
from app.errors import DomainError
from app.models import Attachment
from app.models_repository_assets import (
    RepositoryAssetFile,
    RepositoryAssetJob,
    RepositoryAssetPlan,
    RepositoryAssetPlanFile,
    RepositoryAssetSnapshot,
)
from app.services import repository_assets as policy

LEASE_SECONDS = 300
POLL_SECONDS = 1.0
INDEX_MAX_BYTES = 2 * 1024 * 1024


def now() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _job(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> RepositoryAssetJob | None:
    query = select(RepositoryAssetJob).where(
        RepositoryAssetJob.id == identity, RepositoryAssetJob.user_id == owner
    )
    return db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )


def _terminal(job: RepositoryAssetJob, status: str, code: str | None = None) -> None:
    job.status, job.error_code = status, code
    job.error_message = (
        "Asset operation stopped; measured prior checkpoints are retained" if code else None
    )
    job.finished_at = now()
    if status != "NEEDS_ATTENTION":
        job.active_plan_id = None
        job.lease_token = job.lease_expires_at = None


async def _await_save(
    operation: Coroutine[Any, Any, StoredObject],
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
) -> StoredObject:
    task = asyncio.create_task(operation)
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=POLL_SECONDS)
            if not task.done():
                with Session(db.get_bind()) as watch:
                    try:
                        _check(watch, owner, identity, token, renew=True)
                    except DomainError:
                        task.cancel()
                        try:
                            # A conforming StorageProvider cleans its own temporary
                            # object; a late complete receipt is retained by caller.
                            return await task
                        except asyncio.CancelledError:
                            raise DomainError(
                                "ASSET_SCOPE_CHANGED",
                                "Asset save was cancelled before a receipt was returned",
                                409,
                            ) from None
        return task.result()
    except asyncio.CancelledError:
        task.cancel()
        try:
            return await task
        except asyncio.CancelledError:
            raise DomainError(
                "ASSET_STORAGE_OUTCOME_UNKNOWN",
                "Storage stop did not return a locatable receipt",
                503,
            ) from None


def recover_stale(db: Session, owner: uuid.UUID) -> RepositoryAssetJob | None:
    row = db.scalar(
        select(RepositoryAssetJob)
        .where(
            RepositoryAssetJob.user_id == owner,
            RepositoryAssetJob.status.in_(("DOWNLOADING", "CANCEL_REQUESTED")),
            or_(
                RepositoryAssetJob.lease_token.is_(None),
                RepositoryAssetJob.lease_expires_at <= now(),
            ),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if row is None:
        db.rollback()
        return None
    _terminal(
        row, "CANCELLED" if row.status == "CANCEL_REQUESTED" else "FAILED", "ASSET_LEASE_EXPIRED"
    )
    db.commit()
    return row


def _claim(db: Session, owner: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    row = db.scalar(
        select(RepositoryAssetJob)
        .where(RepositoryAssetJob.user_id == owner, RepositoryAssetJob.status == "QUEUED")
        .order_by(RepositoryAssetJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if row is None:
        db.rollback()
        return None
    try:
        policy.validate_plan(db, row)
        token = uuid.uuid4()
        row.status, row.lease_token = "DOWNLOADING", token
        row.lease_expires_at, row.started_at = now() + timedelta(seconds=LEASE_SECONDS), now()
        row.stored_files, row.stored_bytes = 0, 0
        identity = row.id
        db.commit()
        return identity, token
    except IntegrityError:
        db.rollback()
        return None
    except DomainError as error:
        _terminal(row, "FAILED", error.code)
        db.commit()
        return None


def _check(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, token: uuid.UUID, *, renew: bool = False
) -> tuple[RepositoryAssetJob, RepositoryAssetPlan]:
    row = _job(db, owner, identity, lock=renew)
    if (
        row is None
        or row.lease_token != token
        or row.status != "DOWNLOADING"
        or row.lease_expires_at is None
        or utc(row.lease_expires_at) <= now()
    ):
        raise DomainError(
            "ASSET_SCOPE_CHANGED", "Asset claim was cancelled or its lease changed", 409
        )
    plan = policy.validate_plan(db, row)
    if renew:
        row.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        db.commit()
    return row, plan


async def _stored_valid(
    db: Session,
    owner: uuid.UUID,
    row: RepositoryAssetFile,
    file: RepositoryAssetPlanFile,
    storage: StorageProvider,
) -> bool:
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == row.attachment_id,
            Attachment.user_id == owner,
            Attachment.deleted_at.is_(None),
        )
    )
    if (
        attachment is None
        or attachment.storage_provider != storage.provider_key
        or row.actual_sha256 != attachment.sha256
        or row.actual_size_bytes != attachment.size_bytes
        or attachment.size_bytes != file.size_bytes
    ):
        return False
    try:
        reader = await storage.open(attachment.object_key)
        try:
            if reader.size_bytes != attachment.size_bytes:
                return False
            digest, size = hashlib.sha256(), 0
            async for chunk in reader.iter_bytes():
                size += len(chunk)
                if size > attachment.size_bytes:
                    return False
                digest.update(chunk)
            return (size, digest.hexdigest()) == (attachment.size_bytes, attachment.sha256)
        finally:
            await reader.close()
    except DomainError:
        return False


def _store_receipt(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
    file: RepositoryAssetPlanFile,
    checkpoint_id: uuid.UUID,
    stored: StoredObject,
    storage: StorageProvider,
    expected_sha: str,
    expected_size: int,
) -> RepositoryAssetFile:
    job = _job(db, owner, identity, lock=True)
    if job is None:
        raise DomainError("ASSET_SCOPE_CHANGED", "Owned asset job no longer exists", 409)
    valid = (
        job.lease_token == token
        and job.status == "DOWNLOADING"
        and job.lease_expires_at is not None
        and utc(job.lease_expires_at) > now()
    )
    if valid:
        try:
            policy.validate_plan(db, job)
        except DomainError:
            valid = False
    if (stored.sha256, stored.size_bytes) != (expected_sha, expected_size):
        valid = False
    existing = db.scalar(select(Attachment).where(Attachment.object_key == stored.key))
    if existing is not None and (
        existing.user_id != owner
        or existing.sha256 != expected_sha
        or existing.size_bytes != expected_size
    ):
        raise DomainError(
            "ASSET_STORAGE_RECEIPT_CONFLICT",
            "Storage key belongs to a different existing receipt",
            409,
        )
    attachment = existing
    if attachment is None:
        attachment = Attachment(
            id=uuid.uuid4(),
            user_id=owner,
            storage_provider=storage.provider_key,
            object_key=stored.key,
            original_filename=PurePosixPath(file.path).name[:300],
            mime_type="application/octet-stream",
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )
        db.add(attachment)
        db.flush()
    checkpoint = db.scalar(
        select(RepositoryAssetFile).where(
            RepositoryAssetFile.id == checkpoint_id,
            RepositoryAssetFile.user_id == owner,
            RepositoryAssetFile.job_id == identity,
        )
    )
    if checkpoint is None or checkpoint.status != "STORING":
        raise DomainError(
            "ASSET_CHECKPOINT_CHANGED", "The original asset checkpoint no longer matches", 409
        )
    checkpoint.attachment_id, checkpoint.actual_sha256, checkpoint.actual_size_bytes = (
        attachment.id,
        stored.sha256,
        stored.size_bytes,
    )
    checkpoint.remote_verified = (stored.sha256, stored.size_bytes) == (expected_sha, expected_size)
    checkpoint.status = "STORED" if valid else "QUARANTINED"
    checkpoint.error_code = None if valid else "ASSET_QUARANTINED"
    if valid:
        job.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    return checkpoint


def _progress(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
    verified: dict[str, RepositoryAssetFile],
) -> None:
    job = _job(db, owner, identity, lock=True)
    if job is None or job.lease_token != token or job.status != "DOWNLOADING":
        db.rollback()
        raise DomainError(
            "ASSET_SCOPE_CHANGED", "Asset progress no longer belongs to this claim", 409
        )
    job.stored_files = len(verified)
    job.stored_bytes = sum(row.actual_size_bytes or 0 for row in verified.values())
    db.commit()


async def _shard_gaps(
    storage: StorageProvider,
    db: Session,
    owner: uuid.UUID,
    files: list[RepositoryAssetPlanFile],
    verified: dict[str, RepositoryAssetFile],
) -> list[str]:
    gaps = []
    inventory = {file.path for file in files}
    for file in files:
        if (
            not (
                file.path.endswith(".safetensors.index.json")
                or PurePosixPath(file.path).name == "pytorch_model.bin.index.json"
            )
            or file.path not in verified
        ):
            continue
        row = verified[file.path]
        attachment = db.scalar(
            select(Attachment).where(
                Attachment.id == row.attachment_id, Attachment.user_id == owner
            )
        )
        if attachment is None or attachment.size_bytes > INDEX_MAX_BYTES:
            gaps.append("SHARD_INDEX_UNVERIFIED:" + file.path)
            continue
        raw = bytearray()
        async for chunk in storage.load(attachment.object_key):
            if len(raw) + len(chunk) > INDEX_MAX_BYTES:
                break
            raw.extend(chunk)
        try:
            value = json.loads(raw)
            weight_map = value.get("weight_map") if isinstance(value, dict) else None
            if not isinstance(weight_map, dict):
                raise ValueError("weight map")
            for name in weight_map.values():
                if (
                    not isinstance(name, str)
                    or not name
                    or name.startswith("/")
                    or ".." in PurePosixPath(name).parts
                    or ":" in name
                    or "\\" in name
                ):
                    gaps.append("SHARD_REFERENCE_UNSAFE:" + file.path)
                    continue
                path = (PurePosixPath(file.path).parent / name).as_posix()
                if path not in inventory:
                    gaps.append("SHARD_NOT_IN_INVENTORY:" + path)
                elif path not in verified:
                    gaps.append("SHARD_NOT_STORED:" + path)
        except (ValueError, UnicodeError, RecursionError):
            gaps.append("SHARD_INDEX_INVALID:" + file.path)
    return sorted(set(gaps))


async def process_next(
    db: Session,
    owner: uuid.UUID,
    remote: RemoteAssetProvider | None = None,
    storage: StorageProvider | None = None,
) -> RepositoryAssetJob | None:
    recovered = recover_stale(db, owner)
    if recovered is not None:
        return recovered
    if not get_settings().repository_assets_enabled:
        db.rollback()
        return None
    claimed = _claim(db, owner)
    if claimed is None:
        return None
    identity, token = claimed
    verified: dict[str, RepositoryAssetFile] = {}
    try:
        job, plan = _check(db, owner, identity, token)
        from app.providers.registry import repository_asset_provider, storage_provider

        selected_remote = (
            remote if remote is not None else repository_asset_provider(plan.provider_key)
        )
        selected_storage = storage if storage is not None else storage_provider()
        reference = policy.plan_reference(plan)
        files = policy.plan_files(db, plan)
        plan_hash, manifest_hash = plan.plan_sha256, plan.manifest_sha256
        scope, source, max_bytes = plan.scope, plan.source_snapshot_id, plan.max_bytes
        inventory_complete, declared_gaps = plan.inventory_complete, json.loads(plan.gaps_text)
        db.rollback()
        inventory = await selected_remote.manifest(reference)
        if asset_inventory_sha256(inventory) != manifest_hash or not inventory.complete:
            raise DomainError(
                "ASSET_SOURCE_CHANGED",
                "Fixed remote inventory differs from the approved manifest",
                409,
            )
        for file in files:
            _check(db, owner, identity, token, renew=True)
            rows = list(
                db.scalars(
                    select(RepositoryAssetFile)
                    .where(
                        RepositoryAssetFile.job_id == identity,
                        RepositoryAssetFile.user_id == owner,
                        RepositoryAssetFile.file_key_sha256 == file.file_key_sha256,
                        RepositoryAssetFile.status.in_(("STORED", "QUARANTINED")),
                    )
                    .order_by(RepositoryAssetFile.created_at.desc())
                )
            )
            matched = None
            for prior in rows:
                if await _stored_valid(db, owner, prior, file, selected_storage):
                    matched = prior
                    break
            if matched is not None:
                if matched.status == "QUARANTINED":
                    adopted = RepositoryAssetFile(
                        id=uuid.uuid4(),
                        user_id=owner,
                        job_id=identity,
                        plan_id=matched.plan_id,
                        file_key_sha256=matched.file_key_sha256,
                        attachment_id=matched.attachment_id,
                        status="STORED",
                        actual_sha256=matched.actual_sha256,
                        actual_size_bytes=matched.actual_size_bytes,
                        remote_verified=True,
                    )
                    db.add(adopted)
                    db.commit()
                    matched = adopted
                verified[file.path] = matched
                _progress(db, owner, identity, token, verified)
                db.rollback()
                continue
            if not file.selected:
                db.rollback()
                continue
            checkpoint = RepositoryAssetFile(
                id=uuid.uuid4(),
                user_id=owner,
                job_id=identity,
                plan_id=file.plan_id,
                file_key_sha256=file.file_key_sha256,
                status="STORING",
                remote_verified=False,
            )
            db.add(checkpoint)
            checkpoint_id = checkpoint.id
            remote_file = policy.file_remote(file)
            expected_size = file.size_bytes
            db.commit()
            measured, received = hashlib.sha256(), 0
            last_check = asyncio.get_running_loop().time()

            async def chunks(
                current_file: AssetInventoryFile = remote_file,
                current_digest: Any = measured,
            ) -> AsyncIterator[bytes]:
                nonlocal received, last_check
                async for chunk in selected_remote.stream_file(
                    reference,
                    current_file,
                    max_bytes=min(max_bytes, current_file.size_bytes or 0),
                ):
                    received += len(chunk)
                    if current_file.size_bytes is None or received > current_file.size_bytes:
                        raise DomainError(
                            "ASSET_SIZE_MISMATCH", "Payload exceeds the frozen file size", 409
                        )
                    current = asyncio.get_running_loop().time()
                    if current - last_check >= POLL_SECONDS:
                        with Session(db.get_bind()) as watch:
                            _check(watch, owner, identity, token, renew=True)
                        last_check = current
                    current_digest.update(chunk)
                    yield chunk
                if received != current_file.size_bytes:
                    raise DomainError(
                        "ASSET_SIZE_MISMATCH", "Payload ended before the frozen file size", 409
                    )

            try:
                stored = await _await_save(
                    selected_storage.save(
                        chunks(),
                        mime_type="application/octet-stream",
                        max_bytes=max(1, expected_size or 0),
                        allow_empty=expected_size == 0,
                    ),
                    db,
                    owner,
                    identity,
                    token,
                )
                accepted = _store_receipt(
                    db,
                    owner,
                    identity,
                    token,
                    file,
                    checkpoint_id,
                    stored,
                    selected_storage,
                    measured.hexdigest(),
                    received,
                )
                if accepted.status != "STORED":
                    raise DomainError(
                        "ASSET_SCOPE_CHANGED",
                        "Late asset bytes were quarantined instead of adopted",
                        409,
                    )
                verified[file.path] = accepted
                _progress(db, owner, identity, token, verified)
            except DomainError as error:
                db.rollback()
                current = _job(db, owner, identity, lock=True)
                if current is not None and current.lease_token == token:
                    row = db.get(RepositoryAssetFile, checkpoint_id)
                    if row is not None and row.status == "STORING":
                        row.status = (
                            "UNSUPPORTED" if error.code == "ASSET_GIT_LFS_POINTER" else "FAILED"
                        )
                        row.error_code = error.code
                    db.commit()
                else:
                    db.rollback()
                if error.code == "ASSET_GIT_LFS_POINTER":
                    declared_gaps.append("GIT_LFS_PAYLOAD_MISSING:" + file.path)
                    continue
                raise
        gaps = list(declared_gaps)
        file_map = {file.path: file for file in files}
        for path, row in list(verified.items()):
            if not await _stored_valid(db, owner, row, file_map[path], selected_storage):
                gaps.append("STORED_OBJECT_CHANGED:" + path)
                verified.pop(path)
        gaps += await _shard_gaps(selected_storage, db, owner, files, verified)
        current, final_plan = _check(db, owner, identity, token)
        if final_plan.plan_sha256 != plan_hash:
            raise DomainError(
                "ASSET_SOURCE_CHANGED",
                "Approved asset plan changed before snapshot publication",
                409,
            )
        if scope != "FULL_INVENTORY":
            gaps.append("SELECTED_SUBSET")
        if not inventory_complete or len(verified) != len(files):
            gaps.append("INVENTORY_NOT_FULLY_STORED")
        current.stored_files = len(verified)
        current.stored_bytes = sum(row.actual_size_bytes or 0 for row in verified.values())
        ids = [row.id for row in verified.values()]
        manifest = policy.snapshot_manifest(db, current, ids)
        digest = hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot = RepositoryAssetSnapshot(
            id=uuid.uuid4(),
            user_id=owner,
            job_id=identity,
            plan_id=current.plan_id,
            source_snapshot_id=source,
            status="PARTIAL" if gaps else "MATERIALIZED",
            manifest_sha256=digest,
            stored_files=current.stored_files,
            stored_bytes=current.stored_bytes,
            gaps_text=json.dumps(sorted(set(gaps)), ensure_ascii=False),
        )
        db.add(snapshot)
        db.flush()
        for row in verified.values():
            row.snapshot_id = snapshot.id
        _terminal(current, "COMPLETED")
        db.commit()
    except Exception as error:
        db.rollback()
        current = _job(db, owner, identity, lock=True)
        if current is not None and current.lease_token == token:
            _terminal(
                current,
                "NEEDS_ATTENTION"
                if not isinstance(error, DomainError)
                or error.code in {"ASSET_STORAGE_OUTCOME_UNKNOWN", "ASSET_STORAGE_RECEIPT_CONFLICT"}
                else "CANCELLED"
                if current.status == "CANCEL_REQUESTED"
                else "FAILED",
                error.code if isinstance(error, DomainError) else "ASSET_STORAGE_FAILED",
            )
            db.commit()
        else:
            db.rollback()
    return _job(db, owner, identity)
