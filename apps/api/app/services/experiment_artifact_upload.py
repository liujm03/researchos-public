"""Owner-supplied artifacts use storage ports; checkpoint bytes are never executed."""

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import Attachment, User
from app.models_experiments import ExperimentArtifact
from app.services.attachment_names import safe_attachment_filename as safe_artifact_filename
from app.services.experiments import attach_artifact, get_run

ALLOWED_MIME = frozenset(
    {
        "application/pdf",
        "application/octet-stream",
        "text/plain",
        "text/csv",
        "application/json",
        "image/png",
        "image/jpeg",
    }
)


@dataclass(frozen=True)
class ArtifactUploadResult:
    artifact: ExperimentArtifact
    duplicate: bool


async def upload_experiment_artifact(
    db: Session,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    content: AsyncIterator[bytes],
    *,
    filename: str | None,
    content_type: str | None,
    artifact_type: str,
    description: str | None,
    storage: StorageProvider,
    max_bytes: int,
) -> ArtifactUploadResult:
    get_run(db, user_id, run_id)
    mime = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_MIME:
        raise DomainError(
            "UNSUPPORTED_ARTIFACT_TYPE",
            "Use PDF, PNG/JPEG, CSV, JSON, text or opaque binary artifacts",
            422,
        )
    if max_bytes <= 0:
        raise DomainError("CONFIGURATION_ERROR", "Artifact size limit must be positive", 503)
    cleanup_key: str | None = None
    commit_attempted = False
    try:
        stored = await storage.save(content, mime_type=mime, max_bytes=max_bytes)
        cleanup_key = stored.key
        if (
            stored.size_bytes <= 0
            or stored.size_bytes > max_bytes
            or stored.mime_type != mime
            or not re.fullmatch(r"[a-f0-9]{64}", stored.sha256)
        ):
            raise DomainError(
                "STORAGE_INVALID_RECEIPT", "Storage returned an invalid artifact receipt", 503
            )
        # Serialize owner deduplication only after external I/O has completed.
        if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
            raise DomainError("NOT_FOUND", "Owner not found", 404)
        attachment = db.scalar(
            select(Attachment)
            .where(
                Attachment.user_id == user_id,
                Attachment.deleted_at.is_(None),
                Attachment.storage_provider == storage.provider_key,
                Attachment.sha256 == stored.sha256,
                Attachment.mime_type == stored.mime_type,
            )
            .order_by(Attachment.created_at, Attachment.id)
            .limit(1)
        )
        duplicate = attachment is not None
        if attachment is not None:
            if attachment.object_key != stored.key:
                await storage.delete(stored.key)
            cleanup_key = None
        else:
            attachment = Attachment(
                user_id=user_id,
                storage_provider=storage.provider_key,
                object_key=stored.key,
                original_filename=safe_artifact_filename(filename),
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
            )
            db.add(attachment)
            db.flush()
        artifact = attach_artifact(
            db, user_id, run_id, attachment.id, artifact_type, description, commit=False
        )
        commit_attempted = True
        db.commit()
        cleanup_key = None
        db.refresh(artifact)
        return ArtifactUploadResult(artifact, duplicate)
    except BaseException:
        db.rollback()
        if cleanup_key is not None:
            # A storage adapter may deduplicate its object keys. Never delete
            # a key already referenced by owner data, even before our commit.
            try:
                registered = db.scalar(
                    select(Attachment.id).where(
                        Attachment.user_id == user_id,
                        Attachment.storage_provider == storage.provider_key,
                        Attachment.object_key == cleanup_key,
                    )
                )
            except Exception as error:
                raise DomainError(
                    "UPLOAD_OUTCOME_UNKNOWN",
                    "Artifact confirmation unavailable; preserve storage and retry later",
                    503,
                ) from error
            if registered is not None:
                if commit_attempted:
                    raise DomainError(
                        "UPLOAD_OUTCOME_UNKNOWN",
                        "Artifact registered but confirmation failed; retry safely",
                        503,
                    ) from None
                raise
            try:
                await storage.delete(cleanup_key)
            except Exception as error:
                raise DomainError(
                    "STORAGE_CLEANUP_FAILED", "Artifact storage cleanup requires attention", 503
                ) from error
        raise
