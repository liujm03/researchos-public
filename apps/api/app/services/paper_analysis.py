import hashlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.ai import AnalysisMode, AnalysisScope, PaperAnalysisRequest, SourceText
from app.errors import DomainError
from app.models import (
    AnalysisInputSnapshot,
    AnalysisSettings,
    LiteratureIngestJob,
    Paper,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperAttachment,
    ParsedBlock,
    ParsedDocument,
    ParsedSection,
    User,
)
from app.providers.registry import ai_provider_descriptor
from app.services.analysis_outcomes import (
    UNCERTAIN_JOB_CODES,
    record_uncertain_call,
    restored_budget_tokens,
    restored_call_events,
    restored_known_tokens,
    uncertain_budget_tokens,
)
from app.services.analysis_parts import split_source_texts
from app.services.note_deletion_state import require_not_permanently_deleted
from app.services.papers import get_paper

ANALYSIS_VERSION = "1"
PROMPT_VERSION = "2026-10-02-v4-evidence-locators"
SCHEMA_VERSION = "1"
SCOPE_RANK = {"NONE": 0, "METADATA_ONLY": 1, "ABSTRACT_ONLY": 2, "FULL_TEXT": 3}


def uses_provider_quota(settings: AnalysisSettings, provider_key: str) -> bool:
    """A saved account policy cannot relax another provider's paid API limits."""
    return settings.budget_mode == "PROVIDER_QUOTA" and provider_key == "codex"


def linked_ingest_cleared(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(LiteratureIngestJob.id)
            .where(
                LiteratureIngestJob.user_id == user_id,
                LiteratureIngestJob.analysis_job_id == job_id,
                LiteratureIngestJob.cleared_at.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def effective_call_request(
    request: PaperAnalysisRequest, settings: AnalysisSettings, provider_key: str
) -> PaperAnalysisRequest:
    """Apply current owner policy to the next call without rewriting source hashes.

    Settings can change between calls. Source snapshots and completed part
    results stay immutable; only the output allowance for a future call changes.
    """
    output_limit = (
        None
        if uses_provider_quota(settings, provider_key)
        else min(
            request.max_output_tokens or settings.max_output_tokens_per_job,
            settings.max_output_tokens_per_job,
        )
    )
    return replace(request, max_output_tokens=output_limit)


def _payload_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _request_payload(request: PaperAnalysisRequest) -> dict[str, object]:
    from app.services.pdf_reading import request_payload

    return request_payload(request)


def _part_char_limit(request: PaperAnalysisRequest, max_input_tokens: int) -> int:
    # Input tokenization depends on the provider/model. Keep a conservative
    # source-text share for instructions, JSON framing, title and abstract.
    overhead = max(512, len(request.title) + len(request.abstract or "") + 256)
    return max_input_tokens - overhead


def _part_requests(
    request: PaperAnalysisRequest, max_input_tokens: int
) -> tuple[tuple[int, str, dict[str, object], str], ...]:
    source_limit = _part_char_limit(request, max_input_tokens)
    if source_limit < 1:
        return ()
    chunks = split_source_texts(
        request.source_texts,
        max_source_chars=source_limit,
    )
    return tuple(
        (
            chunk.index,
            chunk.section_key,
            payload,
            _payload_hash(payload),
        )
        for chunk in chunks
        for payload in [
            _request_payload(
                PaperAnalysisRequest(
                    title=request.title,
                    year=request.year,
                    abstract=request.abstract,
                    scope=request.scope,
                    mode=request.mode,
                    source_texts=chunk.source_texts,
                    max_output_tokens=request.max_output_tokens,
                )
            )
        ]
    )


def _frozen_request(payload: dict[str, object]) -> PaperAnalysisRequest:
    from app.services.pdf_reading import source_descriptor

    raw = payload.get("source_texts")
    if not isinstance(raw, list):
        raise DomainError("INVALID_SNAPSHOT", "Analysis input snapshot is invalid", 500)
    try:
        texts = tuple(
            SourceText(
                section_key=str(item["section_key"]),
                text=str(item["text"]),
                page=int(str(item["page"])) if item.get("page") is not None else None,
                block_index=int(str(item["block_index"]))
                if item.get("block_index") is not None
                else None,
                title=str(item["title"]) if item.get("title") is not None else None,
                ancestor_titles=tuple(str(title) for title in item.get("ancestor_titles", [])),
            )
            for item in raw
        )
        return PaperAnalysisRequest(
            title=str(payload["title"]),
            year=int(str(payload["year"])) if payload.get("year") is not None else None,
            abstract=str(payload["abstract"]) if payload.get("abstract") is not None else None,
            scope=payload["scope"],  # type: ignore[arg-type]
            mode=payload["mode"],  # type: ignore[arg-type]
            source_texts=texts,
            pdf_source=source_descriptor(payload),
            writer_identity=cast(dict[str, object] | None, payload.get("writer_identity")),
            reading_receipts=tuple(
                cast(list[dict[str, object]], payload.get("reading_receipts", []))
            ),
            reasoning_effort=str(payload["reasoning_effort"])
            if payload.get("reasoning_effort")
            else None,
            max_output_tokens=int(str(payload["max_output_tokens"]))
            if payload.get("max_output_tokens") is not None
            else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("INVALID_SNAPSHOT", "Analysis input snapshot is invalid", 500) from exc


def _same_source_texts(original: tuple[SourceText, ...], fragments: tuple[SourceText, ...]) -> bool:
    """Require each frozen block's exact text and locator to survive splitting."""
    grouped: list[tuple[str, int | None, int | None, str]] = []
    for item in fragments:
        locator = (item.section_key, item.page, item.block_index)
        if grouped and grouped[-1][:3] == locator:
            previous = grouped[-1]
            grouped[-1] = (*locator, previous[3] + item.text)
        else:
            grouped.append((*locator, item.text))
    return grouped == [
        (item.section_key, item.page, item.block_index, item.text) for item in original
    ]


def monthly_accounted_tokens(
    db: Session,
    jobs: list[PaperAnalysisJob],
    settings: AnalysisSettings,
    *,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> int:
    """Count known usage, reserving a full call for missing completed-part usage.

    A provider can omit usage even after returning a valid result. Treating None
    as zero would allow more calls than the owner's monthly cap intended. Unknown
    attempt allowances are counted independently by their owner-local call month.
    """
    if any(job.user_id != settings.user_id for job in jobs):
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    parts_by_job: dict[uuid.UUID, list[PaperAnalysisPart]] = {}
    restored = restored_call_events(db, settings.user_id)
    restored_parts = {event.payload.get("part_id") for event in restored.values()}
    for part in db.scalars(
        select(PaperAnalysisPart).where(
            PaperAnalysisPart.user_id == settings.user_id,
            PaperAnalysisPart.job_id.in_([job.id for job in jobs]),
        )
    ):
        parts_by_job.setdefault(part.job_id, []).append(part)
    total = 0
    for job in jobs:
        parts = parts_by_job.get(job.id, [])
        recovered = [event for event in restored.values() if event.correlation_id == job.id]
        recovered_input, recovered_output = restored_known_tokens(recovered)
        if parts:
            accounted_input = sum(
                part.input_tokens
                if part.input_tokens is not None
                else settings.max_input_tokens_per_job
                for part in parts
                if part.status == "COMPLETED" and str(part.id) not in restored_parts
            )
            accounted_output = sum(
                part.output_tokens
                if part.output_tokens is not None
                else settings.max_output_tokens_per_job
                for part in parts
                if part.status == "COMPLETED" and str(part.id) not in restored_parts
            )
            total += max((job.input_tokens or 0) - recovered_input, accounted_input)
            total += max((job.output_tokens or 0) - recovered_output, accounted_output)
        elif job.status == "COMPLETED":
            if recovered:
                continue
            total += (
                job.input_tokens
                if job.input_tokens is not None
                else settings.max_input_tokens_per_job
            )
            total += (
                job.output_tokens
                if job.output_tokens is not None
                else settings.max_output_tokens_per_job
            )
        else:
            total += (job.input_tokens or 0) + (job.output_tokens or 0)
    if period_start is None or period_end is None:
        user = db.get(User, settings.user_id)
        assert user is not None
        zone = ZoneInfo(user.timezone)
        today = datetime.now(zone).date()
        period_start = _month_start(today, zone)
        next_month = date(
            today.year + (today.month == 12), 1 if today.month == 12 else today.month + 1, 1
        )
        period_end = _month_start(next_month, zone)
    return (
        total
        + uncertain_budget_tokens(db, settings.user_id, period_start, period_end)
        + restored_budget_tokens(db, settings.user_id, period_start, period_end)
    )


def _lock_owner(db: Session, user_id: uuid.UUID) -> None:
    # Serialize budget admissions for this installation on PostgreSQL.
    # SQLite ignores FOR UPDATE; its tests do not prove concurrent admission.
    if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        raise DomainError("NOT_FOUND", "Owner not found", 404)


def analysis_settings(db: Session, user_id: uuid.UUID) -> AnalysisSettings:
    current = db.get(AnalysisSettings, user_id)
    if current is not None:
        return current
    current = AnalysisSettings(user_id=user_id)
    db.add(current)
    db.flush()
    return current


def _month_start(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day.replace(day=1), time.min, zone).astimezone(UTC)


def _day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, time.min, zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC),
    )


def _actual_input(
    db: Session, paper_id: uuid.UUID, mode: AnalysisMode
) -> tuple[AnalysisScope, tuple[SourceText, ...], ParsedDocument | None]:
    paper = db.get(Paper, paper_id)
    assert paper is not None
    if mode == "FAST":
        if paper.abstract:
            return "ABSTRACT_ONLY", (SourceText("abstract", paper.abstract, None, None),), None
        return "METADATA_ONLY", (), None
    document = db.scalar(
        select(ParsedDocument)
        .where(ParsedDocument.paper_id == paper_id, ParsedDocument.extracted_characters > 0)
        .order_by(ParsedDocument.created_at.desc(), ParsedDocument.id.desc())
    )
    if document is not None:
        section_records = {
            section.id: section
            for section in db.scalars(
                select(ParsedSection).where(ParsedSection.document_id == document.id)
            )
        }
        section_keys = {key: section.section_key for key, section in section_records.items()}
        blocks = list(
            db.scalars(
                select(ParsedBlock)
                .where(ParsedBlock.document_id == document.id)
                .order_by(ParsedBlock.block_index)
            )
        )
        excluded = {"references", "back_matter", "front_matter"}

        def substantive(block: ParsedBlock) -> bool:
            section = (
                section_records.get(block.section_id) if block.section_id is not None else None
            )
            if section is None:
                return True
            visited: set[uuid.UUID] = set()
            while section is not None and section.id not in visited:
                visited.add(section.id)
                semantic = section.semantic_key or (
                    section.section_key if section.section_key in excluded else None
                )
                if semantic in excluded:
                    return False
                section = (
                    section_records.get(section.parent_section_id)
                    if section.parent_section_id is not None
                    else None
                )
            return True

        selected = blocks if mode == "DEEP" else [block for block in blocks if substantive(block)]
        if not selected:
            selected = blocks

        def titles_for(block: ParsedBlock) -> tuple[str | None, tuple[str, ...]]:
            section = (
                section_records.get(block.section_id) if block.section_id is not None else None
            )
            title = section.title if section is not None else None
            ancestors: list[str] = []
            visited: set[uuid.UUID] = set()
            while (
                section is not None
                and section.parent_section_id is not None
                and section.id not in visited
            ):
                visited.add(section.id)
                section = section_records.get(section.parent_section_id)
                if section is not None and section.title:
                    ancestors.append(section.title)
            return title, tuple(reversed(ancestors))

        return (
            "FULL_TEXT",
            tuple(
                SourceText(
                    section_key=(section_keys.get(block.section_id) if block.section_id else None)
                    or "front_matter",
                    text=block.text,
                    page=block.page_number,
                    block_index=block.block_index,
                    title=titles_for(block)[0],
                    ancestor_titles=titles_for(block)[1],
                )
                for block in selected
            ),
            document,
        )
    if paper.abstract:
        return "ABSTRACT_ONLY", (SourceText("abstract", paper.abstract, None, None),), None
    return "METADATA_ONLY", (), None


def enqueue_analysis(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    mode: AnalysisMode,
    priority: str = "NORMAL",
    *,
    commit: bool = True,
) -> PaperAnalysisJob:
    paper = get_paper(db, user_id, paper_id)
    _lock_owner(db, user_id)
    settings = analysis_settings(db, user_id)
    scope, source_texts, document = _actual_input(db, paper_id, mode)
    descriptor = ai_provider_descriptor()
    model_key = descriptor.model_key or "unconfigured"
    provider_key = descriptor.provider_key
    request = PaperAnalysisRequest(
        title=paper.title,
        year=paper.year,
        abstract=paper.abstract,
        scope=scope,
        mode=mode,
        source_texts=source_texts,
        max_output_tokens=None
        if uses_provider_quota(settings, provider_key)
        else settings.max_output_tokens_per_job,
    )
    input_payload = _request_payload(request)
    input_sha256 = _payload_hash(input_payload)
    source_version = db.scalar(
        select(PaperAttachment.source_version)
        .where(PaperAttachment.paper_id == paper_id)
        .order_by(PaperAttachment.created_at.desc())
        .limit(1)
    )
    idempotency_material = (
        f"{paper_id}:{source_version}:{document.file_sha256 if document else ''}:"
        f"{document.parser_version if document else ''}:{input_sha256}:"
        f"{ANALYSIS_VERSION}:{PROMPT_VERSION}:{SCHEMA_VERSION}:{provider_key}:{model_key}:{mode}"
    )
    idempotency_key = hashlib.sha256(idempotency_material.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.user_id == user_id,
            PaperAnalysisJob.idempotency_key == idempotency_key,
        )
    )
    while existing is not None and linked_ingest_cleared(db, user_id, existing.id):
        idempotency_key = hashlib.sha256(
            f"{idempotency_key}:cleared:{existing.id}".encode()
        ).hexdigest()
        existing = db.scalar(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == user_id,
                PaperAnalysisJob.idempotency_key == idempotency_key,
            )
        )
    if existing is not None:
        require_not_permanently_deleted(db, user_id, existing.id)
        return existing
    content_chars = sum(len(part.text) for part in source_texts)
    too_long = content_chars > settings.max_input_tokens_per_job * 2
    part_requests = (
        _part_requests(request, settings.max_input_tokens_per_job)
        if scope == "FULL_TEXT" and too_long
        else ()
    )
    part_count = len(part_requests)
    needed = max(1, part_count) * (
        settings.max_input_tokens_per_job + settings.max_output_tokens_per_job
    )
    status = "QUEUED"
    error_code: str | None = None
    error_message: str | None = None
    if settings.budget_mode == "PROVIDER_QUOTA" and provider_key != "codex":
        status, error_code = "WAITING_CONFIG", "BUDGET_MODE_UNSUPPORTED"
        error_message = "Provider quota mode requires the Codex account provider"
    elif not descriptor.available:
        status, error_code = "WAITING_CONFIG", "AI_NOT_CONFIGURED"
        error_code = descriptor.reason_code or error_code
        error_message = descriptor.reason_message or "Paper AI provider is unavailable"
    elif SCOPE_RANK[settings.cloud_scope] < SCOPE_RANK[scope]:
        status, error_code = "WAITING_CONFIG", "CLOUD_SCOPE_NOT_ALLOWED"
        error_message = f"Cloud scope {settings.cloud_scope} does not allow {scope} input"
    elif too_long and not part_requests:
        status, error_code = "WAITING_INPUT_REDUCTION", "INPUT_TOO_LONG"
        error_message = "Paper input exceeds the configured single-job limit"
    else:
        user = db.get(User, user_id)
        assert user is not None
        zone = ZoneInfo(user.timezone)
        today = datetime.now(zone).date()
        day_start, day_end = _day_bounds(today, zone)
        recent_jobs = list(
            db.scalars(
                select(PaperAnalysisJob).where(
                    PaperAnalysisJob.user_id == user_id,
                    PaperAnalysisJob.queued_at >= day_start,
                    PaperAnalysisJob.queued_at < day_end,
                    PaperAnalysisJob.status.in_(["QUEUED", "ANALYZING", "RETRY_WAIT", "COMPLETED"]),
                )
            )
        )
        month_start = _month_start(today, zone)
        monthly_jobs = list(
            db.scalars(
                select(PaperAnalysisJob).where(
                    PaperAnalysisJob.user_id == user_id,
                    PaperAnalysisJob.queued_at >= month_start,
                )
            )
        )
        used = monthly_accounted_tokens(db, monthly_jobs, settings)
        reserved = sum(
            item.reserved_tokens
            for item in monthly_jobs
            if item.status in {"QUEUED", "ANALYZING", "RETRY_WAIT"}
        )
        if not uses_provider_quota(settings, provider_key) and (
            len(recent_jobs) >= settings.daily_analysis_limit
            or settings.monthly_token_limit <= 0
            or used + reserved + needed > settings.monthly_token_limit
        ):
            status, error_code = "WAITING_BUDGET", "BUDGET_EXHAUSTED"
            error_message = "Daily analysis or monthly token budget is exhausted"
    job = PaperAnalysisJob(
        id=uuid.uuid4(),
        user_id=user_id,
        paper_id=paper_id,
        parsed_document_id=document.id if document else None,
        idempotency_key=idempotency_key,
        input_sha256=input_sha256,
        source_version=str(source_version) if source_version is not None else None,
        analysis_scope=scope,
        analysis_mode=mode,
        provider_key=provider_key,
        model_key=model_key,
        analysis_version=ANALYSIS_VERSION,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        status=status,
        priority=priority,
        part_count=part_count,
        parts_completed=0,
        reserved_tokens=needed if status == "QUEUED" else 0,
        error_code=error_code,
        error_message=error_message,
    )
    try:
        db.add(job)
        # These models have scalar FK values, not ORM relationships. Flush the
        # parent explicitly so immediate PostgreSQL FKs see it before children.
        # Keep this flush inside the idempotency conflict rollback boundary.
        db.flush()
        db.add(
            AnalysisInputSnapshot(
                job_id=job.id,
                payload=input_payload,
                input_sha256=input_sha256,
            )
        )
        for index, section_key, payload, payload_sha256 in part_requests:
            db.add(
                PaperAnalysisPart(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    job_id=job.id,
                    part_index=index,
                    section_key=section_key,
                    request_payload=payload,
                    request_sha256=payload_sha256,
                    status="QUEUED",
                    attempt_count=0,
                )
            )
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == user_id,
                PaperAnalysisJob.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None:
            raise
        require_not_permanently_deleted(db, user_id, concurrent.id)
        return concurrent
    db.refresh(job)
    return job


def retry_analysis(
    db: Session, user_id: uuid.UUID, job_id: uuid.UUID, *, commit: bool = True
) -> PaperAnalysisJob:
    _assert_current_interface(db, user_id, job_id)
    return _retry_analysis_state(db, user_id, job_id, commit=commit)


def _assert_current_interface(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> None:
    row = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.id == job_id, PaperAnalysisJob.user_id == user_id
        )
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    require_not_permanently_deleted(db, user_id, job_id)
    from app.services.current_reading import uses_current_reading_skill

    if not uses_current_reading_skill(db, row):
        raise DomainError(
            "SOURCE_INTERFACE_RETIRED",
            "Submit the original PDF through the skill reading entry",
            409,
        )


def _retry_analysis_state(
    db: Session, user_id: uuid.UUID, job_id: uuid.UUID, *, commit: bool = True
) -> PaperAnalysisJob:
    _lock_owner(db, user_id)
    job = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.id == job_id, PaperAnalysisJob.user_id == user_id
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    require_not_permanently_deleted(db, user_id, job_id)
    if linked_ingest_cleared(db, user_id, job.id):
        raise DomainError("TASK_CLEARED", "Submit a new analysis after clearing its task", 409)
    if job.status not in {
        "FAILED",
        "WAITING_CONFIG",
        "WAITING_BUDGET",
        "WAITING_PROVIDER_QUOTA",
        "WAITING_INPUT_REDUCTION",
        "RETRY_WAIT",
        "CANCELLED",
    }:
        raise DomainError("CONFLICT", "This analysis job cannot be retried", 409)
    if job.status == "CANCELLED" and job.error_code in UNCERTAIN_JOB_CODES:
        raise DomainError("CONFLICT", "Owner acknowledgement is required before retry", 409)
    if job.status == "RETRY_WAIT" and job.error_code == "AI_RATE_LIMITED" and job.next_retry_at:
        next_retry = job.next_retry_at
        if next_retry.tzinfo is None:
            next_retry = next_retry.replace(tzinfo=UTC)
        if next_retry > datetime.now(UTC):
            raise DomainError("RATE_LIMITED", "Wait until the provider retry time", 429)
    settings = analysis_settings(db, user_id)
    snapshot = db.get(AnalysisInputSnapshot, job.id)
    if (
        snapshot is None
        or snapshot.input_sha256 != job.input_sha256
        or _payload_hash(snapshot.payload) != job.input_sha256
    ):
        raise DomainError("INVALID_SNAPSHOT", "Analysis input snapshot is missing", 500)
    request = _frozen_request(snapshot.payload)
    if request.pdf_source is not None:
        from app.services.pdf_reading import validate_pdf_layout

        validate_pdf_layout(db, job, request, snapshot.payload)
    content_chars = sum(len(part.text) for part in request.source_texts)
    parts = list(
        db.scalars(
            select(PaperAnalysisPart)
            .where(PaperAnalysisPart.user_id == user_id, PaperAnalysisPart.job_id == job.id)
            .order_by(PaperAnalysisPart.part_index)
        )
    )
    # Jobs queued before section analysis was introduced can be upgraded from
    # their original frozen snapshot without changing source identity.
    planned_parts = (
        _part_requests(request, settings.max_input_tokens_per_job)
        if request.pdf_source is None
        and not parts
        and job.part_count == 0
        and job.analysis_scope == "FULL_TEXT"
        and content_chars > settings.max_input_tokens_per_job * 2
        else ()
    )
    if parts and (
        len(parts) != job.part_count
        or [part.part_index for part in parts] != list(range(1, job.part_count + 1))
        or any(_payload_hash(part.request_payload) != part.request_sha256 for part in parts)
    ):
        raise DomainError("INVALID_SNAPSHOT", "Analysis parts are incomplete or changed", 500)
    part_requests = [_frozen_request(part.request_payload) for part in parts]
    if request.pdf_source is not None and parts:
        from app.services.pdf_reading import PDF_BATCH_PAGES, validate_pdf_frozen

        for part_request in part_requests:
            validate_pdf_frozen(db, job, part_request)
            assert part_request.pdf_source is not None
            if len(part_request.pdf_source.pages) > PDF_BATCH_PAGES:
                raise DomainError("INVALID_SNAPSHOT", "Original page batch exceeds its bound", 500)
        supplied_pages = tuple(
            page
            for part_request in part_requests
            if part_request.pdf_source is not None and part_request.pdf_source.stage == "READ_PAGES"
            for page in part_request.pdf_source.pages
        )
        if supplied_pages != request.pdf_source.pages:
            raise DomainError("INVALID_SNAPSHOT", "Original PDF page coverage changed", 500)
    if any(
        part_request.title != request.title
        or part_request.year != request.year
        or part_request.abstract != request.abstract
        or part_request.scope != request.scope
        or part_request.mode != request.mode
        or part_request.max_output_tokens != request.max_output_tokens
        or any(source.section_key != part.section_key for source in part_request.source_texts)
        for part, part_request in zip(parts, part_requests, strict=True)
    ):
        raise DomainError("INVALID_SNAPSHOT", "Analysis part metadata differs", 500)
    if parts and not _same_source_texts(
        request.source_texts,
        tuple(text for part_request in part_requests for text in part_request.source_texts),
    ):
        raise DomainError("INVALID_SNAPSHOT", "Analysis parts differ from frozen source text", 500)
    if job.part_count > 0 and not parts:
        raise DomainError("INVALID_SNAPSHOT", "Analysis parts are missing", 500)
    if any(part.status in {"ANALYZING", "NEEDS_ATTENTION"} for part in parts):
        raise DomainError(
            "PART_NEEDS_ATTENTION",
            "An analysis part has an uncertain provider outcome and needs review",
            409,
        )
    if any(
        part.status not in {"QUEUED", "RETRY_WAIT", "FAILED", "COMPLETED", "WAITING_PROVIDER_QUOTA"}
        for part in parts
    ):
        raise DomainError("INVALID_PART_STATUS", "An analysis part has an unknown status", 409)
    remaining_count = (
        len(planned_parts)
        if planned_parts
        else sum(1 for part in parts if part.status != "COMPLETED")
        if parts
        else 1
    )
    if remaining_count:
        if (
            job.prompt_version
            != (_pdf_prompt_version() if job.source_type == "PDF" else PROMPT_VERSION)
            or job.analysis_version != ANALYSIS_VERSION
            or job.schema_version
            != (_pdf_schema_version() if job.source_type == "PDF" else SCHEMA_VERSION)
        ):
            raise DomainError(
                "ANALYSIS_CONFIGURATION_CHANGED",
                "Analysis instructions changed; create a new analysis job",
                409,
            )
        descriptor = ai_provider_descriptor()
        if (
            descriptor.provider_key != job.provider_key
            or descriptor.model_key != job.model_key
            or not descriptor.available
        ):
            raise DomainError(
                "CAPABILITY_UNAVAILABLE",
                "Configured AI model differs; create a new analysis job",
                503,
            )
        if SCOPE_RANK[settings.cloud_scope] < SCOPE_RANK[job.analysis_scope]:
            raise DomainError(
                "CLOUD_SCOPE_NOT_ALLOWED", "Cloud permission does not allow this job's input", 403
            )
        if (
            not uses_provider_quota(settings, job.provider_key)
            and request.max_output_tokens is not None
            and request.max_output_tokens > settings.max_output_tokens_per_job
        ):
            raise DomainError(
                "CONFIGURATION_CHANGED",
                "The frozen output limit exceeds the current analysis setting",
                409,
            )
        if request.pdf_source is None and any(
            sum(len(item.text) for item in part_request.source_texts)
            > _part_char_limit(request, settings.max_input_tokens_per_job)
            for part_request in part_requests
        ):
            raise DomainError(
                "INPUT_TOO_LONG", "A frozen part exceeds the current input limit", 409
            )
        if (
            request.pdf_source is None
            and content_chars > settings.max_input_tokens_per_job * 2
            and not (parts or planned_parts)
        ):
            raise DomainError(
                "INPUT_TOO_LONG", "Input still exceeds the configured single-job limit", 409
            )
    user = db.get(User, user_id)
    assert user is not None
    zone = ZoneInfo(user.timezone)
    today = datetime.now(zone).date()
    day_start, day_end = _day_bounds(today, zone)
    recent = list(
        db.scalars(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == user_id,
                PaperAnalysisJob.id != job.id,
                PaperAnalysisJob.queued_at >= day_start,
                PaperAnalysisJob.queued_at < day_end,
                PaperAnalysisJob.status.in_(["QUEUED", "ANALYZING", "RETRY_WAIT", "COMPLETED"]),
            )
        )
    )
    monthly = list(
        db.scalars(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == user_id,
                PaperAnalysisJob.queued_at >= _month_start(today, zone),
            )
        )
    )
    used = monthly_accounted_tokens(db, monthly, settings)
    reserved = sum(
        item.reserved_tokens
        for item in monthly
        if item.id != job.id and item.status in {"QUEUED", "ANALYZING", "RETRY_WAIT"}
    )
    needed = remaining_count * (
        settings.max_input_tokens_per_job + settings.max_output_tokens_per_job
    )
    if remaining_count and settings.budget_mode == "PROVIDER_QUOTA" and job.provider_key != "codex":
        raise DomainError("BUDGET_MODE_UNSUPPORTED", "Provider quota mode requires Codex", 409)
    if (
        remaining_count
        and not uses_provider_quota(settings, job.provider_key)
        and (
            len(recent) >= settings.daily_analysis_limit
            or settings.monthly_token_limit <= 0
            or used + reserved + needed > settings.monthly_token_limit
        )
    ):
        raise DomainError("BUDGET_EXHAUSTED", "Daily or monthly AI budget is exhausted", 409)
    for index, section_key, payload, payload_sha256 in planned_parts:
        db.add(
            PaperAnalysisPart(
                id=uuid.uuid4(),
                user_id=user_id,
                job_id=job.id,
                part_index=index,
                section_key=section_key,
                request_payload=payload,
                request_sha256=payload_sha256,
                status="QUEUED",
                attempt_count=0,
            )
        )
    if planned_parts:
        job.part_count = len(planned_parts)
        job.parts_completed = 0
    elif parts:
        job.parts_completed = job.part_count - remaining_count
        for part in parts:
            if part.status in {"FAILED", "RETRY_WAIT", "WAITING_PROVIDER_QUOTA"}:
                part.status = "QUEUED"
                part.error_code = None
                part.error_message = None
    job.status = "QUEUED"
    job.error_code = None
    job.error_message = None
    job.next_retry_at = None
    job.reserved_tokens = needed
    if remaining_count:
        job.queued_at = datetime.now(UTC)
    job.started_at = None
    job.completed_at = None
    # Attempts are monotonic identities for immutable unknown-outcome entries.
    # After exhausting automatic retries an owner retry authorizes one new call.
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()
    return job


def cancel_analysis(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> PaperAnalysisJob:
    """Stop future calls; cancelling an unknown result retains its budget entry."""
    _lock_owner(db, user_id)
    job = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.id == job_id,
            PaperAnalysisJob.user_id == user_id,
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    if job.status not in {
        "QUEUED",
        "WAITING_CONFIG",
        "WAITING_BUDGET",
        "WAITING_PROVIDER_QUOTA",
        "RETRY_WAIT",
        "NEEDS_ATTENTION",
    }:
        raise DomainError("CONFLICT", "This job cannot be cancelled in its current state", 409)
    if job.status == "NEEDS_ATTENTION":
        parts = list(
            db.scalars(
                select(PaperAnalysisPart).where(
                    PaperAnalysisPart.job_id == job.id,
                    PaperAnalysisPart.user_id == user_id,
                )
            )
        )
        for part in parts:
            if part.status == "NEEDS_ATTENTION":
                record_uncertain_call(db, job, part)
        if not parts:
            record_uncertain_call(db, job)
        job.error_code = (
            job.error_code
            if job.error_code in UNCERTAIN_JOB_CODES
            else "ANALYSIS_OUTCOME_UNCERTAIN"
        )
    job.status = "CANCELLED"
    job.reserved_tokens = 0
    job.next_retry_at = None
    db.commit()
    return job


def acknowledge_uncertain_analysis(
    db: Session, user_id: uuid.UUID, job_id: uuid.UUID
) -> PaperAnalysisJob:
    _assert_current_interface(db, user_id, job_id)
    return _acknowledge_analysis_state(db, user_id, job_id)


def _pdf_prompt_version() -> str:
    from app.services.pdf_reading import PDF_PROMPT_VERSION

    return PDF_PROMPT_VERSION


def _pdf_schema_version() -> str:
    from app.services.pdf_reading import CANONICAL_SCHEMA_VERSION

    return CANONICAL_SCHEMA_VERSION


def _acknowledge_analysis_state(
    db: Session, user_id: uuid.UUID, job_id: uuid.UUID
) -> PaperAnalysisJob:
    """Owner explicitly accepts possible duplicate billing before another call."""
    _lock_owner(db, user_id)
    job = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.id == job_id, PaperAnalysisJob.user_id == user_id
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    require_not_permanently_deleted(db, user_id, job_id)
    if job.status != "NEEDS_ATTENTION" and not (
        job.status == "CANCELLED" and job.error_code in UNCERTAIN_JOB_CODES
    ):
        raise DomainError("CONFLICT", "This job has no uncertain provider outcome", 409)
    parts = list(
        db.scalars(
            select(PaperAnalysisPart).where(
                PaperAnalysisPart.job_id == job.id, PaperAnalysisPart.user_id == user_id
            )
        )
    )
    if any(part.status == "ANALYZING" for part in parts):
        raise DomainError("CONFLICT", "Wait for stale-call recovery before retrying", 409)
    for part in parts:
        if part.status == "NEEDS_ATTENTION":
            record_uncertain_call(db, job, part)
            part.status = "FAILED"
    if not parts:
        record_uncertain_call(db, job)
    job.status = "FAILED"
    db.flush()
    try:
        return _retry_analysis_state(db, user_id, job_id)
    except Exception:
        db.rollback()
        raise
