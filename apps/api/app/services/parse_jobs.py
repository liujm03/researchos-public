import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.paper_parser import PaperParser
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import Attachment, PaperAttachment, PaperParseJob
from app.services.papers import get_paper
from app.services.parsed_documents import parse_attachment


def enqueue_parse_job(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    parser: PaperParser,
    *,
    suppress_auto_analysis: bool = False,
    commit: bool = True,
) -> PaperParseJob:
    get_paper(db, user_id, paper_id)
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.user_id == user_id,
            Attachment.deleted_at.is_(None),
        )
    )
    linked = db.scalar(
        select(PaperAttachment.id).where(
            PaperAttachment.paper_id == paper_id,
            PaperAttachment.attachment_id == attachment_id,
        )
    )
    if attachment is None or linked is None:
        raise DomainError("NOT_FOUND", "Paper PDF attachment not found", 404)
    material = (
        f"{paper_id}:{attachment.id}:{attachment.sha256}:"
        f"{parser.parser_name}:{parser.parser_version}"
    )
    if suppress_auto_analysis:
        material += ":suppress_auto_analysis=True"
    key = hashlib.sha256(material.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(PaperParseJob).where(
            PaperParseJob.user_id == user_id,
            PaperParseJob.paper_id == paper_id,
            PaperParseJob.attachment_id == attachment_id,
            PaperParseJob.parser_name == parser.parser_name,
            PaperParseJob.parser_version == parser.parser_version,
            PaperParseJob.suppress_auto_analysis == suppress_auto_analysis,
        )
    )
    if existing is not None:
        return existing
    job = PaperParseJob(
        id=uuid.uuid4(),
        user_id=user_id,
        paper_id=paper_id,
        attachment_id=attachment_id,
        parser_name=parser.parser_name,
        parser_version=parser.parser_version,
        idempotency_key=key,
        suppress_auto_analysis=suppress_auto_analysis,
        status="QUEUED",
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
            select(PaperParseJob).where(
                PaperParseJob.user_id == user_id, PaperParseJob.idempotency_key == key
            )
        )
        if concurrent is None:
            raise
        return concurrent
    db.refresh(job)
    return job


async def process_parse_job(
    db: Session,
    job_id: uuid.UUID,
    parser: PaperParser,
    storage: StorageProvider,
) -> PaperParseJob:
    job = db.get(PaperParseJob, job_id)
    if job is None:
        raise DomainError("NOT_FOUND", "Parse job not found", 404)
    if job.status != "QUEUED":
        return job
    if job.parser_name != parser.parser_name or job.parser_version != parser.parser_version:
        job.status = "FAILED"
        job.error_code = "PARSER_VERSION_MISMATCH"
        job.error_message = "Configured parser differs from this job"
        db.commit()
        return job
    job.status = "PARSING"
    job.attempt_count += 1
    job.started_at = datetime.now(UTC)
    db.commit()
    try:
        document = await parse_attachment(
            db, job.user_id, job.paper_id, job.attachment_id, storage, parser, commit=False
        )
        # Clear may run while parsing I/O is in flight. Keep extracted source
        # records, but do not revive the owner's cancelled task.
        with db.no_autoflush:
            current_status = db.scalar(
                select(PaperParseJob.status)
                .where(
                    PaperParseJob.id == job.id,
                    PaperParseJob.user_id == job.user_id,
                )
                .with_for_update()
            )
        if current_status == "CANCELLED":
            job.status = "CANCELLED"
            job.parsed_document_id = document.id
            db.commit()
            return job
        job.parsed_document_id = document.id
        job.status = "COMPLETED"
        job.completed_at = datetime.now(UTC)
        db.commit()
        # Parsing preserves source text. Only a separate owner submission can
        # authorize analysis, including when an old stored auto flag is true.
        return job
    except Exception as exc:
        db.rollback()
        failed = db.get(PaperParseJob, job_id)
        assert failed is not None
        if failed.status == "CANCELLED":
            return failed
        failed.status = "FAILED"
        failed.error_code = exc.code if isinstance(exc, DomainError) else "PARSE_FAILED"
        failed.error_message = (
            str(exc)[:2000] if isinstance(exc, DomainError) else "PDF parsing failed"
        )
        db.commit()
        return failed


async def process_next_parse_job(
    db: Session, parser: PaperParser, storage: StorageProvider
) -> PaperParseJob | None:
    job = db.scalar(
        select(PaperParseJob)
        .where(PaperParseJob.status == "QUEUED")
        .order_by(PaperParseJob.queued_at, PaperParseJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    return await process_parse_job(db, job.id, parser, storage)
