"""Explicit bounded probe of a persisted owner-approved canonical output only."""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.result_artifact_probe import FileProbeReceipt, ResultArtifactProbe
from app.domain.task_results import EnvelopeGap, ReadingResultEnvelopeOut
from app.errors import DomainError
from app.models_analytical import (
    CanonicalAnalyticalNote,
    PaperReadingApproval,
    PaperReadingApprovalPlan,
)
from app.providers.registry import result_artifact_probe
from app.services.reading_result_envelope import reading_result_envelope


async def check_result_file(
    db: Session, owner: uuid.UUID, job_id: uuid.UUID, *, probe: ResultArtifactProbe | None = None
) -> ReadingResultEnvelopeOut:
    envelope = reading_result_envelope(db, owner, job_id)
    if not envelope.file_recheck_available or envelope.completion_proposal == "BLOCKED":
        raise DomainError(
            "RESULT_FILE_NOT_APPROVED",
            "An intact owner-approved canonical output is required for file verification",
            409,
        )
    with db.no_autoflush:
        result = db.execute(
            select(CanonicalAnalyticalNote, PaperReadingApprovalPlan)
            .join(
                PaperReadingApprovalPlan,
                PaperReadingApprovalPlan.id == CanonicalAnalyticalNote.plan_id,
            )
            .join(
                PaperReadingApproval,
                (PaperReadingApproval.plan_id == PaperReadingApprovalPlan.id)
                & (PaperReadingApproval.job_id == CanonicalAnalyticalNote.job_id),
            )
            .where(
                CanonicalAnalyticalNote.user_id == owner,
                CanonicalAnalyticalNote.job_id == job_id,
                PaperReadingApprovalPlan.user_id == owner,
                PaperReadingApproval.user_id == owner,
            )
        ).one_or_none()
        if result is None:
            raise DomainError(
                "RESULT_FILE_NOT_APPROVED", "Owner-approved note destination is unavailable", 409
            )
        note, plan = result
        artifact = next(
            item
            for item in envelope.output_artifacts
            if item.kind == "CANONICAL_ANALYTICAL_NOTE" and item.id == note.id
        )
        try:
            receipt = await asyncio.to_thread(
                (probe or result_artifact_probe()).inspect,
                Path(plan.output_root),
                plan.output_path,
                artifact.sha256,
                artifact.size_bytes,
            )
        except Exception:
            receipt = FileProbeReceipt("UNAVAILABLE")
        if receipt.status == "VERIFIED":
            if receipt.actual_sha256 is None or receipt.actual_size_bytes is None:
                receipt = FileProbeReceipt("UNAVAILABLE")
            elif (
                receipt.actual_sha256 != artifact.sha256
                or receipt.actual_size_bytes != artifact.size_bytes
            ):
                receipt = FileProbeReceipt("CHANGED")
        artifact.verification = receipt.status
        envelope.gaps = [item for item in envelope.gaps if item.code != "FILE_NOT_RECHECKED"]
        if receipt.status != "VERIFIED":
            envelope.gaps.append(
                EnvelopeGap(
                    code="CURRENT_FILE_" + receipt.status,
                    detail="Current approved destination file could not be proven to match the persisted canonical hash and size; historical receipts remain unchanged.",
                )
            )
            envelope.completion_proposal = "BLOCKED"
            envelope.next_action = "Inspect the approved note destination and preserve human edits; repair the file publication through the existing workflow."
        # Probe is an observation, not an export-status update or scientific review.
        return envelope
