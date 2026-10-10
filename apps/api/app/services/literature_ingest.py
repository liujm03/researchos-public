"""Durable, explicitly requested Zotero single-paper ingest.

Each stage commits its own durable pointer. Replaying after a worker crash reuses
source, PDF, parse, and analysis idempotency keys instead of repeating their work.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.ai import AnalysisMode
from app.domain.reference_manager import ReferenceAttachment, ReferenceManagerProvider
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import (
    InboxItem,
    LiteratureIngestCandidate,
    LiteratureIngestJob,
    PaperAnalysisJob,
    PaperParseJob,
    PaperResearchNote,
    PaperSource,
    ZoteroSourceItem,
)
from app.providers.paper_parser.pdfplumber_parser import PdfPlumberParser
from app.providers.registry import ai_provider_descriptor
from app.services.paper_analysis import enqueue_analysis, retry_analysis
from app.services.paper_attachments import copy_zotero_pdf
from app.services.parse_jobs import enqueue_parse_job
from app.services.reference_manager import import_zotero_item
from app.services.zotero_sync import sync_zotero

CHILD_TYPES = {"attachment", "note", "annotation"}
CHECK_DELAY = timedelta(seconds=5)
LEASE_DURATION = timedelta(minutes=30)


class IngestStopped(Exception):
    """Owner cancellation/clearing won over a late worker response."""


def _guard_ingest(db: Session, job: LiteratureIngestJob, *, lock: bool = False) -> None:
    query = select(LiteratureIngestJob.status, LiteratureIngestJob.cleared_at).where(
        LiteratureIngestJob.id == job.id,
        LiteratureIngestJob.user_id == job.user_id,
    )
    if lock:
        query = query.with_for_update()
    with db.no_autoflush:
        current = db.execute(query).one_or_none()
    if current is None or current.status == "CANCELLED" or current.cleared_at is not None:
        raise IngestStopped


async def _identity(provider: ReferenceManagerProvider) -> tuple[str, str, str]:
    status = await provider.status()
    server_id = status.get("server_id")
    library_type = status.get("library_type") or "user"
    library_id = status.get("library_id") or "0"
    if (
        not isinstance(server_id, str)
        or not server_id
        or library_type not in {"user", "group"}
        or not isinstance(library_id, str)
        or not library_id
        or (provider.provider_key == "zotero_local" and (library_type, library_id) != ("user", "0"))
    ):
        raise DomainError("PROVIDER_UNAVAILABLE", "Invalid Zotero library identity", 503)
    return server_id, library_type, library_id


def _pdf_attachment_fingerprint(attachments: list[ReferenceAttachment]) -> str:
    versions = sorted(
        (attachment.key, attachment.version)
        for attachment in attachments
        if attachment.content_type == "application/pdf"
    )
    encoded = json.dumps(versions, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_item(db: Session, job: LiteratureIngestJob) -> ZoteroSourceItem | None:
    return db.scalar(
        select(ZoteroSourceItem)
        .join(PaperSource, PaperSource.id == ZoteroSourceItem.paper_source_id)
        .where(
            ZoteroSourceItem.user_id == job.user_id,
            ZoteroSourceItem.server_id == job.server_id,
            ZoteroSourceItem.library_type == job.library_type,
            ZoteroSourceItem.library_id == job.library_id,
            ZoteroSourceItem.item_key == job.item_key,
            PaperSource.provider_key == job.provider_key,
        )
    )


async def enqueue_ingest(
    db: Session,
    user_id: uuid.UUID,
    provider: ReferenceManagerProvider,
    item_key: str,
    *,
    copy_pdf: bool = False,
    request_analysis: bool = False,
    analysis_mode: AnalysisMode = "STANDARD",
    expected_provider: str | None = None,
    expected_source_version: int | None = None,
    commit: bool = True,
) -> LiteratureIngestJob:
    if request_analysis:
        raise DomainError(
            "SOURCE_INTERFACE_RETIRED",
            "Submit the original PDF separately through the skill reading entry",
            422,
        )
    if expected_provider is not None and expected_provider != provider.provider_key:
        raise DomainError("PROVIDER_MISMATCH", "Requested Zotero provider is not configured", 409)
    server_id, library_type, library_id = await _identity(provider)
    item = await provider.get_item(item_key)
    if item is None or item.item_type in CHILD_TYPES:
        raise DomainError("NOT_FOUND", "Zotero paper item not found", 404)
    if expected_source_version is not None and item.version != expected_source_version:
        raise DomainError("SOURCE_CHANGED", "Zotero item changed during this sync", 409)
    attachment_fingerprint = (
        _pdf_attachment_fingerprint(await provider.list_attachments(item_key)) if copy_pdf else None
    )
    material = json.dumps(
        [
            str(user_id),
            provider.provider_key,
            server_id,
            library_type,
            library_id,
            item_key,
            item.version,
            copy_pdf,
            request_analysis,
            analysis_mode,
            attachment_fingerprint,
        ],
        separators=(",", ":"),
    )
    key = hashlib.sha256(material.encode()).hexdigest()
    existing = db.scalar(
        select(LiteratureIngestJob).where(
            LiteratureIngestJob.user_id == user_id,
            LiteratureIngestJob.idempotency_key == key,
        )
    )
    while existing is not None and existing.cleared_at is not None:
        key = hashlib.sha256(f"{key}:cleared:{existing.id}".encode()).hexdigest()
        existing = db.scalar(
            select(LiteratureIngestJob).where(
                LiteratureIngestJob.user_id == user_id,
                LiteratureIngestJob.idempotency_key == key,
            )
        )
    if existing is not None:
        return existing
    job = LiteratureIngestJob(
        id=uuid.uuid4(),
        user_id=user_id,
        provider_key=provider.provider_key,
        server_id=server_id,
        library_type=library_type,
        library_id=library_id,
        item_key=item_key,
        item_title=item.title,
        source_version=item.version,
        attachment_fingerprint=attachment_fingerprint,
        idempotency_key=key,
        copy_pdf=copy_pdf,
        request_analysis=request_analysis,
        analysis_mode=analysis_mode,
        status="QUEUED",
        stage="SYNC",
        attempt_count=0,
    )
    db.add(job)
    if not commit:
        db.flush()
        return job
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(LiteratureIngestJob).where(
                LiteratureIngestJob.user_id == user_id,
                LiteratureIngestJob.idempotency_key == key,
            )
        )
        if concurrent is None:
            raise
        return concurrent
    db.refresh(job)
    return job


def get_ingest(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> LiteratureIngestJob:
    job = db.scalar(
        select(LiteratureIngestJob).where(
            LiteratureIngestJob.id == job_id, LiteratureIngestJob.user_id == user_id
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Literature ingest job not found", 404)
    return job


def list_ingests(db: Session, user_id: uuid.UUID, limit: int = 50) -> list[LiteratureIngestJob]:
    return list(
        db.scalars(
            select(LiteratureIngestJob)
            .where(LiteratureIngestJob.user_id == user_id, LiteratureIngestJob.cleared_at.is_(None))
            .order_by(LiteratureIngestJob.created_at.desc(), LiteratureIngestJob.id.desc())
            .limit(limit)
        )
    )


def candidate_ids(db: Session, job_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(LiteratureIngestCandidate.paper_id)
            .where(LiteratureIngestCandidate.job_id == job_id)
            .order_by(LiteratureIngestCandidate.paper_id)
        )
    )


async def resolve_ingest_paper(
    db: Session,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    paper_id: uuid.UUID,
    provider: ReferenceManagerProvider,
) -> LiteratureIngestJob:
    job = get_ingest(db, user_id, job_id)
    if job.cleared_at is not None:
        raise DomainError("TASK_CLEARED", "Cleared literature tasks cannot be resumed", 409)
    if job.status not in {"FAILED", "WAITING_REVIEW"} or job.stage != "SYNC":
        raise DomainError("CONFLICT", "This ingest job has no paper candidate to resolve", 409)
    if paper_id not in candidate_ids(db, job.id):
        raise DomainError("NOT_FOUND", "Paper is not a candidate for this ingest job", 404)
    if provider.provider_key != job.provider_key or await _identity(provider) != (
        job.server_id,
        job.library_type,
        job.library_id,
    ):
        raise DomainError("PROVIDER_MISMATCH", "Configured Zotero library changed", 409)
    item = await provider.get_item(job.item_key)
    _guard_ingest(db, job, lock=True)
    if item is None or item.version != job.source_version:
        raise DomainError("SOURCE_CHANGED", "Zotero item changed; enqueue its new version", 409)
    imported = await import_zotero_item(db, user_id, job.item_key, provider, paper_id)
    _guard_ingest(db, job, lock=True)
    if imported.id != paper_id:
        raise DomainError("CONFLICT", "Zotero item is already linked to another paper", 409)
    job.paper_id = paper_id
    job.status = "QUEUED"
    job.error_code = None
    job.error_message = None
    job.lease_expires_at = None
    job.next_check_at = None
    db.commit()
    return job


def _advance(job: LiteratureIngestJob, stage: str) -> None:
    job.stage = stage
    job.status = "COMPLETED" if stage == "DONE" else "QUEUED"
    job.lease_expires_at = None
    job.next_check_at = None
    job.error_code = None
    job.error_message = None


def _wait(
    job: LiteratureIngestJob, status: str, code: str | None = None, message: str | None = None
) -> None:
    job.status = status
    job.lease_expires_at = None
    job.next_check_at = (
        datetime.now(UTC) + CHECK_DELAY if status in {"WAITING_PARSE", "WAITING_ANALYSIS"} else None
    )
    job.error_code = code
    job.error_message = message


async def process_ingest_job(
    db: Session,
    job_id: uuid.UUID,
    provider: ReferenceManagerProvider | None,
    storage: StorageProvider,
    parser: PdfPlumberParser,
) -> LiteratureIngestJob:
    job = db.get(LiteratureIngestJob, job_id)
    if job is None:
        raise DomainError("NOT_FOUND", "Literature ingest job not found", 404)
    if job.cleared_at is not None:
        return job
    if job.request_analysis:
        job.status = "FAILED"
        job.error_code = "SOURCE_INTERFACE_RETIRED"
        job.error_message = "Submit the original PDF separately through the skill reading entry"
        job.lease_expires_at = None
        job.next_check_at = None
        db.commit()
        return job
    if job.status not in {"QUEUED", "WAITING_PARSE", "WAITING_ANALYSIS", "RUNNING"}:
        return job
    now = datetime.now(UTC)
    if job.status == "RUNNING" and job.lease_expires_at:
        lease = job.lease_expires_at
        if (lease.replace(tzinfo=UTC) if lease.tzinfo is None else lease) > now:
            return job
    if job.next_check_at:
        check = job.next_check_at
        if (check.replace(tzinfo=UTC) if check.tzinfo is None else check) > now:
            return job
    if job.stage in {"SYNC", "COPY"}:
        if provider is None or provider.provider_key != job.provider_key:
            _wait(job, "WAITING_CONFIG", "PROVIDER_CHANGED", "Configured Zotero provider changed")
            db.commit()
            return job
        try:
            observed_identity = await _identity(provider)
            _guard_ingest(db, job, lock=True)
            if observed_identity != (job.server_id, job.library_type, job.library_id):
                _wait(job, "WAITING_CONFIG", "LIBRARY_CHANGED", "Configured Zotero library changed")
                db.commit()
                return job
        except IngestStopped:
            db.rollback()
            db.refresh(job)
            return job
        except DomainError as exc:
            try:
                _guard_ingest(db, job, lock=True)
            except IngestStopped:
                db.rollback()
                db.refresh(job)
                return job
            _wait(job, "WAITING_CONFIG", exc.code, exc.message)
            db.commit()
            return job

    manual_resume = job.status == "QUEUED" and job.analysis_job_id is not None
    job.status = "RUNNING"
    job.lease_expires_at = now + LEASE_DURATION
    job.next_check_at = None
    job.attempt_count += 1
    db.commit()
    try:
        if job.stage == "SYNC":
            assert provider is not None
            item = await provider.get_item(job.item_key)
            _guard_ingest(db, job)
            if item is None or item.version != job.source_version:
                raise DomainError(
                    "SOURCE_CHANGED", "Zotero item changed; enqueue its new version", 409
                )
            result = await sync_zotero(
                db,
                job.user_id,
                provider,
                item_key=job.item_key,
                idempotency_key=f"{job.id}:{job.attempt_count}",
            )
            _guard_ingest(db, job, lock=True)
            if result.status != "COMPLETED":
                duplicate = next(
                    (
                        error
                        for error in result.errors
                        if error.get("code") == "DUPLICATE_CANDIDATE"
                    ),
                    None,
                )
                if duplicate is not None:
                    raw_candidates = duplicate.get("candidate_paper_ids")
                    if isinstance(raw_candidates, list):
                        for value in raw_candidates:
                            try:
                                candidate_id = uuid.UUID(str(value))
                            except ValueError:
                                continue
                            if db.get(LiteratureIngestCandidate, (job.id, candidate_id)) is None:
                                db.add(
                                    LiteratureIngestCandidate(job_id=job.id, paper_id=candidate_id)
                                )
                    _wait(
                        job,
                        "WAITING_REVIEW",
                        "DUPLICATE_CANDIDATE",
                        str(duplicate.get("error") or "Choose the matching paper"),
                    )
                    db.commit()
                    return job
                raise DomainError("SYNC_FAILED", "Zotero single-paper sync did not complete", 503)
            source = _source_item(db, job)
            if source is None or source.item_version != job.source_version:
                raise DomainError("SOURCE_CHANGED", "Synced Zotero source version differs", 409)
            link = db.get(PaperSource, source.paper_source_id)
            assert link is not None
            job.paper_id = link.paper_id
            _advance(job, "COPY" if job.copy_pdf else "ANALYZE" if job.request_analysis else "DONE")
        elif job.stage == "COPY":
            assert provider is not None
            assert job.paper_id is not None
            item = await provider.get_item(job.item_key)
            _guard_ingest(db, job)
            if item is None or item.version != job.source_version:
                raise DomainError("SOURCE_CHANGED", "Zotero item changed before PDF copy", 409)
            indexed_attachments = await provider.list_attachments(job.item_key)
            _guard_ingest(db, job)
            if (
                job.attachment_fingerprint is not None
                and _pdf_attachment_fingerprint(indexed_attachments) != job.attachment_fingerprint
            ):
                raise DomainError(
                    "ATTACHMENT_CHANGED",
                    "Zotero PDF attachments changed; enqueue the current item version again",
                    409,
                )
            candidates = sorted(
                (
                    attachment
                    for attachment in indexed_attachments
                    if attachment.content_type == "application/pdf"
                ),
                key=lambda attachment: (attachment.title.casefold(), attachment.key),
            )
            if not candidates:
                job.warning_code = "PDF_UNAVAILABLE"
                job.warning_message = (
                    "No accessible Zotero PDF; analysis will use abstract or metadata"
                )
                _advance(job, "ANALYZE" if job.request_analysis else "DONE")
            else:
                inaccessible: list[str] = []
                for candidate in candidates:
                    try:
                        attachment, _ = await copy_zotero_pdf(
                            db,
                            job.user_id,
                            job.paper_id,
                            job.item_key,
                            candidate.key,
                            provider,
                            storage,
                        )
                        _guard_ingest(db, job, lock=True)
                        job.attachment_id = attachment.id
                        _advance(job, "PARSE")
                        break
                    except DomainError as exc:
                        if exc.code not in {
                            "NOT_FOUND",
                            "PROVIDER_AUTH_ERROR",
                            "INVALID_PDF",
                            "FILE_TOO_LARGE",
                        }:
                            raise
                        inaccessible.append(candidate.key)
                else:
                    job.warning_code = "PDF_UNAVAILABLE"
                    job.warning_message = (
                        f"No accessible Zotero PDF ({len(inaccessible)} candidate(s)); "
                        "analysis will use abstract or metadata"
                    )
                    _advance(job, "ANALYZE" if job.request_analysis else "DONE")
        elif job.stage == "PARSE":
            _guard_ingest(db, job, lock=True)
            assert job.paper_id is not None and job.attachment_id is not None
            parse = db.get(PaperParseJob, job.parse_job_id) if job.parse_job_id else None
            if parse is None:
                parse = enqueue_parse_job(
                    db,
                    job.user_id,
                    job.paper_id,
                    job.attachment_id,
                    parser,
                    suppress_auto_analysis=True,
                    commit=False,
                )
                job.parse_job_id = parse.id
            if parse.status == "COMPLETED":
                _advance(job, "ANALYZE" if job.request_analysis else "DONE")
            elif parse.status in {"QUEUED", "PARSING"}:
                _wait(job, "WAITING_PARSE")
            else:
                raise DomainError("PARSE_FAILED", parse.error_message or "PDF parsing failed", 409)
        elif job.stage == "ANALYZE":
            _guard_ingest(db, job, lock=True)
            assert job.paper_id is not None
            analysis = (
                db.get(PaperAnalysisJob, job.analysis_job_id) if job.analysis_job_id else None
            )
            if (
                analysis is not None
                and analysis.status
                in {
                    "FAILED",
                    "CANCELLED",
                    "WAITING_CONFIG",
                    "WAITING_BUDGET",
                    "WAITING_INPUT_REDUCTION",
                    "WAITING_PROVIDER_QUOTA",
                }
                and manual_resume
            ):
                # A manual ingest retry resumed this stage. Preserve the original
                # immutable AI input when possible; a changed model gets a new job.
                descriptor = ai_provider_descriptor()
                if (
                    analysis.provider_key != descriptor.provider_key
                    or analysis.model_key != descriptor.model_key
                ):
                    analysis = None
                    job.analysis_job_id = None
                else:
                    try:
                        analysis = retry_analysis(db, job.user_id, analysis.id, commit=False)
                    except DomainError as exc:
                        waiting = (
                            "WAITING_BUDGET" if exc.code == "BUDGET_EXHAUSTED" else "WAITING_CONFIG"
                        )
                        if exc.code == "INPUT_TOO_LONG":
                            waiting = "WAITING_INPUT_REDUCTION"
                        _wait(job, waiting, exc.code, exc.message)
                        db.commit()
                        return job
            if analysis is None:
                analysis = enqueue_analysis(
                    db,
                    job.user_id,
                    job.paper_id,
                    job.analysis_mode,  # type: ignore[arg-type]
                    commit=False,
                )
                job.analysis_job_id = analysis.id
            if analysis.status == "COMPLETED":
                _advance(job, "INBOX")
            elif analysis.status in {"QUEUED", "ANALYZING", "RETRY_WAIT"}:
                _wait(job, "WAITING_ANALYSIS")
            elif analysis.status in {
                "WAITING_CONFIG",
                "WAITING_BUDGET",
                "WAITING_INPUT_REDUCTION",
                "WAITING_PROVIDER_QUOTA",
            }:
                _wait(job, analysis.status, analysis.error_code, analysis.error_message)
            else:
                raise DomainError(
                    "ANALYSIS_FAILED", analysis.error_message or "Analysis failed", 409
                )
        elif job.stage == "INBOX":
            assert job.analysis_job_id is not None
            note = db.scalar(
                select(PaperResearchNote).where(
                    PaperResearchNote.user_id == job.user_id,
                    PaperResearchNote.analysis_job_id == job.analysis_job_id,
                )
            )
            inbox = (
                db.scalar(
                    select(InboxItem).where(
                        InboxItem.user_id == job.user_id, InboxItem.note_id == note.id
                    )
                )
                if note is not None
                else None
            )
            if inbox is None:
                raise DomainError("INBOX_MISSING", "Analysis completed without an Inbox item", 500)
            job.inbox_item_id = inbox.id
            _advance(job, "DONE")
        else:
            raise DomainError("INVALID_STAGE", "Unknown literature ingest stage", 500)
        _guard_ingest(db, job, lock=True)
        db.commit()
        db.refresh(job)
        return job
    except IngestStopped:
        db.rollback()
        db.refresh(job)
        return job
    except Exception as exc:
        db.rollback()
        failed = db.get(LiteratureIngestJob, job_id)
        assert failed is not None
        if failed.cleared_at is not None or failed.status == "CANCELLED":
            return failed
        failed.status = "FAILED"
        failed.lease_expires_at = None
        failed.next_check_at = None
        failed.error_code = exc.code if isinstance(exc, DomainError) else "INGEST_FAILED"
        failed.error_message = (
            exc.message
            if isinstance(exc, DomainError)
            else "Literature ingest failed; inspect worker logs"
        )
        db.commit()
        return failed


async def process_next_ingest_job(
    db: Session,
    provider: ReferenceManagerProvider | None,
    storage: StorageProvider,
    parser: PdfPlumberParser,
) -> LiteratureIngestJob | None:
    now = datetime.now(UTC)
    job = db.scalar(
        select(LiteratureIngestJob)
        .where(
            LiteratureIngestJob.cleared_at.is_(None),
            or_(
                LiteratureIngestJob.status == "QUEUED",
                LiteratureIngestJob.status.in_(["WAITING_PARSE", "WAITING_ANALYSIS"]),
                (LiteratureIngestJob.status == "RUNNING")
                & (LiteratureIngestJob.lease_expires_at <= now),
            ),
            or_(
                LiteratureIngestJob.next_check_at.is_(None),
                LiteratureIngestJob.next_check_at <= now,
            ),
        )
        .order_by(LiteratureIngestJob.created_at, LiteratureIngestJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    return await process_ingest_job(db, job.id, provider, storage, parser)


def retry_ingest(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> LiteratureIngestJob:
    job = get_ingest(db, user_id, job_id)
    if job.cleared_at is not None:
        raise DomainError("TASK_CLEARED", "Cleared literature tasks cannot be retried", 409)
    if job.status not in {
        "FAILED",
        "CANCELLED",
        "WAITING_CONFIG",
        "WAITING_BUDGET",
        "WAITING_INPUT_REDUCTION",
        "WAITING_PROVIDER_QUOTA",
    }:
        raise DomainError("CONFLICT", "This ingest job cannot be retried", 409)
    if job.stage == "PARSE" and job.parse_job_id:
        parse = db.get(PaperParseJob, job.parse_job_id)
        if parse is not None and parse.status in {"FAILED", "CANCELLED"}:
            parse.status = "QUEUED"
            parse.error_code = None
            parse.error_message = None
            parse.started_at = None
            parse.completed_at = None
    job.status = "QUEUED"
    job.error_code = None
    job.error_message = None
    job.lease_expires_at = None
    job.next_check_at = None
    db.commit()
    return job


def cancel_ingest(
    db: Session,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    allow_in_flight: bool = False,
    commit: bool = True,
) -> LiteratureIngestJob:
    job = get_ingest(db, user_id, job_id)
    if job.status in {"COMPLETED", "CANCELLED"}:
        raise DomainError("CONFLICT", "This ingest job cannot be cancelled", 409)
    if job.status == "RUNNING" and not allow_in_flight:
        raise DomainError("CONFLICT", "Ingest stage is running; retry cancellation later", 409)
    if job.parse_job_id:
        parse = db.scalar(
            select(PaperParseJob)
            .where(
                PaperParseJob.id == job.parse_job_id,
                PaperParseJob.user_id == user_id,
            )
            .with_for_update()
        )
        if parse is not None and parse.status == "PARSING" and not allow_in_flight:
            raise DomainError("CONFLICT", "PDF parsing is in progress", 409)
        if parse is not None and parse.status in {"QUEUED", "PARSING"}:
            parse.status = "CANCELLED"
    if job.analysis_job_id:
        analysis = db.scalar(
            select(PaperAnalysisJob)
            .where(
                PaperAnalysisJob.id == job.analysis_job_id,
                PaperAnalysisJob.user_id == user_id,
            )
            .with_for_update()
        )
        if analysis is not None and analysis.status == "ANALYZING" and not allow_in_flight:
            raise DomainError("CONFLICT", "AI analysis is in progress", 409)
        if analysis is not None and analysis.status in {
            "QUEUED",
            "RETRY_WAIT",
            "WAITING_CONFIG",
            "WAITING_BUDGET",
            "WAITING_INPUT_REDUCTION",
            "WAITING_PROVIDER_QUOTA",
            "ANALYZING",
            "NEEDS_ATTENTION",
        }:
            analysis.status = "CANCELLED"
            analysis.reserved_tokens = 0
    job.status = "CANCELLED"
    job.lease_expires_at = None
    job.next_check_at = None
    if commit:
        db.commit()
    return job


def clear_ingests(db: Session, user_id: uuid.UUID) -> dict[str, int]:
    """Clear the visible task list, keeping every research object and receipt."""
    jobs = list(
        db.scalars(
            select(LiteratureIngestJob)
            .where(
                LiteratureIngestJob.user_id == user_id,
                LiteratureIngestJob.cleared_at.is_(None),
            )
            .order_by(LiteratureIngestJob.id)
            .with_for_update()
        )
    )
    cancelled = 0
    now = datetime.now(UTC)
    for job in jobs:
        if job.status not in {"COMPLETED", "CANCELLED"}:
            cancel_ingest(db, user_id, job.id, allow_in_flight=True, commit=False)
            cancelled += 1
        job.cleared_at = now
        job.lease_expires_at = None
        job.next_check_at = None
    db.commit()
    return {"cleared": len(jobs), "cancelled": cancelled}
