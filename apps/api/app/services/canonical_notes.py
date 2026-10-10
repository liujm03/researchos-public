"""Persist complete canonical candidates before a retryable filesystem export."""

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Exists

from app.core.config import get_settings
from app.domain.note_output import NoteOutputProvider
from app.errors import DomainError
from app.models import Attachment, PaperAnalysisJob
from app.models_analytical import (
    CanonicalAnalyticalNote,
    PaperReadingApproval,
    PaperReadingApprovalPlan,
)
from app.providers.registry import note_output_provider, storage_provider
from app.services.note_deletion_state import (
    require_not_permanently_deleted,
    require_output_path_available,
)
from app.services.note_trash import require_selectable_job, selectable_job_clause

AUTO_PUBLICATION_ATTEMPTS = 5
PUBLICATION_LEASE_SECONDS = 600


def _completed_approval(user_id: uuid.UUID) -> Exists:
    return exists(
        select(PaperReadingApproval.job_id)
        .join(
            PaperAnalysisJob,
            (PaperAnalysisJob.id == PaperReadingApproval.job_id)
            & (PaperAnalysisJob.user_id == user_id),
        )
        .where(
            PaperReadingApproval.user_id == user_id,
            PaperReadingApproval.job_id == CanonicalAnalyticalNote.job_id,
            PaperReadingApproval.plan_id == CanonicalAnalyticalNote.plan_id,
            PaperAnalysisJob.source_type == "PDF",
            PaperAnalysisJob.status == "COMPLETED",
            selectable_job_clause(user_id, CanonicalAnalyticalNote.job_id),
        )
    )


def _available_lease(now: datetime) -> ColumnElement[bool]:
    return or_(
        CanonicalAnalyticalNote.export_lease_token.is_(None),
        CanonicalAnalyticalNote.export_lease_expires_at <= now,
    )


def _automatic_due(now: datetime) -> ColumnElement[bool]:
    return (
        CanonicalAnalyticalNote.export_retryable.is_(True)
        & (CanonicalAnalyticalNote.export_attempt_count < AUTO_PUBLICATION_ATTEMPTS)
        & CanonicalAnalyticalNote.export_status.in_(["PENDING", "FAILED", "SAVING"])
        & or_(
            CanonicalAnalyticalNote.export_next_retry_at.is_(None),
            CanonicalAnalyticalNote.export_next_retry_at <= now,
        )
    )


def canonical_note_out(note: CanonicalAnalyticalNote, *, db: Session) -> dict[str, Any]:
    require_not_permanently_deleted(db, note.user_id, note.job_id)
    # Manual file-only recovery is independent of the bounded automatic policy.
    # Recheck durable approval/completion and the lease, rather than treating a
    # retryable error flag as authorization or guessing from model/profile data.
    manual_retry_allowed = (
        db.scalar(
            select(CanonicalAnalyticalNote.id).where(
                CanonicalAnalyticalNote.id == note.id,
                CanonicalAnalyticalNote.user_id == note.user_id,
                _completed_approval(note.user_id),
                CanonicalAnalyticalNote.export_status.in_(["PENDING", "FAILED"]),
                _available_lease(datetime.now(UTC)),
            )
        )
        is not None
    )
    return {
        key: getattr(note, key)
        for key in (
            "id",
            "job_id",
            "markdown",
            "sha256",
            "output_path",
            "export_status",
            "export_error",
            "export_error_code",
            "export_attempt_count",
            "export_retryable",
            "export_next_retry_at",
            "export_lease_expires_at",
            "exported_at",
            "created_at",
        )
    } | {
        "export_auto_retry_enabled": get_settings().canonical_publication_auto_retry,
        "export_manual_retry_allowed": manual_retry_allowed,
    }


def get_canonical_note(
    db: Session, user_id: uuid.UUID, job_id: uuid.UUID
) -> CanonicalAnalyticalNote:
    require_not_permanently_deleted(db, user_id, job_id)
    note = db.scalar(
        select(CanonicalAnalyticalNote).where(
            CanonicalAnalyticalNote.job_id == job_id, CanonicalAnalyticalNote.user_id == user_id
        )
    )
    if note is None:
        raise DomainError("NOT_FOUND", "Canonical analytical note is not available yet", 404)
    require_selectable_job(db, user_id, job_id)
    return note


def register_canonical_note(
    db: Session, user_id: uuid.UUID, job_id: uuid.UUID, markdown: str
) -> CanonicalAnalyticalNote:
    require_not_permanently_deleted(db, user_id, job_id)
    approval = db.scalar(
        select(PaperReadingApproval).where(
            PaperReadingApproval.job_id == job_id, PaperReadingApproval.user_id == user_id
        )
    )
    plan = db.get(PaperReadingApprovalPlan, approval.plan_id) if approval else None
    if plan is None or plan.user_id != user_id:
        raise DomainError(
            "READING_APPROVAL_REQUIRED",
            "Canonical output requires the owner's frozen approval",
            409,
        )
    require_output_path_available(db, user_id, plan.output_root, plan.output_path)
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    existing = db.scalar(
        select(CanonicalAnalyticalNote).where(
            CanonicalAnalyticalNote.job_id == job_id, CanonicalAnalyticalNote.user_id == user_id
        )
    )
    if existing:
        if existing.sha256 != digest:
            raise DomainError(
                "CANONICAL_NOTE_CONFLICT", "A different canonical result is already frozen", 409
            )
        return existing
    note = CanonicalAnalyticalNote(
        id=uuid.uuid4(),
        user_id=user_id,
        job_id=job_id,
        plan_id=plan.id,
        markdown=markdown,
        sha256=digest,
        output_path=str(PurePosixPath(plan.output_root.replace("\\", "/")) / plan.output_path),
        export_status="PENDING",
    )
    db.add(note)
    return note


async def save_canonical_note(
    db: Session,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    output: NoteOutputProvider | None = None,
    automatic: bool = False,
) -> CanonicalAnalyticalNote:
    note = get_canonical_note(db, user_id, job_id)
    plan = db.get(PaperReadingApprovalPlan, note.plan_id)
    assert plan is not None and plan.user_id == user_id
    require_output_path_available(db, user_id, plan.output_root, plan.output_path)
    now = datetime.now(UTC)
    token = uuid.uuid4()
    claim = update(CanonicalAnalyticalNote).where(
        CanonicalAnalyticalNote.id == note.id,
        CanonicalAnalyticalNote.user_id == user_id,
        _completed_approval(user_id),
        _available_lease(now),
    )
    if automatic:
        claim = claim.where(_automatic_due(now))
    claimed = db.scalar(
        claim.values(
            export_status="SAVING",
            export_lease_token=token,
            export_lease_expires_at=now + timedelta(seconds=PUBLICATION_LEASE_SECONDS),
            export_attempt_count=CanonicalAnalyticalNote.export_attempt_count + 1,
            export_next_retry_at=None,
        )
        .returning(CanonicalAnalyticalNote.id)
        .execution_options(synchronize_session=False)
    )
    db.commit()  # The token lease persists across backup registration commits.
    db.refresh(note)
    if claimed is None:
        if automatic:
            return note
        if (
            db.scalar(
                select(CanonicalAnalyticalNote.id).where(
                    CanonicalAnalyticalNote.id == note.id,
                    CanonicalAnalyticalNote.user_id == user_id,
                    _completed_approval(user_id),
                )
            )
            is None
        ):
            raise DomainError(
                "NOTE_PUBLICATION_NOT_READY",
                "Only a completed approved reading can publish its canonical note",
                409,
            )
        raise DomainError(
            "NOTE_PUBLICATION_BUSY", "Canonical note publication is already running", 409
        )
    plan = db.get(PaperReadingApprovalPlan, note.plan_id)
    assert plan is not None and plan.user_id == user_id
    try:
        if hashlib.sha256(note.markdown.encode()).hexdigest() != note.sha256:
            raise DomainError(
                "CANONICAL_NOTE_CONFLICT", "Frozen canonical Markdown hash changed", 409
            )
        await _mirror_note(db, user_id, note, plan, lease_token=token)
        _assert_publication_lease(db, user_id, note.id, token)
        provider = output or note_output_provider(plan.output_root)
        current = await asyncio.to_thread(provider.inspect, plan.output_path)
        if current.sha256 not in {None, note.sha256}:
            managed = db.scalar(
                select(CanonicalAnalyticalNote.id).where(
                    CanonicalAnalyticalNote.user_id == user_id,
                    CanonicalAnalyticalNote.output_path == note.output_path,
                    CanonicalAnalyticalNote.sha256 == current.sha256,
                    CanonicalAnalyticalNote.export_status == "SAVED",
                )
            )
            if managed is None:
                raise DomainError(
                    "NOTE_OUTPUT_CONFLICT",
                    "Existing unmanaged or human-edited note requires explicit review; generated result is retained",
                    409,
                )
        _assert_publication_lease(db, user_id, note.id, token)
        saved = await asyncio.to_thread(
            provider.save,
            plan.output_path,
            note.markdown.encode(),
            expected_current_sha256=plan.existing_file_sha256,
        )
        if saved.sha256 != note.sha256:
            raise DomainError(
                "NOTE_OUTPUT_INVALID",
                "File output receipt does not match the canonical candidate",
                500,
            )
        values: dict[str, Any] = {
            "export_status": "SAVED",
            "export_error": None,
            "export_error_code": None,
            "exported_at": datetime.now(UTC),
            "export_retryable": False,
            "export_next_retry_at": None,
        }
    except DomainError as error:
        db.rollback()
        retryable = error.code in {"STORAGE_UNAVAILABLE", "STORAGE_ERROR", "NOTE_BACKUP_TEMPORARY"}
        values = _failure_values(
            note.export_attempt_count,
            error.code,
            error.message,
            retryable,
            conflict=error.status_code == 409,
        )
    except (OSError, TimeoutError, ConnectionError):
        db.rollback()
        values = _failure_values(
            note.export_attempt_count,
            "NOTE_OUTPUT_IO_ERROR",
            "Temporary local publication I/O failure; the completed result is retained",
            True,
        )
    except Exception:
        db.rollback()
        values = _failure_values(
            note.export_attempt_count,
            "NOTE_PUBLICATION_FAILED",
            "Canonical candidate is retained; file save needs review and can be retried without inference",
            False,
        )
    finished = db.scalar(
        update(CanonicalAnalyticalNote)
        .where(
            CanonicalAnalyticalNote.id == note.id,
            CanonicalAnalyticalNote.user_id == user_id,
            CanonicalAnalyticalNote.export_lease_token == token,
            CanonicalAnalyticalNote.export_lease_expires_at > datetime.now(UTC),
        )
        .values(**values, export_lease_token=None, export_lease_expires_at=None)
        .returning(CanonicalAnalyticalNote.id)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(note)
    # Another publisher may have recovered an expired lease. Its state wins.
    if finished is None:
        return note
    return note


def _failure_values(
    attempt: int, code: str, message: str, retryable: bool, *, conflict: bool = False
) -> dict[str, Any]:
    retryable = retryable and not conflict and attempt < AUTO_PUBLICATION_ATTEMPTS
    delay = min(600, 30 * 2 ** min(max(attempt - 1, 0), 5))
    return {
        "export_status": "CONFLICT" if conflict else "FAILED",
        "export_error_code": code,
        "export_error": message[:2000],
        "export_retryable": retryable,
        "export_next_retry_at": datetime.now(UTC) + timedelta(seconds=delay) if retryable else None,
    }


def _assert_publication_lease(
    db: Session, user_id: uuid.UUID, note_id: uuid.UUID, token: uuid.UUID
) -> None:
    if (
        db.scalar(
            select(CanonicalAnalyticalNote.id).where(
                CanonicalAnalyticalNote.id == note_id,
                CanonicalAnalyticalNote.user_id == user_id,
                CanonicalAnalyticalNote.export_lease_token == token,
                CanonicalAnalyticalNote.export_lease_expires_at > datetime.now(UTC),
                selectable_job_clause(user_id, CanonicalAnalyticalNote.job_id),
            )
        )
        is None
    ):
        raise DomainError(
            "NOTE_PUBLICATION_LEASE_LOST",
            "Publication lease changed; another publisher owns recovery",
            409,
        )


async def process_due_canonical_publication(
    db: Session, user_id: uuid.UUID
) -> CanonicalAnalyticalNote | None:
    if not get_settings().canonical_publication_auto_retry:
        return None
    now = datetime.now(UTC)
    # A crashed fifth attempt cannot spin forever in SAVING or consume another
    # automatic attempt; its immutable result is available for owner file retry.
    db.execute(
        update(CanonicalAnalyticalNote)
        .where(
            CanonicalAnalyticalNote.user_id == user_id,
            _completed_approval(user_id),
            CanonicalAnalyticalNote.export_status == "SAVING",
            CanonicalAnalyticalNote.export_lease_expires_at <= now,
            CanonicalAnalyticalNote.export_attempt_count >= AUTO_PUBLICATION_ATTEMPTS,
        )
        .values(
            export_status="FAILED",
            export_retryable=False,
            export_error_code="NOTE_PUBLICATION_RETRIES_EXHAUSTED",
            export_error="Automatic file publication attempts exhausted after an interrupted write; completed reading is retained",
            export_next_retry_at=None,
            export_lease_token=None,
            export_lease_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    job_id = db.scalar(
        select(CanonicalAnalyticalNote.job_id)
        .where(
            CanonicalAnalyticalNote.user_id == user_id,
            _completed_approval(user_id),
            _automatic_due(now),
            _available_lease(now),
        )
        .order_by(CanonicalAnalyticalNote.created_at, CanonicalAnalyticalNote.id)
        .limit(1)
    )
    if job_id is None:
        return None
    return await save_canonical_note(db, user_id, job_id, automatic=True)


async def _mirror_note(
    db: Session,
    user_id: uuid.UUID,
    note: CanonicalAnalyticalNote,
    plan: PaperReadingApprovalPlan,
    *,
    lease_token: uuid.UUID,
) -> None:
    require_not_permanently_deleted(db, user_id, note.job_id)
    require_output_path_available(db, user_id, plan.output_root, plan.output_path)
    if note.attachment_id is not None:
        return
    storage = storage_provider()

    async def content() -> AsyncIterator[bytes]:
        yield note.markdown.encode()

    stored = await storage.save(content(), mime_type="text/plain", max_bytes=1_048_576)
    try:
        _assert_publication_lease(db, user_id, note.id, lease_token)
        if stored.sha256 != note.sha256 or stored.size_bytes != len(note.markdown.encode()):
            raise DomainError(
                "NOTE_OUTPUT_INVALID", "Managed note backup receipt differs from candidate", 500
            )
        existing = db.scalar(
            select(Attachment).where(
                Attachment.user_id == user_id,
                Attachment.storage_provider == storage.provider_key,
                Attachment.object_key == stored.key,
                Attachment.sha256 == stored.sha256,
                Attachment.deleted_at.is_(None),
            )
        )
        attachment = existing or Attachment(
            id=uuid.uuid4(),
            user_id=user_id,
            storage_provider=storage.provider_key,
            object_key=stored.key,
            original_filename=PurePosixPath(plan.output_path).name,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )
        if existing is None:
            db.add(attachment)
            db.flush()
        linked = db.scalar(
            update(CanonicalAnalyticalNote)
            .where(
                CanonicalAnalyticalNote.id == note.id,
                CanonicalAnalyticalNote.user_id == user_id,
                CanonicalAnalyticalNote.export_lease_token == lease_token,
                CanonicalAnalyticalNote.export_lease_expires_at > datetime.now(UTC),
                selectable_job_clause(user_id, CanonicalAnalyticalNote.job_id),
            )
            .values(attachment_id=attachment.id)
            .returning(CanonicalAnalyticalNote.id)
            .execution_options(synchronize_session=False)
        )
        if linked is None:
            raise DomainError(
                "NOTE_PUBLICATION_LEASE_LOST",
                "Publication lease changed during backup registration",
                409,
            )
        db.commit()
        db.refresh(note)
    except BaseException:
        db.rollback()
        try:
            registered = db.scalar(
                select(Attachment.id).where(
                    Attachment.user_id == user_id,
                    Attachment.storage_provider == storage.provider_key,
                    Attachment.object_key == stored.key,
                )
            )
        except Exception:
            raise DomainError(
                "NOTE_BACKUP_OUTCOME_UNKNOWN",
                "Preserve managed bytes until backup registration can be verified",
                503,
            ) from None
        if registered is None:
            try:
                await storage.delete(stored.key)
            except Exception:
                raise DomainError(
                    "NOTE_BACKUP_CLEANUP_REQUIRED",
                    "Unregistered managed note bytes need cleanup",
                    503,
                ) from None
        raise
