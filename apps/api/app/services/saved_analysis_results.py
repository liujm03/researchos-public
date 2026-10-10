"""Recheck exact rejected writer receipts and publish without model execution."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.ai import AIAnalysisResponse, AIUsage, PaperAnalysisResult
from app.errors import DomainError
from app.models import (
    AnalysisInputSnapshot,
    LiteratureIngestJob,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperReadingApproval,
    ResearchEvent,
)
from app.services.analysis_outcomes import (
    REVALIDATED_EVENT,
    UNCERTAIN_EVENT,
    UNUSABLE_EVENT,
    bounded_candidate_result,
    restored_call_events,
)
from app.services.analysis_worker import (
    _attempt_note_export,
    _part_request,
    _persist_analysis_note,
    _request_from_snapshot,
    _validate_evidence,
    _writing_request,
)
from app.services.note_deletion_state import require_not_permanently_deleted
from app.services.original_pdf_quotes import verify_new_original_quotes
from app.services.pdf_reading import validate_pdf_layout

CHECKER_VERSION = "canonical-contract-optional-figure-tables-v2"


def candidate_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def revalidation_for_event(
    db: Session, owner: uuid.UUID, event_id: uuid.UUID
) -> ResearchEvent | None:
    return db.scalar(
        select(ResearchEvent).where(
            ResearchEvent.user_id == owner,
            ResearchEvent.event_id == uuid.uuid5(event_id, "canonical-local-revalidation-v1"),
            ResearchEvent.event_type == REVALIDATED_EVENT,
        )
    )


def _token(event: ResearchEvent, key: str) -> int | None:
    value = event.payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


async def audit_saved_result_quotes(
    db: Session,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    event_id: uuid.UUID,
    expected_result_sha256: str,
) -> dict[str, object]:
    """Read-only selected candidate verification; no ORM mutations or file writes."""
    with db.no_autoflush:
        return await _audit_saved_result_quotes(
            db, user_id, job_id, event_id, expected_result_sha256
        )


async def _audit_saved_result_quotes(
    db: Session,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    event_id: uuid.UUID,
    expected_result_sha256: str,
) -> dict[str, object]:
    require_not_permanently_deleted(db, user_id, job_id)
    job = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.id == job_id,
            PaperAnalysisJob.user_id == user_id,
        )
    )
    event = db.scalar(
        select(ResearchEvent).where(
            ResearchEvent.user_id == user_id,
            ResearchEvent.event_id == event_id,
            ResearchEvent.correlation_id == job_id,
            ResearchEvent.event_type == UNUSABLE_EVENT,
        )
    )
    if job is None or event is None:
        raise DomainError("NOT_FOUND", "Saved analysis result not found", 404)
    approval = db.scalar(
        select(PaperReadingApproval).where(
            PaperReadingApproval.job_id == job_id,
            PaperReadingApproval.user_id == user_id,
        )
    )
    if job.source_type != "PDF" or approval is None:
        raise DomainError("READING_APPROVAL_REQUIRED", "An approved original PDF is required", 409)
    envelope = event.payload.get("result_issue")
    candidate, clipped, reason = bounded_candidate_result(
        envelope.get("candidate_result") if isinstance(envelope, dict) else None
    )
    if candidate is None or clipped or reason:
        raise DomainError("RESULT_NOT_RECORDED", "Complete retained candidate required", 409)
    digest = candidate_sha256(candidate)
    if digest != expected_result_sha256:
        raise DomainError("RESULT_CHANGED", "Selected retained result hash changed", 409)
    snapshot = db.get(AnalysisInputSnapshot, job_id)
    if snapshot is None or snapshot.input_sha256 != job.input_sha256:
        raise DomainError("INVALID_SNAPSHOT", "Frozen input changed", 409)
    request = _request_from_snapshot(snapshot)
    validate_pdf_layout(db, job, request, snapshot.payload)
    parts = list(
        db.scalars(
            select(PaperAnalysisPart)
            .where(
                PaperAnalysisPart.user_id == user_id,
                PaperAnalysisPart.job_id == job_id,
            )
            .order_by(PaperAnalysisPart.part_index)
        )
    )
    if parts:
        if (
            event.payload.get("part_id") != str(parts[-1].id)
            or event.payload.get("request_sha256") != parts[-1].request_sha256
        ):
            raise DomainError("INVALID_SNAPSHOT", "Selected writer request changed", 409)
        for reading in parts[:-1]:
            if reading.status != "COMPLETED" or reading.response_payload is None:
                raise DomainError("INVALID_SNAPSHOT", "Original page reading is incomplete", 409)
            _validate_evidence(
                db,
                job,
                _part_request(reading),
                AIAnalysisResponse(
                    PaperAnalysisResult.model_validate(reading.response_payload),
                    AIUsage(reading.input_tokens, reading.output_tokens),
                    reading.provider_response_id,
                ),
            )
        request = _writing_request(db, job, _part_request(parts[-1]), parts[:-1])
    elif (
        event.payload.get("part_id") is not None
        or event.payload.get("request_sha256") != job.input_sha256
    ):
        raise DomainError("INVALID_SNAPSHOT", "Selected writer request changed", 409)
    if event.payload.get("input_sha256") != job.input_sha256:
        raise DomainError("INVALID_SNAPSHOT", "Selected source input changed", 409)
    result = PaperAnalysisResult.model_validate(candidate)
    verified, audit = await verify_new_original_quotes(db, job, request, result)
    _validate_evidence(db, job, verified, AIAnalysisResponse(result, AIUsage(None, None), None))
    return {
        "candidate_result_sha256": digest,
        "original_pdf_quote_verification": audit,
        "structural_validation_passed": True,
        "scientifically_verified": False,
        "new_model_calls": 0,
    }


async def revalidate_saved_result(
    db: Session,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    event_id: uuid.UUID,
    expected_result_sha256: str,
) -> PaperAnalysisJob:
    require_not_permanently_deleted(db, user_id, job_id)
    job = db.scalar(
        select(PaperAnalysisJob)
        .where(PaperAnalysisJob.id == job_id, PaperAnalysisJob.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    event = db.scalar(
        select(ResearchEvent).where(
            ResearchEvent.user_id == user_id,
            ResearchEvent.event_id == event_id,
            ResearchEvent.correlation_id == job_id,
            ResearchEvent.event_type == UNUSABLE_EVENT,
        )
    )
    if job is None or event is None:
        raise DomainError("NOT_FOUND", "Saved analysis result not found", 404)
    envelope = event.payload.get("result_issue")
    candidate, clipped, reason = bounded_candidate_result(
        envelope.get("candidate_result") if isinstance(envelope, dict) else None
    )
    if (
        candidate is None
        or clipped
        or reason
        or (isinstance(envelope, dict) and envelope.get("candidate_result_truncated") is True)
    ):
        raise DomainError("RESULT_NOT_RECORDED", "A complete retained candidate is required", 409)
    digest = candidate_sha256(candidate)
    if digest != expected_result_sha256:
        raise DomainError("RESULT_CHANGED", "Selected retained candidate hash changed", 409)
    prior = revalidation_for_event(db, user_id, event_id)
    if prior is not None and job.status == "COMPLETED":
        if event_id in restored_call_events(db, user_id):
            return job
        raise DomainError("DATA_INTEGRITY", "Restored result no longer matches its receipt", 409)
    approval = db.scalar(
        select(PaperReadingApproval).where(
            PaperReadingApproval.job_id == job.id, PaperReadingApproval.user_id == user_id
        )
    )
    cleared = db.scalar(
        select(LiteratureIngestJob.id).where(
            LiteratureIngestJob.user_id == user_id,
            LiteratureIngestJob.analysis_job_id == job.id,
            LiteratureIngestJob.cleared_at.is_not(None),
        )
    )
    if job.source_type != "PDF" or approval is None or cleared is not None:
        raise DomainError(
            "READING_APPROVAL_REQUIRED", "Only an approved original PDF can recover", 409
        )
    if job.status not in {"FAILED", "NEEDS_ATTENTION"}:
        raise DomainError(
            "RESULT_RECOVERY_NOT_ALLOWED", "Job must be inactive before local recovery", 409
        )
    snapshot = db.get(AnalysisInputSnapshot, job.id)
    if snapshot is None or snapshot.input_sha256 != job.input_sha256:
        raise DomainError("INVALID_SNAPSHOT", "Frozen analysis input changed", 409)
    request = _request_from_snapshot(snapshot)
    validate_pdf_layout(db, job, request, snapshot.payload)
    if event.payload.get("input_sha256") != job.input_sha256:
        raise DomainError("INVALID_SNAPSHOT", "Retained result belongs to another input", 409)
    result = PaperAnalysisResult.model_validate(candidate)
    if len(result.sections) != 1 or result.sections[0].section_key != "analytical_note":
        raise DomainError(
            "RESULT_RECOVERY_NOT_ALLOWED", "Only a complete writer result can recover", 409
        )
    parts = list(
        db.scalars(
            select(PaperAnalysisPart)
            .where(PaperAnalysisPart.user_id == user_id, PaperAnalysisPart.job_id == job.id)
            .order_by(PaperAnalysisPart.part_index)
        )
    )
    part = parts[-1] if parts else None
    if any(row.status == "ANALYZING" for row in parts):
        raise DomainError(
            "RESULT_RECOVERY_NOT_ALLOWED", "An active part cannot recover locally", 409
        )
    if part is not None:
        if event.payload.get("part_id") != str(part.id):
            raise DomainError(
                "RESULT_RECOVERY_NOT_ALLOWED", "Selected result is not the final writer", 409
            )
        for reading in parts[:-1]:
            if reading.status != "COMPLETED" or reading.response_payload is None:
                raise DomainError(
                    "INVALID_SNAPSHOT", "Prior original pages were not completed", 409
                )
            _validate_evidence(
                db,
                job,
                _part_request(reading),
                AIAnalysisResponse(
                    PaperAnalysisResult.model_validate(reading.response_payload),
                    AIUsage(reading.input_tokens, reading.output_tokens),
                    reading.provider_response_id,
                ),
            )
        request = _writing_request(db, job, _part_request(part), parts[:-1])
        expected_request = part.request_sha256
    else:
        if event.payload.get("part_id") is not None:
            raise DomainError("INVALID_SNAPSHOT", "Selected result part changed", 409)
        expected_request = job.input_sha256
    if event.payload.get("request_sha256") != expected_request:
        raise DomainError("INVALID_SNAPSHOT", "Selected result request hash changed", 409)
    attempt = event.payload.get("attempt")
    if (
        not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or attempt < 1
        or attempt > (part.attempt_count if part else job.attempt_count)
    ):
        raise DomainError("INVALID_SNAPSHOT", "Selected result call attempt changed", 409)
    if request.pdf_source is None or request.pdf_source.stage != "WRITE_NOTE":
        raise DomainError(
            "RESULT_RECOVERY_NOT_ALLOWED", "Only the final writing stage can recover", 409
        )
    usage = AIUsage(_token(event, "reported_input_tokens"), _token(event, "reported_output_tokens"))
    response_id = event.payload.get("provider_response_id")
    response = AIAnalysisResponse(
        result, usage, response_id if isinstance(response_id, str) else None
    )
    request, quote_audit = await verify_new_original_quotes(db, job, request, response.result)
    blocks = _validate_evidence(db, job, request, response)
    later_unknown = list(
        db.scalars(
            select(ResearchEvent.event_id).where(
                ResearchEvent.user_id == user_id,
                ResearchEvent.correlation_id == job.id,
                ResearchEvent.event_type == UNCERTAIN_EVENT,
            )
        )
    )
    if later_unknown:
        response.result.warnings.append(
            "LOCAL_RESULT_RECOVERY: an exact earlier retained writer result was published; "
            "other provider outcomes remain unknown and their usage allowances are retained."
        )
    if part is not None:
        part.response_payload = response.result.model_dump(mode="json")
        part.provider_response_id = response.provider_response_id
        part.input_tokens, part.output_tokens = usage.input_tokens, usage.output_tokens
        part.status = "COMPLETED"
        part.completed_at = datetime.now(UTC)
        part.error_code = part.error_message = None
        job.parts_completed = len(parts)
        response = AIAnalysisResponse(
            response.result,
            AIUsage(
                sum(row.input_tokens for row in parts if row.input_tokens is not None)
                if all(row.input_tokens is not None for row in parts)
                else None,
                sum(row.output_tokens for row in parts if row.output_tokens is not None)
                if all(row.output_tokens is not None for row in parts)
                else None,
            ),
            response.provider_response_id,
        )
    db.add(
        ResearchEvent(
            event_id=uuid.uuid5(event_id, "canonical-local-revalidation-v1"),
            user_id=user_id,
            event_type=REVALIDATED_EVENT,
            schema_version="1.0",
            occurred_at=datetime.now(UTC),
            source="owner-local-revalidation",
            paper_id=job.paper_id,
            correlation_id=job.id,
            payload={
                "source_event_id": str(event_id),
                "candidate_result_sha256": digest,
                "accepted_result_sha256": candidate_sha256(response.result.model_dump(mode="json")),
                "input_sha256": job.input_sha256,
                "request_sha256": expected_request,
                "part_id": str(part.id) if part else None,
                "source_attempt": event.payload.get("attempt"),
                "provider_response_id": event.payload.get("provider_response_id"),
                "checker_version": CHECKER_VERSION,
                "original_pdf_quote_verification": quote_audit,
                "unresolved_provider_event_ids": [str(key) for key in later_unknown],
                "new_model_calls": 0,
                "scientifically_verified": False,
            },
        )
    )
    job.error_code = job.error_message = None
    job.next_retry_at = None
    recovered = _persist_analysis_note(db, job, response, blocks)
    await _attempt_note_export(db, user_id, job.id)
    return recovered
