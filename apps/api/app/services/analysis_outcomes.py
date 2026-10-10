"""Immutable budget entries for unknown outcomes and unusable AI responses.

These events are allowances, never reported provider Token usage or prices.
They survive an owner retry/cancellation and are charged to the call-start month.
"""

import hashlib
import json
import math
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.ai import AIUsage, PaperAnalysisResult
from app.errors import DomainError
from app.models import (
    AnalysisSettings,
    CanonicalAnalyticalNote,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperReadingApproval,
    ResearchEvent,
)

UNCERTAIN_EVENT = "paper.analysis_outcome_uncertain"
UNUSABLE_EVENT = "paper.analysis_result_unusable"
CALL_BUDGET_EVENTS = frozenset({UNCERTAIN_EVENT, UNUSABLE_EVENT})
REVALIDATED_EVENT = "paper.analysis_result_revalidated"
MAX_CANDIDATE_RESULT_BYTES = 1_048_576
MAX_VALIDATION_DIAGNOSTICS_BYTES = 65_536
UNCERTAIN_JOB_CODES = frozenset(
    {
        "ANALYSIS_OUTCOME_UNCERTAIN",
        "PART_RESULT_UNCERTAIN",
        "PART_OUTCOME_UNCERTAIN",
    }
)


def _bounded_text(value: str, limit: int) -> str:
    return value[:limit].encode("utf-8", errors="replace").decode("utf-8")


def _diagnostic_json(value: object, depth: int = 0) -> tuple[object, bool]:
    """Copy only a finite JSON tree; source diagnostics cannot break accounting."""
    if depth > 6:
        return None, True
    if value is None or isinstance(value, (bool, int)):
        return value, False
    if isinstance(value, float):
        return (value, False) if math.isfinite(value) else (None, True)
    if isinstance(value, str):
        clipped = _bounded_text(value, 4000)
        return clipped, clipped != value
    if isinstance(value, dict):
        result: dict[str, object] = {}
        truncated = len(value) > 100
        for index, (key, item) in enumerate(value.items()):
            if index >= 100:
                break
            if not isinstance(key, str) or len(key) > 120:
                truncated = True
                continue
            result[key], omitted = _diagnostic_json(item, depth + 1)
            truncated |= omitted
        return result, truncated
    if isinstance(value, (list, tuple)):
        result_list: list[object] = []
        truncated = len(value) > 100
        for item in value[:100]:
            cleaned, omitted = _diagnostic_json(item, depth + 1)
            result_list.append(cleaned)
            truncated |= omitted
        return result_list, truncated
    return None, True


def bounded_diagnostics(value: object) -> tuple[dict[str, object] | None, bool]:
    if value is None:
        return None, False
    try:
        cleaned, truncated = _diagnostic_json(value)
        if not isinstance(cleaned, dict):
            return None, True
        raw = json.dumps(cleaned, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_VALIDATION_DIAGNOSTICS_BYTES:
            return None, True
        return cleaned, truncated
    except Exception:
        # This is optional forensic data, not the receipt/ledger write itself.
        return None, True


def bounded_candidate_result(
    value: object,
) -> tuple[dict[str, object] | None, bool, str | None]:
    if value is None:
        return None, False, "NOT_AVAILABLE"
    try:
        raw_value = (
            value.model_dump(mode="json", warnings=False)
            if isinstance(value, PaperAnalysisResult)
            else value
        )
        encoded = json.dumps(raw_value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_CANDIDATE_RESULT_BYTES:
            return None, True, "SIZE_LIMIT"
        candidate = PaperAnalysisResult.model_validate_json(encoded)
        return candidate.model_dump(mode="json"), False, None
    except Exception:
        return None, False, "INVALID_SCHEMA_OR_SERIALIZATION"


def _result_issue_envelope(
    result: PaperAnalysisResult | None,
    error: DomainError | None,
) -> dict[str, object]:
    candidate, candidate_truncated, omitted_reason = bounded_candidate_result(result)
    diagnostics, diagnostics_truncated = bounded_diagnostics(error.details if error else None)
    return {
        "error_code": _bounded_text(error.code, 80) if error else None,
        "error_message": _bounded_text(error.message, 2000) if error else None,
        "diagnostics": diagnostics,
        "diagnostics_truncated": diagnostics_truncated,
        "candidate_result": candidate,
        "candidate_result_truncated": candidate_truncated,
        "candidate_result_omitted_reason": omitted_reason,
    }


def record_uncertain_call(
    db: Session,
    job: PaperAnalysisJob,
    part: PaperAnalysisPart | None = None,
    *,
    event_type: str = UNCERTAIN_EVENT,
    usage: AIUsage | None = None,
    provider_response_id: str | None = None,
    result: PaperAnalysisResult | None = None,
    validation_error: DomainError | None = None,
) -> None:
    """Record once per owner/job/part/monotonic attempt under the job row lock.

    Unusable responses retain their reported usage when available; unknown
    usage is a labelled conservative allowance and never presented as actual.
    """
    if event_type not in CALL_BUDGET_EVENTS:
        raise DomainError("VALIDATION_ERROR", "Invalid AI budget event type", 422)
    owned_job = db.scalar(
        select(PaperAnalysisJob.id)
        .where(PaperAnalysisJob.id == job.id, PaperAnalysisJob.user_id == job.user_id)
        .with_for_update()
    )
    if owned_job is None:
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    if part is not None and (
        part.job_id != job.id
        or part.user_id != job.user_id
        or db.scalar(
            select(PaperAnalysisPart.id).where(
                PaperAnalysisPart.id == part.id,
                PaperAnalysisPart.job_id == job.id,
                PaperAnalysisPart.user_id == job.user_id,
            )
        )
        is None
    ):
        raise DomainError("NOT_FOUND", "Analysis part not found", 404)
    attempt = part.attempt_count if part is not None else job.attempt_count
    event_id = uuid.uuid5(
        job.id, f"{job.user_id}:{part.id if part is not None else 'single'}:{attempt}"
    )
    if (
        db.scalar(
            select(ResearchEvent.id).where(
                ResearchEvent.user_id == job.user_id, ResearchEvent.event_id == event_id
            )
        )
        is not None
    ):
        return
    remaining = max(1, job.part_count - job.parts_completed)
    allowance = (job.reserved_tokens + remaining - 1) // remaining
    allowance_basis = "job_reservation"
    if allowance <= 0:
        # Legacy/incomplete in-flight rows may not have a reservation. A current
        # per-call allowance is a conservative fallback, not reconstructed usage.
        policy = db.get(AnalysisSettings, job.user_id)
        allowance_basis = "current_policy_fallback"
        allowance = (
            policy.max_input_tokens_per_job + policy.max_output_tokens_per_job
            if policy is not None
            else 16000
        )
    input_tokens = usage.input_tokens if usage is not None else None
    output_tokens = usage.output_tokens if usage is not None else None
    reported = input_tokens is not None and output_tokens is not None
    if reported:
        assert input_tokens is not None and output_tokens is not None
        allowance = input_tokens + output_tokens
        allowance_basis = "reported_usage"
    elif input_tokens is not None or output_tokens is not None:
        allowance = max(allowance, (input_tokens or 0) + (output_tokens or 0))
    if not reported:
        policy = db.get(AnalysisSettings, job.user_id)
        if (
            policy is not None
            and policy.budget_mode == "PROVIDER_QUOTA"
            and job.provider_key == "codex"
        ):
            # There is no application output ceiling in this mode. This numeric
            # placeholder keeps historical accounting portable but is neither
            # measured usage nor an upper bound on an uncertain provider call.
            allowance_basis = "provider_quota_placeholder_not_upper_bound"
    started_at = (part.started_at if part is not None else job.started_at) or datetime.now(UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    db.add(
        ResearchEvent(
            event_id=event_id,
            user_id=job.user_id,
            event_type=event_type,
            schema_version="1.0",
            occurred_at=started_at.astimezone(UTC),
            source="analysis-worker",
            paper_id=job.paper_id,
            correlation_id=job.id,
            payload={
                "job_id": str(job.id),
                "part_id": str(part.id) if part is not None else None,
                "attempt": attempt,
                "call_started_at": started_at.astimezone(UTC).isoformat(),
                "input_sha256": job.input_sha256,
                "request_sha256": part.request_sha256 if part is not None else job.input_sha256,
                "budget_accounted_tokens": allowance,
                "allowance_basis": allowance_basis,
                "usage_reported": reported,
                "reported_input_tokens": input_tokens,
                "reported_output_tokens": output_tokens,
                "provider_response_id": provider_response_id,
                **(
                    {"result_issue": _result_issue_envelope(result, validation_error)}
                    if event_type in CALL_BUDGET_EVENTS
                    and (result is not None or validation_error is not None)
                    else {}
                ),
            },
        )
    )
    db.flush()


def restored_call_events(db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, ResearchEvent]:
    """Only a durable exact accepted result moves a receipt out of uncertainty.

    The source receipt remains append-only and remains the call-month ledger;
    completed-job counters must omit this relocated usage to prevent duplicates.
    A naked link event is insufficient proof of restoration.
    """
    restored: dict[uuid.UUID, ResearchEvent] = _erased_restoration_sources(db, user_id)
    for link in db.scalars(
        select(ResearchEvent).where(
            ResearchEvent.user_id == user_id, ResearchEvent.event_type == REVALIDATED_EVENT
        )
    ):
        try:
            source_id = uuid.UUID(str(link.payload["source_event_id"]))
        except (ValueError, KeyError):
            continue
        source = db.scalar(
            select(ResearchEvent).where(
                ResearchEvent.user_id == user_id,
                ResearchEvent.event_id == source_id,
                ResearchEvent.event_type == UNUSABLE_EVENT,
                ResearchEvent.correlation_id == link.correlation_id,
            )
        )
        job = db.scalar(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == user_id,
                PaperAnalysisJob.id == link.correlation_id,
                PaperAnalysisJob.status == "COMPLETED",
                PaperAnalysisJob.source_type == "PDF",
            )
        )
        note = db.scalar(
            select(CanonicalAnalyticalNote).where(
                CanonicalAnalyticalNote.user_id == user_id,
                CanonicalAnalyticalNote.job_id == link.correlation_id,
            )
        )
        approval = db.get(PaperReadingApproval, link.correlation_id)
        if source is None or job is None or note is None or approval is None:
            continue
        envelope = source.payload.get("result_issue")
        candidate, clipped, _ = bounded_candidate_result(
            envelope.get("candidate_result") if isinstance(envelope, dict) else None
        )
        if candidate is None or clipped:
            continue
        digest = hashlib.sha256(
            json.dumps(candidate, ensure_ascii=False, sort_keys=True, allow_nan=False).encode(
                "utf-8"
            )
        ).hexdigest()
        sections = candidate.get("sections")
        if (
            digest != link.payload.get("candidate_result_sha256")
            or source.payload.get("input_sha256") != job.input_sha256
            or source.payload.get("request_sha256") != link.payload.get("request_sha256")
            or source.payload.get("attempt") != link.payload.get("source_attempt")
            or source.payload.get("provider_response_id")
            != link.payload.get("provider_response_id")
            or not isinstance(sections, list)
            or len(sections) != 1
            or not isinstance(sections[0], dict)
            or sections[0].get("section_key") != "analytical_note"
            or sections[0].get("body_markdown") != note.markdown
            or hashlib.sha256(note.markdown.encode("utf-8")).hexdigest() != note.sha256
            or approval.user_id != user_id
            or approval.plan_id != note.plan_id
        ):
            continue
        part_key = source.payload.get("part_id")
        if part_key is not None:
            try:
                part_id = uuid.UUID(str(part_key))
            except ValueError:
                continue
            part = db.scalar(
                select(PaperAnalysisPart).where(
                    PaperAnalysisPart.id == part_id,
                    PaperAnalysisPart.user_id == user_id,
                    PaperAnalysisPart.job_id == job.id,
                    PaperAnalysisPart.status == "COMPLETED",
                )
            )
            if part is None or part.response_payload is None:
                continue
            if (
                part.request_sha256 != source.payload.get("request_sha256")
                or part.provider_response_id != source.payload.get("provider_response_id")
                or part.input_tokens != source.payload.get("reported_input_tokens")
                or part.output_tokens != source.payload.get("reported_output_tokens")
            ):
                continue
            accepted = hashlib.sha256(
                json.dumps(
                    part.response_payload, ensure_ascii=False, sort_keys=True, allow_nan=False
                ).encode("utf-8")
            ).hexdigest()
            if accepted != link.payload.get("accepted_result_sha256"):
                continue
        elif job.input_tokens != source.payload.get(
            "reported_input_tokens"
        ) or job.output_tokens != source.payload.get("reported_output_tokens"):
            continue
        restored[source_id] = source
    return restored


_DELETION_USAGE_FIELDS = (
    "operation_id",
    "source_event_id",
    "user_id",
    "link_event_id",
    "reading_job_id",
    "part_id",
    "plan_id",
    "input_sha256",
    "request_sha256",
    "candidate_result_sha256",
    "accepted_result_sha256",
    "note_sha256",
    "source_attempt",
    "provider_response_id",
    "budget_accounted_tokens",
    "reported_input_tokens",
    "reported_output_tokens",
    "call_started_at",
)


def _usage_receipt_sha(receipt: object) -> str:
    payload = {key: getattr(receipt, key) for key in _DELETION_USAGE_FIELDS}
    when = payload["call_started_at"]
    if isinstance(when, datetime):
        payload["call_started_at"] = (
            when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
        ).isoformat()
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def capture_deletion_budget_receipts(
    db: Session, owner: uuid.UUID, job_id: uuid.UUID, operation_id: uuid.UUID
) -> int:
    """Freeze only actually verified restorations before deleting their body proof.

    The caller owns admission locks and commits this alongside its deletion mark.
    This never treats an unverified candidate as a recovered/paid result.
    """
    from app.models_note_deletion import NoteDeletionUsageReceipt, NotePermanentDeletion

    operation = db.scalar(
        select(NotePermanentDeletion).where(
            NotePermanentDeletion.id == operation_id,
            NotePermanentDeletion.user_id == owner,
            NotePermanentDeletion.reading_job_id == job_id,
        )
    )
    job = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.id == job_id, PaperAnalysisJob.user_id == owner
        )
    )
    if operation is None or job is None:
        raise DomainError("NOT_FOUND", "Owned deletion accounting source not found", 404)
    restored = restored_call_events(db, owner)
    count = 0
    for source in restored.values():
        if source.correlation_id != job_id:
            continue
        key = (operation_id, source.event_id)
        existing = db.get(NoteDeletionUsageReceipt, key)
        if existing is not None:
            if existing.receipt_sha256 != _usage_receipt_sha(existing):
                raise DomainError("DATA_INTEGRITY", "Deletion accounting receipt changed", 500)
            continue
        # This link already passed the full body/part/approval checks above.
        link = db.scalar(
            select(ResearchEvent).where(
                ResearchEvent.user_id == owner,
                ResearchEvent.correlation_id == job_id,
                ResearchEvent.event_type == REVALIDATED_EVENT,
                ResearchEvent.event_id
                == uuid.uuid5(source.event_id, "canonical-local-revalidation-v1"),
            )
        )
        note = db.scalar(
            select(CanonicalAnalyticalNote).where(
                CanonicalAnalyticalNote.user_id == owner, CanonicalAnalyticalNote.job_id == job_id
            )
        )
        approval = db.get(PaperReadingApproval, job_id)
        if link is None or note is None or approval is None or approval.user_id != owner:
            raise DomainError("DATA_INTEGRITY", "Verified deletion accounting source changed", 500)
        candidate_sha = link.payload.get("candidate_result_sha256")
        accepted_sha = link.payload.get("accepted_result_sha256")
        request_sha = source.payload.get("request_sha256")
        allowance = source.payload.get("budget_accounted_tokens")
        attempt = source.payload.get("attempt")
        input_tokens = source.payload.get("reported_input_tokens")
        output_tokens = source.payload.get("reported_output_tokens")
        if (
            not all(
                _valid_sha(value)
                for value in (
                    candidate_sha,
                    accepted_sha,
                    request_sha,
                    job.input_sha256,
                    note.sha256,
                )
            )
            or not isinstance(allowance, int)
            or isinstance(allowance, bool)
            or allowance < 0
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or attempt < 1
            or any(
                value is not None
                and (not isinstance(value, int) or isinstance(value, bool) or value < 0)
                for value in (input_tokens, output_tokens)
            )
        ):
            raise DomainError(
                "DATA_INTEGRITY", "Verified deletion accounting values are invalid", 500
            )
        raw_part_id = source.payload.get("part_id")
        try:
            part_id = uuid.UUID(str(raw_part_id)) if raw_part_id is not None else None
        except ValueError as error:
            raise DomainError(
                "DATA_INTEGRITY", "Verified accounting part identity is invalid", 500
            ) from error
        response_id = source.payload.get("provider_response_id")
        if response_id is not None and (not isinstance(response_id, str) or len(response_id) > 200):
            raise DomainError(
                "DATA_INTEGRITY", "Verified accounting response identity is invalid", 500
            )
        receipt = NoteDeletionUsageReceipt(
            operation_id=operation_id,
            source_event_id=source.event_id,
            user_id=owner,
            link_event_id=link.event_id,
            reading_job_id=job_id,
            part_id=part_id,
            plan_id=approval.plan_id,
            input_sha256=job.input_sha256,
            request_sha256=request_sha,
            candidate_result_sha256=candidate_sha,
            accepted_result_sha256=accepted_sha,
            note_sha256=note.sha256,
            source_attempt=attempt,
            provider_response_id=response_id,
            budget_accounted_tokens=allowance,
            reported_input_tokens=input_tokens,
            reported_output_tokens=output_tokens,
            call_started_at=source.occurred_at,
        )
        receipt.receipt_sha256 = _usage_receipt_sha(receipt)
        db.add(receipt)
        count += 1
    db.flush()
    return count


def _erased_restoration_sources(db: Session, owner: uuid.UUID) -> dict[uuid.UUID, ResearchEvent]:
    """Retain call-month relocation from frozen content-free deletion receipts."""
    from app.models_note_deletion import NoteDeletionUsageReceipt, NotePermanentDeletion

    restored: dict[uuid.UUID, ResearchEvent] = {}
    receipts = db.scalars(
        select(NoteDeletionUsageReceipt)
        .join(
            NotePermanentDeletion,
            (NotePermanentDeletion.id == NoteDeletionUsageReceipt.operation_id)
            & (NotePermanentDeletion.user_id == owner),
        )
        .where(
            NoteDeletionUsageReceipt.user_id == owner,
            NotePermanentDeletion.reading_job_id == NoteDeletionUsageReceipt.reading_job_id,
        )
    )
    for receipt in receipts:
        if receipt.receipt_sha256 != _usage_receipt_sha(receipt):
            raise DomainError("DATA_INTEGRITY", "Deletion accounting receipt changed", 500)
        source = db.scalar(
            select(ResearchEvent).where(
                ResearchEvent.user_id == owner,
                ResearchEvent.event_id == receipt.source_event_id,
                ResearchEvent.event_type == UNUSABLE_EVENT,
                ResearchEvent.correlation_id == receipt.reading_job_id,
            )
        )
        link = db.scalar(
            select(ResearchEvent).where(
                ResearchEvent.user_id == owner,
                ResearchEvent.event_id == receipt.link_event_id,
                ResearchEvent.event_type == REVALIDATED_EVENT,
                ResearchEvent.correlation_id == receipt.reading_job_id,
            )
        )
        job = db.scalar(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == owner,
                PaperAnalysisJob.id == receipt.reading_job_id,
                PaperAnalysisJob.status == "COMPLETED",
                PaperAnalysisJob.source_type == "PDF",
            )
        )
        approval = db.get(PaperReadingApproval, receipt.reading_job_id)
        if source is None or link is None or job is None or approval is None:
            raise DomainError(
                "DATA_INTEGRITY", "Deleted reading accounting references are missing", 500
            )
        when = source.occurred_at
        captured = receipt.call_started_at
        when = when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
        captured = (
            captured.replace(tzinfo=UTC) if captured.tzinfo is None else captured.astimezone(UTC)
        )
        expected_source = {
            "input_sha256": receipt.input_sha256,
            "request_sha256": receipt.request_sha256,
            "part_id": str(receipt.part_id) if receipt.part_id else None,
            "attempt": receipt.source_attempt,
            "provider_response_id": receipt.provider_response_id,
            "budget_accounted_tokens": receipt.budget_accounted_tokens,
            "reported_input_tokens": receipt.reported_input_tokens,
            "reported_output_tokens": receipt.reported_output_tokens,
        }
        expected_link = {
            "source_event_id": str(receipt.source_event_id),
            "candidate_result_sha256": receipt.candidate_result_sha256,
            "accepted_result_sha256": receipt.accepted_result_sha256,
            "input_sha256": receipt.input_sha256,
            "request_sha256": receipt.request_sha256,
            "part_id": str(receipt.part_id) if receipt.part_id else None,
            "source_attempt": receipt.source_attempt,
            "provider_response_id": receipt.provider_response_id,
        }
        if (
            when != captured
            or job.input_sha256 != receipt.input_sha256
            or approval.user_id != owner
            or approval.plan_id != receipt.plan_id
            or any(source.payload.get(key) != value for key, value in expected_source.items())
            or any(link.payload.get(key) != value for key, value in expected_link.items())
        ):
            raise DomainError("DATA_INTEGRITY", "Deleted reading accounting identity changed", 500)
        if receipt.part_id is not None:
            part = db.scalar(
                select(PaperAnalysisPart).where(
                    PaperAnalysisPart.id == receipt.part_id,
                    PaperAnalysisPart.user_id == owner,
                    PaperAnalysisPart.job_id == receipt.reading_job_id,
                    PaperAnalysisPart.status == "COMPLETED",
                )
            )
            if (
                part is None
                or part.request_sha256 != receipt.request_sha256
                or part.provider_response_id != receipt.provider_response_id
                or part.input_tokens != receipt.reported_input_tokens
                or part.output_tokens != receipt.reported_output_tokens
            ):
                raise DomainError("DATA_INTEGRITY", "Deleted reading accounting part changed", 500)
        elif (
            job.input_tokens != receipt.reported_input_tokens
            or job.output_tokens != receipt.reported_output_tokens
        ):
            raise DomainError("DATA_INTEGRITY", "Deleted reading accounting usage changed", 500)
        restored[receipt.source_event_id] = source
    return restored


def restored_budget_tokens(db: Session, user_id: uuid.UUID, start: datetime, end: datetime) -> int:
    total = 0
    for event in restored_call_events(db, user_id).values():
        when = event.occurred_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if start <= when < end:
            value = event.payload.get("budget_accounted_tokens")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DomainError("DATA_INTEGRITY", "Recovered call budget entry is invalid", 500)
            total += value
    return total


def restored_known_tokens(events: list[ResearchEvent]) -> tuple[int, int]:
    values = []
    for key in ("reported_input_tokens", "reported_output_tokens"):
        values.append(
            sum(
                value
                for event in events
                if isinstance(value := event.payload.get(key), int)
                and not isinstance(value, bool)
                and value >= 0
            )
        )
    return values[0], values[1]


def reported_job_tokens(db: Session, user_id: uuid.UUID, jobs: list[PaperAnalysisJob]) -> int:
    """Report known completed-part usage even when another part has missing usage."""
    restored = restored_call_events(db, user_id)
    total = 0
    for job in jobs:
        if job.user_id != user_id:
            raise DomainError("NOT_FOUND", "Analysis job not found", 404)
        parts = list(
            db.scalars(
                select(PaperAnalysisPart).where(
                    PaperAnalysisPart.job_id == job.id,
                    PaperAnalysisPart.user_id == user_id,
                    PaperAnalysisPart.status == "COMPLETED",
                )
            )
        )
        source_input, source_output = restored_known_tokens(
            [event for event in restored.values() if event.correlation_id == job.id]
        )
        total += max(
            0,
            max(job.input_tokens or 0, sum(part.input_tokens or 0 for part in parts))
            - source_input,
        )
        total += max(
            0,
            max(job.output_tokens or 0, sum(part.output_tokens or 0 for part in parts))
            - source_output,
        )
    return total


def uncertain_budget_tokens(db: Session, user_id: uuid.UUID, start: datetime, end: datetime) -> int:
    restored = restored_call_events(db, user_id)
    events = db.scalars(
        select(ResearchEvent).where(
            ResearchEvent.user_id == user_id,
            ResearchEvent.event_type.in_(CALL_BUDGET_EVENTS),
            ResearchEvent.occurred_at >= start,
            ResearchEvent.occurred_at < end,
        )
    )
    total = 0
    for event in events:
        if event.event_id in restored:
            continue
        value = event.payload.get("budget_accounted_tokens")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DomainError("DATA_INTEGRITY", "Unknown-call budget entry is invalid", 500)
        total += value
    return total


def reported_call_tokens(db: Session, user_id: uuid.UUID, start: datetime, end: datetime) -> int:
    events = db.scalars(
        select(ResearchEvent).where(
            ResearchEvent.user_id == user_id,
            ResearchEvent.event_type.in_(CALL_BUDGET_EVENTS),
            ResearchEvent.occurred_at >= start,
            ResearchEvent.occurred_at < end,
        )
    )
    return sum(
        value
        for event in events
        for key in ("reported_input_tokens", "reported_output_tokens")
        if isinstance(value := event.payload.get(key), int)
        and not isinstance(value, bool)
        and value >= 0
    )


def error_receipt(error: Exception) -> tuple[AIUsage | None, str | None]:
    if not isinstance(error, DomainError) or not isinstance(error.details, dict):
        return None, None
    raw = error.details.get("usage")
    if not isinstance(raw, dict):
        return None, None
    values = []
    for key in ("input_tokens", "output_tokens"):
        value = raw.get(key)
        values.append(
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        )
    response_id = error.details.get("provider_response_id")
    return AIUsage(values[0], values[1]), (
        response_id if isinstance(response_id, str) and len(response_id) <= 200 else None
    )
