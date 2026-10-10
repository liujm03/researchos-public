"""Direct original-page analysis source preparation; no parsed text or AI call."""

import asyncio
import hashlib
import uuid
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.ai import NoteOutputContract, PaperAnalysisRequest, PDFReadingSource
from app.domain.note_output import NoteOutputProvider
from app.domain.pdf_reading import PDFVisualProvider, ReadingSkillProvider, ReadingSkillReceipt
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models import (
    AnalysisInputSnapshot,
    Attachment,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperAttachment,
    PaperPDFReadingSource,
    User,
    ZoteroSourceItem,
)
from app.models_analytical import PaperReadingApproval, PaperReadingApprovalPlan
from app.providers.registry import (
    ai_provider_descriptor,
    pdf_visual_provider,
    storage_provider,
)
from app.services.note_deletion_state import (
    require_not_permanently_deleted,
    require_output_path_available,
)
from app.services.note_trash import require_selectable_job
from app.services.paper_analysis import (
    ANALYSIS_VERSION,
    _day_bounds,
    _lock_owner,
    _month_start,
    _payload_hash,
    analysis_settings,
    linked_ingest_cleared,
    monthly_accounted_tokens,
    uses_provider_quota,
)
from app.services.papers import get_paper

PDF_BATCH_PAGES = 20
LEGACY_PDF_PROMPT_VERSION = "2026-10-03-analytical-writer-v2"
PDF_PROMPT_VERSION = "2026-10-07-canonical-markdown-v3"
CANONICAL_SCHEMA_VERSION = "canonical-markdown-v2"


def source_descriptor(payload: dict[str, object]) -> PDFReadingSource | None:
    raw = payload.get("pdf_source")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DomainError("INVALID_SNAPSHOT", "Original PDF source descriptor is invalid", 500)
    try:
        pages = raw["pages"]
        if not isinstance(pages, (list, tuple)):
            raise ValueError("pages")
        source = PDFReadingSource(
            attachment_id=uuid.UUID(str(raw["attachment_id"])),
            sha256=str(raw["sha256"]),
            page_count=int(str(raw["page_count"])),
            pages=tuple(int(str(page)) for page in pages),
            skill_key=str(raw["skill_key"]),
            skill_version=str(raw["skill_version"]),
            skill_instructions=str(raw["skill_instructions"]),
            skill_sha256=str(raw["skill_sha256"]),
            render_version=str(raw["render_version"]),
            template_text=str(raw["template_text"])
            if raw.get("template_text") is not None
            else None,
            template_sha256=str(raw["template_sha256"])
            if raw.get("template_sha256") is not None
            else None,
            stage=raw.get("stage", "WRITE_NOTE"),
            note_output_contract=raw.get("note_output_contract", "PAPER_ANALYSIS_V1"),
        )
        if (
            source.stage not in {"READ_PAGES", "WRITE_NOTE"}
            or source.note_output_contract not in {"PAPER_ANALYSIS_V1", "CANONICAL_MARKDOWN_V2"}
            or source.page_count < 1
            or len(set(source.pages)) != len(source.pages)
            or not source.pages
            or any(not 1 <= page <= source.page_count for page in source.pages)
        ):
            raise ValueError("page range")
        if (
            hashlib.sha256(source.skill_instructions.encode("utf-8")).hexdigest()
            != source.skill_sha256
        ):
            raise ValueError("skill hash")
        if (
            source.template_text is not None
            and hashlib.sha256(source.template_text.encode()).hexdigest() != source.template_sha256
        ):
            raise ValueError("template hash")
        return source
    except (ValueError, TypeError, KeyError) as error:
        raise DomainError("INVALID_SNAPSHOT", "Frozen PDF/skill source is invalid", 500) from error


def request_payload(request: PaperAnalysisRequest) -> dict[str, Any]:
    # Never asdict ephemeral page images. Keep old text payload shape exactly.
    result = asdict(replace(request, page_images=()))
    result.pop("page_images", None)
    result.pop("verified_pdf_quotes", None)
    if request.pdf_source is None:
        result.pop("pdf_source", None)
    else:
        result["pdf_source"]["attachment_id"] = str(request.pdf_source.attachment_id)
        result["pdf_source"]["pages"] = list(request.pdf_source.pages)
        if request.pdf_source.note_output_contract == "PAPER_ANALYSIS_V1":
            result["pdf_source"].pop("note_output_contract", None)
    return result


def _attachment(
    db: Session, user_id: uuid.UUID, paper_id: uuid.UUID, attachment_id: uuid.UUID
) -> Attachment:
    get_paper(db, user_id, paper_id)
    result = db.scalar(
        select(Attachment)
        .join(PaperAttachment, PaperAttachment.attachment_id == Attachment.id)
        .where(
            Attachment.id == attachment_id,
            Attachment.user_id == user_id,
            Attachment.deleted_at.is_(None),
            PaperAttachment.paper_id == paper_id,
        )
    )
    if result is None or result.mime_type != "application/pdf":
        raise DomainError("NOT_FOUND", "Owned original paper PDF not found", 404)
    return result


async def _read_verified(record: Attachment, storage: StorageProvider, expected_hash: str) -> bytes:
    if storage.provider_key != record.storage_provider:
        raise DomainError("STORAGE_PROVIDER_MISMATCH", "Attachment storage provider changed", 409)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if record.size_bytes > max_bytes:
        raise DomainError("PDF_SIZE_LIMIT", "Original PDF exceeds the configured size limit", 422)
    reader = await storage.open(record.object_key)
    try:
        if reader.size_bytes != record.size_bytes:
            raise DomainError("PDF_SOURCE_CHANGED", "Original PDF size changed", 409)
        chunks: list[bytes] = []
        count = 0
        digest = hashlib.sha256()
        async for chunk in reader.iter_bytes():
            count += len(chunk)
            if count > max_bytes or count > record.size_bytes:
                raise DomainError("PDF_SOURCE_CHANGED", "Original PDF size changed", 409)
            digest.update(chunk)
            chunks.append(chunk)
        if (
            count != record.size_bytes
            or digest.hexdigest() != expected_hash
            or record.sha256 != expected_hash
        ):
            raise DomainError("PDF_SOURCE_CHANGED", "Original PDF checksum changed", 409)
        content = b"".join(chunks)
        if not content.startswith(b"%PDF-"):
            raise DomainError("PDF_UNREADABLE", "Attachment does not contain a PDF", 422)
        return content
    finally:
        await reader.close()


async def enqueue_pdf_reading(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
    approval_plan_id: uuid.UUID | None = None,
    expected_plan_sha256: str | None = None,
    approved: bool = False,
    output: NoteOutputProvider | None = None,
    storage: StorageProvider | None = None,
    skills: ReadingSkillProvider | None = None,
    visual: PDFVisualProvider | None = None,
) -> PaperAnalysisJob:
    paper = get_paper(db, user_id, paper_id)
    record = _attachment(db, user_id, paper_id, attachment_id)
    from app.services.analytical_plans import approved_plan

    if not approved or approval_plan_id is None or expected_plan_sha256 is None:
        raise DomainError(
            "READING_APPROVAL_REQUIRED",
            "Approve the frozen original PDF, skill, template and destination first",
            422,
        )
    approved_job = db.scalar(
        select(PaperAnalysisJob)
        .join(PaperReadingApproval, PaperReadingApproval.job_id == PaperAnalysisJob.id)
        .join(PaperReadingApprovalPlan, PaperReadingApprovalPlan.id == PaperReadingApproval.plan_id)
        .where(
            PaperAnalysisJob.user_id == user_id,
            PaperReadingApproval.plan_id == approval_plan_id,
            PaperReadingApprovalPlan.paper_id == paper_id,
            PaperReadingApprovalPlan.attachment_id == attachment_id,
            PaperReadingApprovalPlan.plan_sha256 == expected_plan_sha256,
        )
    )
    if approved_job is not None:
        require_selectable_job(db, user_id, approved_job.id)
        return approved_job
    plan = await approved_plan(
        db, user_id, paper_id, attachment_id, approval_plan_id, expected_plan_sha256, output=output
    )
    require_output_path_available(db, user_id, plan.output_root, plan.output_path)
    if plan.note_output_contract != "CANONICAL_MARKDOWN_V2":
        raise DomainError(
            "READING_CONTRACT_RETIRED",
            "Create and approve a plan in the current Analytical Writer environment; historical plans remain read-only",
            409,
        )
    skill = ReadingSkillReceipt(
        plan.skill_key,
        plan.skill_version,
        plan.skill_instructions,
        plan.skill_sha256,
        template_text=plan.template_text,
        template_sha256=plan.template_sha256,
    )
    if (
        not skill.key
        or not skill.version
        or not skill.instructions
        or len(skill.instructions.encode("utf-8")) > 256_000
        or hashlib.sha256(skill.instructions.encode("utf-8")).hexdigest() != skill.sha256
    ):
        raise DomainError("READING_SKILL_INVALID", "Reading skill receipt is invalid", 503)
    descriptor = ai_provider_descriptor()
    if descriptor.provider_key not in {"codex", "disabled"}:
        raise DomainError(
            "PDF_READING_PROVIDER_UNSUPPORTED",
            "Original PDF reading requires the Codex account provider",
            503,
        )
    content = await _read_verified(
        record, storage or storage_provider(record.storage_provider), record.sha256
    )
    renderer = visual or pdf_visual_provider()
    count = await asyncio.to_thread(renderer.page_count, content, max_pages=None)
    if count < 1:
        raise DomainError("PDF_UNREADABLE", "Original PDF has no readable pages", 422)
    if count != plan.page_count or renderer.render_version != plan.render_version:
        raise DomainError(
            "READING_PLAN_CHANGED", "Original PDF page count or render recipe changed", 409
        )
    _lock_owner(db, user_id)
    require_output_path_available(db, user_id, plan.output_root, plan.output_path)
    policy = analysis_settings(db, user_id)
    model = descriptor.model_key or get_settings().codex_model or "unconfigured"
    source = PDFReadingSource(
        record.id,
        record.sha256,
        count,
        tuple(range(1, count + 1)),
        skill.key,
        skill.version,
        skill.instructions,
        skill.sha256,
        renderer.render_version,
        template_text=plan.template_text,
        template_sha256=plan.template_sha256,
        stage="WRITE_NOTE",
        note_output_contract=cast(NoteOutputContract, plan.note_output_contract),
    )
    link = db.scalar(
        select(PaperAttachment).where(
            PaperAttachment.paper_id == paper_id, PaperAttachment.attachment_id == attachment_id
        )
    )
    source_item = (
        db.get(ZoteroSourceItem, link.source_item_id) if link and link.source_item_id else None
    )
    request = PaperAnalysisRequest(
        paper.title,
        paper.year,
        None,
        "FULL_TEXT",
        "DEEP",
        (),
        None if uses_provider_quota(policy, "codex") else policy.max_output_tokens_per_job,
        reasoning_effort=plan.reasoning_effort,
        pdf_source=source,
        writer_identity={
            "title": plan.title,
            "doi": paper.doi,
            "year": paper.year,
            "collection": plan.collection,
            "note_path": f"02vault/{plan.output_path}",
            "fulltext_path": None,
            "zotero_key": source_item.item_key
            if source_item and source_item.user_id == user_id
            else None,
            "pdf_key": link.attachment_key if link else None,
            "approval_plan_id": str(plan.id),
        },
    )
    payload = request_payload(request)
    input_hash = _payload_hash(payload)
    key_material = f"approved:{plan.id}:{plan.plan_sha256}:pdf:{paper_id}:{attachment_id}:{input_hash}:{PDF_PROMPT_VERSION}:codex:{model}:{idempotency_key or ''}"
    key = hashlib.sha256(key_material.encode()).hexdigest()
    existing = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.user_id == user_id, PaperAnalysisJob.idempotency_key == key
        )
    )
    while existing is not None and linked_ingest_cleared(db, user_id, existing.id):
        key = hashlib.sha256(f"{key}:cleared:{existing.id}".encode()).hexdigest()
        existing = db.scalar(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == user_id, PaperAnalysisJob.idempotency_key == key
            )
        )
    if existing is not None:
        require_not_permanently_deleted(db, user_id, existing.id)
        return existing
    batches = [
        tuple(range(start, min(count, start + PDF_BATCH_PAGES - 1) + 1))
        for start in range(1, count + 1, PDF_BATCH_PAGES)
    ]
    part_count = len(batches) + 1 if count > PDF_BATCH_PAGES else 0
    needed = max(1, part_count) * (
        policy.max_input_tokens_per_job + policy.max_output_tokens_per_job
    )
    status, code, message = "QUEUED", None, None
    if not descriptor.available or descriptor.provider_key != "codex":
        status, code, message = (
            "WAITING_CONFIG",
            descriptor.reason_code or "AI_NOT_CONFIGURED",
            descriptor.reason_message or "Codex account provider is unavailable",
        )
    elif policy.cloud_scope != "FULL_TEXT":
        status, code, message = (
            "WAITING_CONFIG",
            "CLOUD_SCOPE_NOT_ALLOWED",
            "Original PDF cloud transfer requires FULL_TEXT permission",
        )
    elif not uses_provider_quota(policy, "codex"):
        owner = db.get(User, user_id)
        assert owner is not None
        zone = ZoneInfo(owner.timezone)
        today = datetime.now(zone).date()
        day_start, day_end = _day_bounds(today, zone)
        recent = list(
            db.scalars(
                select(PaperAnalysisJob).where(
                    PaperAnalysisJob.user_id == user_id,
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
        used = monthly_accounted_tokens(db, monthly, policy)
        reserved = sum(
            row.reserved_tokens
            for row in monthly
            if row.status in {"QUEUED", "ANALYZING", "RETRY_WAIT"}
        )
        if (
            len(recent) >= policy.daily_analysis_limit
            or policy.monthly_token_limit <= 0
            or used + reserved + needed > policy.monthly_token_limit
        ):
            status, code, message = (
                "WAITING_BUDGET",
                "BUDGET_EXHAUSTED",
                "Local daily/monthly analysis budget is exhausted",
            )
    job = PaperAnalysisJob(
        id=uuid.uuid4(),
        user_id=user_id,
        paper_id=paper_id,
        source_type="PDF",
        parsed_document_id=None,
        idempotency_key=key,
        input_sha256=input_hash,
        source_version=record.sha256,
        analysis_scope="FULL_TEXT",
        analysis_mode="DEEP",
        provider_key="codex",
        model_key=model,
        reasoning_effort=plan.reasoning_effort,
        analysis_version=ANALYSIS_VERSION,
        prompt_version=PDF_PROMPT_VERSION,
        schema_version=CANONICAL_SCHEMA_VERSION,
        status=status,
        priority="NORMAL",
        part_count=part_count,
        parts_completed=0,
        reserved_tokens=needed if status == "QUEUED" else 0,
        error_code=code,
        error_message=message,
    )
    try:
        db.add(job)
        db.flush()
        db.add(AnalysisInputSnapshot(job_id=job.id, payload=payload, input_sha256=input_hash))
        db.add(
            PaperPDFReadingSource(
                job_id=job.id,
                user_id=user_id,
                attachment_id=record.id,
                sha256=record.sha256,
                page_count=count,
                skill_key=skill.key,
                skill_version=skill.version,
                skill_instructions=skill.instructions,
                skill_sha256=skill.sha256,
                render_version=renderer.render_version,
                note_output_contract=plan.note_output_contract,
            )
        )
        if part_count:
            for index, pages in enumerate(batches, 1):
                part_payload = request_payload(
                    replace(request, pdf_source=replace(source, pages=pages, stage="READ_PAGES"))
                )
                db.add(
                    PaperAnalysisPart(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        job_id=job.id,
                        part_index=index,
                        section_key=f"pdf-pages-{pages[0]}-{pages[-1]}",
                        request_payload=part_payload,
                        request_sha256=_payload_hash(part_payload),
                        status="QUEUED",
                        attempt_count=0,
                    )
                )
        db.add(PaperReadingApproval(job_id=job.id, user_id=user_id, plan_id=plan.id))
        if part_count:
            writing_payload = request_payload(
                replace(request, pdf_source=replace(source, pages=batches[0], stage="WRITE_NOTE"))
            )
            db.add(
                PaperAnalysisPart(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    job_id=job.id,
                    part_index=part_count,
                    section_key="canonical-note-writing",
                    request_payload=writing_payload,
                    request_sha256=_payload_hash(writing_payload),
                    status="QUEUED",
                    attempt_count=0,
                )
            )
        db.commit()
        db.refresh(job)
        return job
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == user_id, PaperAnalysisJob.idempotency_key == key
            )
        )
        if existing is not None:
            require_not_permanently_deleted(db, user_id, existing.id)
            return existing
        raise
    except Exception:
        db.rollback()
        raise


def validate_pdf_frozen(
    db: Session, job: PaperAnalysisJob, request: PaperAnalysisRequest
) -> PaperPDFReadingSource:
    source = db.scalar(
        select(PaperPDFReadingSource).where(
            PaperPDFReadingSource.job_id == job.id, PaperPDFReadingSource.user_id == job.user_id
        )
    )
    descriptor = request.pdf_source
    if (
        source is None
        or descriptor is None
        or job.source_type != "PDF"
        or job.provider_key != "codex"
        or request.source_texts
        or request.abstract is not None
    ):
        raise DomainError(
            "INVALID_SNAPSHOT", "Original PDF reading source is missing or mixed with text", 500
        )
    if (
        descriptor.attachment_id != source.attachment_id
        or descriptor.sha256 != source.sha256
        or descriptor.page_count != source.page_count
        or descriptor.skill_key != source.skill_key
        or descriptor.skill_version != source.skill_version
        or descriptor.skill_sha256 != source.skill_sha256
        or descriptor.skill_instructions != source.skill_instructions
        or descriptor.render_version != source.render_version
        or descriptor.note_output_contract != source.note_output_contract
    ):
        raise DomainError("INVALID_SNAPSHOT", "Frozen original PDF/skill binding changed", 500)
    approval = db.get(PaperReadingApproval, job.id)
    if approval is not None:
        plan = db.get(PaperReadingApprovalPlan, approval.plan_id)
        from app.services.analytical_plans import plan_payload

        if (
            plan is None
            or _payload_hash(plan_payload(plan)) != plan.plan_sha256
            or plan.user_id != job.user_id
            or approval.user_id != job.user_id
            or plan.paper_id != job.paper_id
            or plan.attachment_id != source.attachment_id
            or plan.sha256 != source.sha256
            or plan.page_count != source.page_count
            or descriptor.template_text != plan.template_text
            or descriptor.template_sha256 != plan.template_sha256
            or descriptor.skill_sha256 != plan.skill_sha256
            or descriptor.note_output_contract != plan.note_output_contract
        ):
            raise DomainError(
                "INVALID_SNAPSHOT", "Approved canonical template binding changed", 500
            )
        from app.services.reading_source_bindings import sources, validate

        validate(plan, sources(db, plan))
    _attachment(db, job.user_id, job.paper_id, source.attachment_id)
    return source


def validate_pdf_layout(
    db: Session, job: PaperAnalysisJob, request: PaperAnalysisRequest, payload: dict[str, object]
) -> None:
    source = validate_pdf_frozen(db, job, request)
    if (
        _payload_hash(payload) != job.input_sha256
        or request.pdf_source is None
        or request.pdf_source.pages != tuple(range(1, source.page_count + 1))
    ):
        raise DomainError(
            "INVALID_SNAPSHOT", "Original PDF snapshot hash/page coverage changed", 500
        )
    parts = list(
        db.scalars(
            select(PaperAnalysisPart)
            .where(PaperAnalysisPart.job_id == job.id, PaperAnalysisPart.user_id == job.user_id)
            .order_by(PaperAnalysisPart.part_index)
        )
    )
    batches = [
        tuple(range(start, min(source.page_count, start + PDF_BATCH_PAGES - 1) + 1))
        for start in range(1, source.page_count + 1, PDF_BATCH_PAGES)
    ]
    if source.page_count <= PDF_BATCH_PAGES:
        if parts or job.part_count != 0:
            raise DomainError("INVALID_SNAPSHOT", "A whole-PDF reading was incorrectly split", 500)
        return
    approval = db.get(PaperReadingApproval, job.id)
    expected_count = len(batches) + (1 if approval is not None else 0)
    if len(parts) != expected_count or job.part_count != expected_count:
        raise DomainError("INVALID_SNAPSHOT", "Original PDF page batches are incomplete", 500)
    for index, (part, pages) in enumerate(zip(parts[: len(batches)], batches, strict=True), 1):
        descriptor = source_descriptor(part.request_payload)
        if (
            part.part_index != index
            or descriptor is None
            or descriptor.pages != pages
            or _payload_hash(part.request_payload) != part.request_sha256
        ):
            raise DomainError("INVALID_SNAPSHOT", "Original PDF page batch/hash changed", 500)
        part_request = replace(request, pdf_source=descriptor)
        validate_pdf_frozen(db, job, part_request)
    if approval is not None:
        final = parts[-1]
        descriptor = source_descriptor(final.request_payload)
        if (
            descriptor is None
            or descriptor.stage != "WRITE_NOTE"
            or final.part_index != expected_count
            or _payload_hash(final.request_payload) != final.request_sha256
        ):
            raise DomainError(
                "INVALID_SNAPSHOT", "Canonical writing stage is missing or changed", 500
            )
        validate_pdf_frozen(db, job, replace(request, pdf_source=descriptor))


async def runtime_pdf_request(
    db: Session, job: PaperAnalysisJob, request: PaperAnalysisRequest
) -> PaperAnalysisRequest:
    source = validate_pdf_frozen(db, job, request)
    assert request.pdf_source is not None
    if len(request.pdf_source.pages) > PDF_BATCH_PAGES:
        raise DomainError("PDF_PAGE_RANGE_INVALID", "Original page batch exceeds twenty pages", 422)
    record = _attachment(db, job.user_id, job.paper_id, source.attachment_id)
    content = await _read_verified(record, storage_provider(record.storage_provider), source.sha256)
    renderer = pdf_visual_provider()
    if renderer.render_version != source.render_version:
        raise DomainError(
            "PDF_RENDER_VERSION_CHANGED", "Frozen PDF rendering recipe is unavailable", 409
        )
    images = await asyncio.to_thread(renderer.render, content, request.pdf_source.pages)
    if tuple(image.page for image in images) != request.pdf_source.pages or any(
        hashlib.sha256(image.png).hexdigest() != image.sha256 for image in images
    ):
        raise DomainError("PDF_RENDER_INVALID", "Rendered original-page identity is invalid", 422)
    return replace(request, page_images=images)


def source_out(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
    require_not_permanently_deleted(db, user_id, job_id)
    job = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.id == job_id, PaperAnalysisJob.user_id == user_id
        )
    )
    source = db.scalar(
        select(PaperPDFReadingSource).where(
            PaperPDFReadingSource.job_id == job_id, PaperPDFReadingSource.user_id == user_id
        )
    )
    if job is None or source is None:
        raise DomainError("NOT_FOUND", "Original PDF reading source not found", 404)
    parts = list(
        db.scalars(
            select(PaperAnalysisPart)
            .where(PaperAnalysisPart.job_id == job_id, PaperAnalysisPart.user_id == user_id)
            .order_by(PaperAnalysisPart.part_index)
        )
    )
    if parts:
        pages = []
        for part in parts:
            descriptor = source_descriptor(part.request_payload)
            if descriptor is None:
                raise DomainError("INVALID_SNAPSHOT", "Original PDF page batch is invalid", 500)
            pages.append(descriptor.pages)
    else:
        snapshot = db.get(AnalysisInputSnapshot, job_id)
        if snapshot is None:
            raise DomainError("INVALID_SNAPSHOT", "Original PDF snapshot is unavailable", 500)
        descriptor = source_descriptor(snapshot.payload)
        if descriptor is None:
            raise DomainError("INVALID_SNAPSHOT", "Original PDF snapshot is invalid", 500)
        pages = [descriptor.pages]
    return {
        "job_id": job_id,
        "attachment_id": source.attachment_id,
        "sha256": source.sha256,
        "page_count": source.page_count,
        "skill_key": source.skill_key,
        "skill_version": source.skill_version,
        "skill_sha256": source.skill_sha256,
        "render_version": source.render_version,
        "note_output_contract": source.note_output_contract,
        "page_batches": [
            {"part_index": index, "pages": batch} for index, batch in enumerate(pages, 1)
        ],
    }
