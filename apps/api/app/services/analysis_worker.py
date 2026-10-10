import hashlib
import json
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.ai import (
    SECTION_KEYS,
    AIAnalysisResponse,
    AIProvider,
    AIUsage,
    AnalysisMode,
    AnalysisScope,
    AnalysisSectionResult,
    PaperAnalysisRequest,
    PaperAnalysisResult,
    SourceText,
)
from app.domain.analytical_contract import validate_analytical_markdown
from app.errors import DomainError
from app.models import (
    AnalysisInputSnapshot,
    AnalysisSettings,
    InboxItem,
    LiteratureIngestJob,
    Paper,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperPDFReadingSource,
    PaperResearchNote,
    ParsedBlock,
    ResearchEvent,
    ResearchNoteEvidence,
    ResearchNoteSection,
)
from app.models_analytical import PaperReadingApproval
from app.services.analysis_outcomes import UNUSABLE_EVENT, error_receipt, record_uncertain_call
from app.services.canonical_notes import register_canonical_note, save_canonical_note
from app.services.common import register_entity
from app.services.note_deletion_state import (
    require_not_permanently_deleted,
    selectable_deletion_clause,
)
from app.services.paper_analysis import (
    ANALYSIS_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    SCOPE_RANK,
    effective_call_request,
    uses_provider_quota,
)
from app.services.pdf_reading import (
    CANONICAL_SCHEMA_VERSION,
    PDF_PROMPT_VERSION,
    runtime_pdf_request,
    source_descriptor,
    validate_pdf_frozen,
    validate_pdf_layout,
)


def _pdf_attachment_id(db: Session, job: PaperAnalysisJob) -> uuid.UUID:
    source = db.scalar(
        select(PaperPDFReadingSource).where(
            PaperPDFReadingSource.job_id == job.id, PaperPDFReadingSource.user_id == job.user_id
        )
    )
    if source is None:
        raise DomainError("INVALID_SNAPSHOT", "Original PDF source is unavailable", 500)
    return source.attachment_id


def _call_was_cancelled(db: Session, job: PaperAnalysisJob) -> bool:
    """Lock a fresh status before publishing a response received after I/O."""
    with db.no_autoflush:
        require_not_permanently_deleted(db, job.user_id, job.id)
        current = db.scalar(
            select(PaperAnalysisJob.status)
            .where(
                PaperAnalysisJob.id == job.id,
                PaperAnalysisJob.user_id == job.user_id,
            )
            .with_for_update()
        )
        cleared = db.scalar(
            select(LiteratureIngestJob.id)
            .where(
                LiteratureIngestJob.user_id == job.user_id,
                LiteratureIngestJob.analysis_job_id == job.id,
                LiteratureIngestJob.cleared_at.is_not(None),
            )
            .limit(1)
        )
    if current == "CANCELLED" or cleared is not None:
        job.status = "CANCELLED"
        job.reserved_tokens = 0
        job.next_retry_at = None
        return True
    return False


def _retain_cancelled_receipt(
    db: Session,
    job: PaperAnalysisJob,
    response: AIAnalysisResponse,
    part: PaperAnalysisPart | None = None,
) -> PaperAnalysisJob:
    """Retain usage/result evidence without publishing a note or another call."""
    require_not_permanently_deleted(db, job.user_id, job.id)
    if part is not None:
        part.response_payload = response.result.model_dump(mode="json")
        part.provider_response_id = response.provider_response_id
        part.input_tokens = response.usage.input_tokens
        part.output_tokens = response.usage.output_tokens
        part.status = "COMPLETED"
        part.completed_at = datetime.now(UTC)
        job.parts_completed += 1
    else:
        record_uncertain_call(
            db,
            job,
            event_type=UNUSABLE_EVENT,
            usage=response.usage,
            provider_response_id=response.provider_response_id,
        )
    job.status = "CANCELLED"
    job.reserved_tokens = 0
    job.next_retry_at = None
    db.commit()
    return job


def _retry_seconds(error: Exception, attempt: int) -> int:
    delay = min(60 * (1 << max(0, min(attempt, 6))), 3600)
    if isinstance(error, DomainError) and isinstance(error.details, dict):
        advised = error.details.get("retry_after_seconds")
        if isinstance(advised, int) and not isinstance(advised, bool) and 0 <= advised <= 3600:
            delay = max(delay, int(advised))
    return delay


def _request_from_payload(payload: dict[str, object]) -> PaperAnalysisRequest:
    raw_texts = payload.get("source_texts")
    if not isinstance(raw_texts, list):
        raise DomainError("INVALID_SNAPSHOT", "Analysis input snapshot is invalid", 500)
    texts = tuple(
        SourceText(
            section_key=str(part["section_key"]),
            text=str(part["text"]),
            page=int(str(part["page"])) if part.get("page") is not None else None,
            block_index=int(str(part["block_index"]))
            if part.get("block_index") is not None
            else None,
            title=str(part["title"]) if part.get("title") is not None else None,
            ancestor_titles=tuple(str(item) for item in part.get("ancestor_titles", [])),
        )
        for part in raw_texts
        if isinstance(part, dict)
    )
    return PaperAnalysisRequest(
        title=str(payload["title"]),
        year=int(str(payload["year"])) if payload.get("year") is not None else None,
        abstract=str(payload["abstract"]) if payload.get("abstract") is not None else None,
        scope=cast(AnalysisScope, payload["scope"]),
        mode=cast(AnalysisMode, payload["mode"]),
        source_texts=texts,
        pdf_source=source_descriptor(payload),
        writer_identity=cast(dict[str, object] | None, payload.get("writer_identity")),
        reading_receipts=tuple(cast(list[dict[str, object]], payload.get("reading_receipts", []))),
        reasoning_effort=str(payload["reasoning_effort"])
        if payload.get("reasoning_effort")
        else None,
        max_output_tokens=int(str(payload["max_output_tokens"]))
        if payload.get("max_output_tokens") is not None
        else None,
    )


def _request_from_snapshot(snapshot: AnalysisInputSnapshot) -> PaperAnalysisRequest:
    return _request_from_payload(snapshot.payload)


def _validate_evidence(
    db: Session,
    job: PaperAnalysisJob,
    request: PaperAnalysisRequest,
    response: AIAnalysisResponse,
) -> dict[int, ParsedBlock]:
    if request.pdf_source is not None:
        validate_pdf_frozen(db, job, request)
        supplied_pages = set(request.pdf_source.pages)
        supplied_pages.update(
            proof.physical_page
            for proof in request.verified_pdf_quotes
            if proof.pdf_sha256 == request.pdf_source.sha256
        )
        prior_evidence: list[dict[str, object]] = []
        for receipt in request.reading_receipts:
            raw_result = receipt.get("result")
            if not isinstance(raw_result, dict):
                raise DomainError("INVALID_SNAPSHOT", "Reading receipt result is invalid", 500)
            receipt_result = PaperAnalysisResult.model_validate(raw_result)
            prior_evidence.extend(
                item.model_dump(mode="json")
                for section in receipt_result.sections
                for item in section.evidence
            )
        if request.pdf_source.stage == "WRITE_NOTE":
            supplied_pages.update(
                cast(int, item.get("source_page"))
                for item in prior_evidence
                if isinstance(item.get("source_page"), int)
            )
            note_sections = response.result.sections
            if request.pdf_source.template_text is not None:
                if (
                    len(note_sections) != 1
                    or note_sections[0].section_key != "analytical_note"
                    or not note_sections[0].body_markdown
                ):
                    raise DomainError(
                        "AI_INVALID_OUTPUT",
                        "Writer must return one complete canonical analytical note",
                        502,
                    )
                validate_analytical_markdown(
                    note_sections[0].body_markdown,
                    request.pdf_source.template_text,
                    request.writer_identity,
                )
                from app.services.current_reading import approved_writer_plan

                if approved_writer_plan(db, job) is not None:
                    # The professional Skill's exact Markdown is the primary output.
                    # Legacy JSON evidence is an unverified receipt, never a source proof.
                    auxiliary = [
                        {
                            "section_key": section.section_key,
                            "origin_type": section.origin_type,
                            "uncertainty": section.uncertainty,
                            "evidence": [item.model_dump(mode="json") for item in section.evidence],
                        }
                        for section in note_sections
                        if section.evidence or section.origin_type != "AI_INTERPRETATION"
                    ]
                    if auxiliary:
                        db.add(
                            ResearchEvent(
                                event_id=uuid.uuid4(),
                                user_id=job.user_id,
                                event_type="paper.writer_auxiliary_candidate",
                                source="analysis-worker",
                                occurred_at=datetime.now(UTC),
                                paper_id=job.paper_id,
                                correlation_id=job.id,
                                payload={
                                    "job_id": str(job.id),
                                    "provider_response_id": response.provider_response_id,
                                    "note_sha256": hashlib.sha256(
                                        note_sections[0].body_markdown.encode()
                                    ).hexdigest(),
                                    "verification": "UNVERIFIED_CANDIDATE",
                                    "source_associations_created": False,
                                    "auxiliary_sections": auxiliary,
                                },
                            )
                        )
                    for section in note_sections:
                        section.evidence = []
                        section.origin_type = "AI_INTERPRETATION"
                    warning = "CANONICAL_MARKDOWN_UNVERIFIED: the exact Skill Markdown is retained as an unreviewed candidate; auxiliary quotations and page claims are not verified source associations."
                    if warning not in response.result.warnings:
                        response.result.warnings.append(warning)
                    return {}
        for section in response.result.sections:
            if section.section_key not in SECTION_KEYS:
                raise DomainError("AI_INVALID_OUTPUT", "AI returned an unknown note section", 502)
            for index, evidence in enumerate(section.evidence):
                if (
                    evidence.source_page not in request.pdf_source.pages
                    and evidence.evidence_text
                    and not any(
                        proof.pdf_sha256 == request.pdf_source.sha256
                        and proof.physical_page == evidence.source_page
                        and proof.quote_sha256
                        == hashlib.sha256(evidence.evidence_text.encode("utf-8")).hexdigest()
                        for proof in request.verified_pdf_quotes
                    )
                    and not any(
                        item.get("source_page") == evidence.source_page
                        and item.get("evidence_text") == evidence.evidence_text
                        for item in prior_evidence
                    )
                ):
                    raise DomainError(
                        "AI_INVALID_EVIDENCE",
                        "New visual quotation must be checked on a supplied original page",
                        502,
                    )
                if (
                    evidence.source_block_index is not None
                    or evidence.source_page not in supplied_pages
                ):
                    raise DomainError(
                        "AI_INVALID_EVIDENCE",
                        "Visual evidence must cite a supplied physical original PDF page",
                        502,
                        details={
                            "validation_reason": "INVALID_ORIGINAL_PDF_PAGE",
                            "note_section": section.section_key,
                            "evidence_index": index,
                            "source_page": evidence.source_page,
                            "source_block_index": evidence.source_block_index,
                        },
                    )
        warning = "ORIGINAL_PDF_VISUAL_EVIDENCE: physical page references are checked; visual quotations/figures/tables/equations remain unverified candidates until owner review."
        if warning not in response.result.warnings:
            response.result.warnings.append(warning)
        return {}
    supplied_blocks = {
        part.block_index: part for part in request.source_texts if part.block_index is not None
    }

    def in_source(quote: str, source: str) -> bool:
        normalized_quote = re.sub(r"\s+", " ", quote).strip().casefold()
        normalized_source = re.sub(r"\s+", " ", source).strip().casefold()
        return bool(normalized_quote) and normalized_quote in normalized_source

    blocks = (
        {
            block.block_index: block
            for block in db.scalars(
                select(ParsedBlock).where(ParsedBlock.document_id == job.parsed_document_id)
            )
        }
        if job.parsed_document_id
        else {}
    )
    for section in response.result.sections:
        if section.section_key not in SECTION_KEYS:
            raise DomainError(
                "AI_INVALID_OUTPUT",
                "AI returned an unknown note section",
                502,
                details={
                    "validation_reason": "UNKNOWN_NOTE_SECTION",
                    "note_section": section.section_key[:80],
                },
            )
        for evidence_index, evidence in enumerate(section.evidence):

            def invalid_evidence(
                reason: str,
                message: str,
                *,
                matches: int | None = None,
                note_section: str = section.section_key,
                item_index: int = evidence_index,
                locator: tuple[str | None, int | None, int | None] = (
                    evidence.source_section,
                    evidence.source_page,
                    evidence.source_block_index,
                ),
            ) -> DomainError:
                details: dict[str, object] = {
                    "validation_reason": reason,
                    "note_section": note_section,
                    "evidence_index": item_index,
                    "source_section": locator[0][:160] if locator[0] is not None else None,
                    "source_page": locator[1],
                    "source_block_index": locator[2],
                }
                if matches is not None:
                    details["quote_match_count"] = matches
                return DomainError("AI_INVALID_EVIDENCE", message, 502, details=details)

            quote = evidence.evidence_text
            if evidence.claim_type == "PAPER_REPORTED" and not quote:
                raise invalid_evidence("MISSING_QUOTE", "Reported claim has no source quote")
            if job.analysis_scope == "FULL_TEXT":
                match_count: int | None = None
                if evidence.source_block_index is None:
                    # Resolve only an exact quote uniquely present in the frozen
                    # input; never infer a locator from model claims alone.
                    matches = [
                        supplied
                        for supplied in supplied_blocks.values()
                        if quote
                        and in_source(quote, supplied.text)
                        and (evidence.source_page is None or evidence.source_page == supplied.page)
                        and (
                            evidence.source_section is None
                            or evidence.source_section in (supplied.section_key, supplied.title)
                        )
                    ]
                    match_count = len(matches)
                    if len(matches) == 1:
                        resolved_source = matches[0]
                        evidence.source_block_index = resolved_source.block_index
                        evidence.source_page = resolved_source.page
                        evidence.source_section = resolved_source.section_key
                    elif (
                        (
                            evidence.source_section is None
                            or evidence.source_section.strip().casefold() == "abstract"
                        )
                        and evidence.source_page is None
                        and quote
                        and in_source(quote, request.abstract or "")
                    ):
                        # A frozen metadata abstract has no PDF page or block.
                        # Label its actual source; do not fabricate PDF locators.
                        evidence.source_section = "abstract"
                        continue
                if evidence.source_block_index is None:
                    if evidence.source_page is not None or quote:
                        raise invalid_evidence(
                            "LOCATOR_REQUIRED",
                            "PDF quote needs a supplied block",
                            matches=match_count,
                        )
                    continue
                block = blocks.get(evidence.source_block_index)
                supplied = supplied_blocks.get(evidence.source_block_index)
                if (
                    block is None
                    or supplied is None
                    or (
                        evidence.source_page is not None
                        and block.page_number != evidence.source_page
                    )
                ):
                    raise invalid_evidence("BLOCK_OUT_OF_SCOPE", "AI cited an unsupplied PDF block")
                if evidence.source_section and evidence.source_section != supplied.section_key:
                    raise invalid_evidence(
                        "SECTION_MISMATCH", "PDF section locator is inconsistent"
                    )
                if quote and not in_source(quote, supplied.text):
                    raise invalid_evidence(
                        "QUOTE_MISMATCH", "PDF quote is absent from supplied text"
                    )
            else:
                if evidence.source_block_index is not None or evidence.source_page is not None:
                    raise invalid_evidence(
                        "UNEXPECTED_PDF_LOCATOR", "Abstract or metadata has no PDF locator"
                    )
                source_name = "abstract" if job.analysis_scope == "ABSTRACT_ONLY" else "metadata"
                if evidence.source_section not in (None, source_name):
                    raise invalid_evidence("SECTION_MISMATCH", "Source section is inconsistent")
                source_text = request.abstract if source_name == "abstract" else request.title
                if quote and not in_source(quote, source_text or ""):
                    raise invalid_evidence("QUOTE_MISMATCH", "Quote is absent from supplied source")
    return blocks


def _persist_analysis_note(
    db: Session, job: PaperAnalysisJob, response: AIAnalysisResponse, blocks: dict[int, ParsedBlock]
) -> PaperAnalysisJob:
    # Serialize revision assignment for the same paper on PostgreSQL.
    with db.no_autoflush:
        db.execute(select(Paper.id).where(Paper.id == job.paper_id).with_for_update())
        require_not_permanently_deleted(db, job.user_id, job.id)
    existing_revision = (
        db.scalar(
            select(func.max(PaperResearchNote.revision)).where(
                PaperResearchNote.paper_id == job.paper_id
            )
        )
        or 0
    )
    note_id = register_entity(db, job.user_id, "research_note")
    note = PaperResearchNote(
        id=note_id,
        user_id=job.user_id,
        paper_id=job.paper_id,
        analysis_job_id=job.id,
        revision=existing_revision + 1,
        summary=response.result.summary,
        analysis_scope=job.analysis_scope,
        analysis_mode=job.analysis_mode,
        created_by="AI",
        review_status="UNREVIEWED",
    )
    db.add(note)
    approval = db.get(PaperReadingApproval, job.id)
    if approval is not None:
        sections = response.result.sections
        if (
            len(sections) != 1
            or sections[0].section_key != "analytical_note"
            or not sections[0].body_markdown
        ):
            raise DomainError(
                "AI_INVALID_OUTPUT", "A complete canonical analytical note is required", 502
            )
        register_canonical_note(db, job.user_id, job.id, sections[0].body_markdown)
    db.flush()
    seen_keys: set[str] = set()
    for section in response.result.sections:
        if section.section_key in seen_keys:
            raise DomainError("AI_INVALID_OUTPUT", "AI repeated a note section", 502)
        seen_keys.add(section.section_key)
        section_id = uuid.uuid4()
        db.add(
            ResearchNoteSection(
                id=section_id,
                note_id=note_id,
                section_key=section.section_key,
                body_markdown=section.body_markdown,
                origin_type=section.origin_type,
                uncertainty=section.uncertainty,
                review_status="UNREVIEWED",
            )
        )
        db.flush()
        for evidence in section.evidence:
            block = (
                blocks.get(evidence.source_block_index)
                if evidence.source_block_index is not None
                else None
            )
            db.add(
                ResearchNoteEvidence(
                    id=uuid.uuid4(),
                    section_id=section_id,
                    claim_type=evidence.claim_type,
                    source_section=evidence.source_section,
                    source_page=evidence.source_page,
                    source_block_id=block.id if block else None,
                    evidence_text=evidence.evidence_text,
                    locator=(
                        f"/api/v1/attachments/{_pdf_attachment_id(db, job)}/download#page={evidence.source_page}"
                        if job.source_type == "PDF" and evidence.source_page is not None
                        else f"block:{evidence.source_block_index}"
                        if block
                        else "abstract"
                        if job.analysis_scope == "ABSTRACT_ONLY"
                        or evidence.source_section == "abstract"
                        else None
                    ),
                )
            )
    db.add(
        InboxItem(
            id=uuid.uuid4(),
            user_id=job.user_id,
            item_type="AI_NOTE",
            note_id=note_id,
            status="PENDING",
        )
    )
    now = datetime.now(UTC)
    db.add(
        ResearchEvent(
            id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            user_id=job.user_id,
            event_type="paper.analysis_completed",
            schema_version="1.0",
            occurred_at=now,
            source="analysis-worker",
            paper_id=job.paper_id,
            correlation_id=job.id,
            payload={
                "job_id": str(job.id),
                "note_id": str(note_id),
                "scope": job.analysis_scope,
                "provider_key": job.provider_key,
                "model_key": job.model_key,
                "provider_response_id": response.provider_response_id,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )
    )
    job.status = "COMPLETED"
    job.completed_at = now
    job.reserved_tokens = 0
    job.input_tokens = response.usage.input_tokens
    job.output_tokens = response.usage.output_tokens
    db.commit()
    db.refresh(job)
    return job


def _part_request(part: PaperAnalysisPart) -> PaperAnalysisRequest:
    canonical = json.dumps(part.request_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != part.request_sha256:
        raise DomainError("INVALID_SNAPSHOT", "Analysis part input hash changed", 500)
    return _request_from_payload(part.request_payload)


def _merged_part_response(
    db: Session, job: PaperAnalysisJob, parts: list[PaperAnalysisPart]
) -> AIAnalysisResponse:
    grouped: dict[str, list[tuple[PaperAnalysisPart, AnalysisSectionResult]]] = {}
    summaries: list[str] = []
    warnings: list[str] = []
    for part in parts:
        if part.status != "COMPLETED" or part.response_payload is None:
            raise DomainError("INVALID_SNAPSHOT", "An analysis part has no completed result", 500)
        request = _part_request(part)
        result = PaperAnalysisResult.model_validate(part.response_payload)
        recorded = AIAnalysisResponse(
            result=result,
            usage=AIUsage(part.input_tokens, part.output_tokens),
            provider_response_id=part.provider_response_id,
        )
        _validate_evidence(db, job, request, recorded)
        summaries.append(f"片段 {part.part_index}（{part.section_key}）：{result.summary}")
        warnings.extend(f"片段 {part.part_index}：{warning}" for warning in result.warnings)
        for section in result.sections:
            grouped.setdefault(section.section_key, []).append((part, section))
    merged_sections: list[AnalysisSectionResult] = []
    for key in SECTION_KEYS:
        rows = grouped.get(key, [])
        if not rows:
            continue
        bodies = [
            f"#### 原文片段 {part.part_index} · {part.section_key}\n\n{section.body_markdown}"
            for part, section in rows
            if section.body_markdown
        ]
        uncertainties = [
            f"片段 {part.part_index}：{section.uncertainty}"
            for part, section in rows
            if section.uncertainty
        ]
        merged_sections.append(
            AnalysisSectionResult(
                section_key=key,
                body_markdown="\n\n".join(bodies) or None,
                origin_type=(
                    "AI_INTERPRETATION"
                    if any(section.origin_type == "AI_INTERPRETATION" for _, section in rows)
                    else "PAPER_REPORTED"
                ),
                uncertainty="\n".join(uncertainties) or None,
                evidence=[evidence for _, section in rows for evidence in section.evidence],
            )
        )
    if not merged_sections:
        raise DomainError("AI_INVALID_OUTPUT", "Analysis parts contain no note sections", 502)
    input_values = [part.input_tokens for part in parts]
    output_values = [part.output_tokens for part in parts]
    return AIAnalysisResponse(
        result=PaperAnalysisResult(
            summary=(
                "按原始 PDF 页段精读结果汇编；未额外调用独立全篇综合。\n\n"
                if job.source_type == "PDF"
                else "按原文片段汇编；未进行跨章节综合推断。\n\n"
            )
            + "\n".join(summaries),
            sections=merged_sections,
            warnings=warnings,
        ),
        usage=AIUsage(
            sum(value for value in input_values if value is not None)
            if all(value is not None for value in input_values)
            else None,
            sum(value for value in output_values if value is not None)
            if all(value is not None for value in output_values)
            else None,
        ),
        provider_response_id=None,
    )


async def _attempt_note_export(db: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> None:
    # Model receipt and canonical candidate are already committed. File-system or
    # backup registration failures must never replay or reclassify the AI call.
    try:
        await save_canonical_note(db, user_id, job_id, automatic=True)
    except Exception:
        db.rollback()


def _writing_request(
    db: Session,
    job: PaperAnalysisJob,
    request: PaperAnalysisRequest,
    reading_parts: list[PaperAnalysisPart],
) -> PaperAnalysisRequest:
    if request.pdf_source is None:
        raise DomainError("INVALID_SNAPSHOT", "Canonical writing requires original PDF source", 500)
    receipts: list[dict[str, object]] = []
    coverage: list[int] = []
    evidence_pages: list[int] = []
    for part in reading_parts:
        source = _part_request(part).pdf_source
        if (
            part.status != "COMPLETED"
            or part.response_payload is None
            or source is None
            or source.stage != "READ_PAGES"
        ):
            raise DomainError(
                "INVALID_SNAPSHOT", "Read every original PDF page before canonical writing", 500
            )
        coverage.extend(source.pages)
        result = PaperAnalysisResult.model_validate(part.response_payload)
        for section in result.sections:
            for evidence in section.evidence:
                if evidence.source_page is not None and evidence.source_page not in evidence_pages:
                    evidence_pages.append(evidence.source_page)
        receipts.append(
            {
                "part_index": part.part_index,
                "pages": list(source.pages),
                "request_sha256": part.request_sha256,
                "result": result.model_dump(mode="json"),
            }
        )
    if coverage != list(range(1, request.pdf_source.page_count + 1)):
        raise DomainError("INVALID_SNAPSHOT", "Original PDF page coverage is incomplete", 500)
    check_pages = tuple(sorted(evidence_pages[:20])) or request.pdf_source.pages
    return replace(
        request,
        pdf_source=replace(request.pdf_source, pages=check_pages),
        reading_receipts=tuple(receipts),
    )


async def _process_part_job(
    db: Session,
    job: PaperAnalysisJob,
    provider: AIProvider | None,
    full_request: PaperAnalysisRequest,
) -> PaperAnalysisJob:
    response: AIAnalysisResponse | None = None
    parts = list(
        db.scalars(
            select(PaperAnalysisPart)
            .where(PaperAnalysisPart.job_id == job.id, PaperAnalysisPart.user_id == job.user_id)
            .order_by(PaperAnalysisPart.part_index)
        )
    )
    if len(parts) != job.part_count or [part.part_index for part in parts] != list(
        range(1, job.part_count + 1)
    ):
        job.status = "FAILED"
        job.error_code = "INVALID_SNAPSHOT"
        job.error_message = "Analysis part sequence is incomplete"
        job.reserved_tokens = 0
        db.commit()
        return job
    if any(part.status in {"ANALYZING", "NEEDS_ATTENTION"} for part in parts):
        for uncertain_part in parts:
            if uncertain_part.status in {"ANALYZING", "NEEDS_ATTENTION"}:
                record_uncertain_call(db, job, uncertain_part)
        job.status = "NEEDS_ATTENTION"
        job.error_code = "PART_OUTCOME_UNCERTAIN"
        job.error_message = "Inspect the uncertain part before retrying; it may have been billed"
        job.reserved_tokens = 0
        db.commit()
        return job
    if all(part.status == "COMPLETED" for part in parts):
        job.status = "ANALYZING"
        job.started_at = datetime.now(UTC)
        db.commit()
        try:
            if db.get(PaperReadingApproval, job.id) is not None:
                final = parts[-1]
                if final.response_payload is None:
                    raise DomainError(
                        "INVALID_SNAPSHOT", "Canonical writing result is unavailable", 500
                    )
                response = AIAnalysisResponse(
                    PaperAnalysisResult.model_validate(final.response_payload),
                    AIUsage(job.input_tokens, job.output_tokens),
                    final.provider_response_id,
                )
                final_request = _writing_request(db, job, _part_request(final), parts[:-1])
                blocks = _validate_evidence(db, job, final_request, response)
                result_job = _persist_analysis_note(db, job, response, blocks)
                await _attempt_note_export(db, job.user_id, job.id)
                return result_job
            response = _merged_part_response(db, job, parts)
            blocks = _validate_evidence(db, job, full_request, response)
            return _persist_analysis_note(db, job, response, blocks)
        except Exception as exc:
            db.rollback()
            failed = db.get(PaperAnalysisJob, job.id)
            assert failed is not None
            failed.status = "FAILED"
            failed.error_code = exc.code if isinstance(exc, DomainError) else "FINALIZATION_FAILED"
            failed.error_message = (
                str(exc)[:2000]
                if isinstance(exc, DomainError)
                else "Note publication failed; completed parts are retained"
            )
            failed.reserved_tokens = 0
            db.commit()
            return failed
    part = next((row for row in parts if row.status != "COMPLETED"), None)
    assert part is not None
    if part.status not in {"QUEUED", "RETRY_WAIT"}:
        job.status = "FAILED"
        job.error_code = "PART_NOT_READY"
        job.error_message = "An analysis part requires owner review before continuing"
        job.reserved_tokens = 0
        db.commit()
        return job
    if provider is None:
        job.status = "WAITING_CONFIG"
        job.error_code = "AI_NOT_CONFIGURED"
        job.error_message = "AI provider is unavailable for the remaining analysis parts"
        job.reserved_tokens = 0
        db.commit()
        return job
    try:
        request = _part_request(part)
        if (
            request.pdf_source is not None
            and request.pdf_source.stage == "WRITE_NOTE"
            and db.get(PaperReadingApproval, job.id) is not None
        ):
            request = _writing_request(db, job, request, parts[:-1])
        policy = db.scalar(
            select(AnalysisSettings)
            .where(AnalysisSettings.user_id == job.user_id)
            .execution_options(populate_existing=True)
        )
        assert policy is not None  # Current policy was checked before dispatch.
        request = replace(
            effective_call_request(request, policy, job.provider_key),
            reasoning_effort=job.reasoning_effort,
        )
        if request.pdf_source is not None:
            request = await runtime_pdf_request(db, job, request)
            if _call_was_cancelled(db, job):
                db.commit()
                return job
            policy = db.scalar(
                select(AnalysisSettings)
                .where(AnalysisSettings.user_id == job.user_id)
                .execution_options(populate_existing=True)
            )
            if policy is None or policy.cloud_scope != "FULL_TEXT":
                job.status = "WAITING_CONFIG"
                job.error_code = "CLOUD_SCOPE_NOT_ALLOWED"
                job.error_message = "Original PDF transfer permission was revoked before submission"
                job.reserved_tokens = 0
                db.commit()
                return job
            request = replace(
                effective_call_request(request, policy, job.provider_key),
                reasoning_effort=job.reasoning_effort,
            )
    except DomainError as exc:
        if _call_was_cancelled(db, job):
            db.commit()
            return job
        job.status = part.status = "FAILED"
        job.error_code = part.error_code = exc.code
        job.error_message = part.error_message = exc.message
        job.reserved_tokens = 0
        db.commit()
        return job
    job.status = "ANALYZING"
    job.attempt_count += 1
    job.started_at = datetime.now(UTC)
    job.error_code = None
    job.error_message = None
    part.status = "ANALYZING"
    part.attempt_count += 1
    part.started_at = datetime.now(UTC)
    part.error_code = None
    part.error_message = None
    db.commit()
    rejected_result: PaperAnalysisResult | None = None
    try:
        response = await provider.analyze_paper(request)
        if _call_was_cancelled(db, job):
            return _retain_cancelled_receipt(db, job, response, part)
        rejected_result = response.result.model_copy(deep=True)
        _validate_evidence(db, job, request, response)
        part.response_payload = response.result.model_dump(mode="json")
        part.provider_response_id = response.provider_response_id
        part.input_tokens = response.usage.input_tokens
        part.output_tokens = response.usage.output_tokens
        part.status = "COMPLETED"
        part.completed_at = datetime.now(UTC)
        job.parts_completed += 1
        completed = [row for row in parts if row.status == "COMPLETED"]
        job.input_tokens = (
            sum(row.input_tokens for row in completed if row.input_tokens is not None)
            if all(row.input_tokens is not None for row in completed)
            else None
        )
        job.output_tokens = (
            sum(row.output_tokens for row in completed if row.output_tokens is not None)
            if all(row.output_tokens is not None for row in completed)
            else None
        )
        remaining = job.part_count - job.parts_completed
        job.reserved_tokens = max(
            0,
            job.reserved_tokens - (job.reserved_tokens // (remaining + 1) if remaining >= 0 else 0),
        )
        job.status = "QUEUED"
        job.next_retry_at = None
        db.commit()
        return job
    except Exception as exc:
        db.rollback()
        failed_job = db.get(PaperAnalysisJob, job.id)
        failed_part = db.get(PaperAnalysisPart, part.id)
        require_not_permanently_deleted(db, job.user_id, job.id)
        assert failed_job is not None and failed_part is not None
        code = exc.code if isinstance(exc, DomainError) else "ANALYSIS_FAILED"
        message = (
            str(exc)[:2000]
            if isinstance(exc, DomainError)
            else "Analysis part failed; inspect logs"
        )
        failed_job.error_code = code
        failed_job.error_message = message
        failed_part.error_code = code
        failed_part.error_message = message
        usage, response_id = error_receipt(exc)
        if response is not None:
            usage, response_id = response.usage, response.provider_response_id
        if _call_was_cancelled(db, failed_job):
            record_uncertain_call(
                db,
                failed_job,
                failed_part,
                usage=usage,
                provider_response_id=response_id,
                validation_error=exc if isinstance(exc, DomainError) else None,
            )
            failed_job.error_code = "ANALYSIS_OUTCOME_UNCERTAIN"
            failed_part.status = "NEEDS_ATTENTION"
        elif code in {
            "AI_OUTCOME_UNCERTAIN",
            "AI_TIMEOUT",
            "PROVIDER_UNAVAILABLE",
        } or not isinstance(exc, DomainError):
            failed_job.status = failed_part.status = "NEEDS_ATTENTION"
            failed_job.error_code = failed_part.error_code = "PART_RESULT_UNCERTAIN"
            failed_job.error_message = failed_part.error_message = (
                "Provider outcome is unknown; owner acknowledgement is required before retry"
            )
            record_uncertain_call(
                db,
                failed_job,
                failed_part,
                usage=usage,
                provider_response_id=response_id,
                validation_error=exc if isinstance(exc, DomainError) else None,
            )
            failed_job.reserved_tokens = 0
        elif code == "AI_QUOTA_EXHAUSTED":
            failed_job.status = "WAITING_PROVIDER_QUOTA"
            # The part's existing checked state vocabulary records a known
            # rejected attempt as FAILED. The owner-facing job controls waiting.
            failed_part.status = "FAILED"
            failed_job.next_retry_at = None
            failed_job.reserved_tokens = 0
        elif code in {"AI_REQUEST_NOT_SENT", "AI_RATE_LIMITED"} and (
            failed_part.attempt_count < failed_job.max_attempts
        ):
            failed_job.status = failed_part.status = "RETRY_WAIT"
            failed_job.next_retry_at = datetime.now(UTC) + timedelta(
                seconds=_retry_seconds(exc, failed_part.attempt_count)
            )
        else:
            failed_job.status = failed_part.status = "FAILED"
            if code in {
                "AI_INVALID_OUTPUT",
                "AI_INCOMPLETE",
                "AI_INVALID_EVIDENCE",
                "ANALYTICAL_NOTE_INVALID",
                "ANALYTICAL_NOTE_ASSET_UNVERIFIED",
            }:
                record_uncertain_call(
                    db,
                    failed_job,
                    failed_part,
                    event_type=UNUSABLE_EVENT,
                    usage=usage,
                    provider_response_id=response_id,
                    result=rejected_result,
                    validation_error=exc if isinstance(exc, DomainError) else None,
                )
            failed_job.reserved_tokens = 0
        db.commit()
        return failed_job


async def process_analysis_job(
    db: Session, job_id: uuid.UUID, provider: AIProvider | None
) -> PaperAnalysisJob:
    job = db.get(PaperAnalysisJob, job_id)
    if job is None:
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    require_not_permanently_deleted(db, job.user_id, job.id)
    if job.status not in {"QUEUED", "RETRY_WAIT"}:
        return job
    if _call_was_cancelled(db, job):
        db.commit()
        return job
    if job.status == "RETRY_WAIT" and job.next_retry_at:
        retry_at = job.next_retry_at
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        if retry_at > datetime.now(UTC):
            return job
    snapshot = db.get(AnalysisInputSnapshot, job.id)
    if snapshot is None or snapshot.input_sha256 != job.input_sha256:
        raise DomainError("INVALID_SNAPSHOT", "Analysis input is unavailable or changed", 500)
    request = _request_from_snapshot(snapshot)
    if job.source_type == "PDF" and db.get(PaperReadingApproval, job.id) is None:
        job.status = "WAITING_CONFIG"
        job.error_code = "READING_APPROVAL_REQUIRED"
        job.error_message = "Create and approve a canonical Analytical Writer plan before reading"
        job.reserved_tokens = 0
        db.commit()
        return job
    if job.source_type == "PDF":
        try:
            validate_pdf_layout(db, job, request, snapshot.payload)
        except DomainError as error:
            # An invalid frozen source cannot remain the earliest queued job
            # forever or cause a new model call. Preserve all prior receipts.
            job.status = "FAILED"
            job.error_code, job.error_message = error.code, error.message
            job.reserved_tokens = 0
            db.commit()
            return job
    local_finalization = job.part_count > 0 and job.parts_completed == job.part_count
    if not local_finalization:
        if job.source_type == "PDF":
            from app.services.current_reading import uses_current_reading_skill

            if not uses_current_reading_skill(db, job):
                job.status = "WAITING_CONFIG"
                job.error_code = "SOURCE_INTERFACE_RETIRED"
                job.error_message = "Historical reading contracts are retained; approve a plan in the current Zotero writer environment before a new model call"
                job.reserved_tokens = 0
                db.commit()
                return job
        if (
            job.prompt_version
            != (PDF_PROMPT_VERSION if job.source_type == "PDF" else PROMPT_VERSION)
            or job.analysis_version != ANALYSIS_VERSION
            or job.schema_version
            != (CANONICAL_SCHEMA_VERSION if job.source_type == "PDF" else SCHEMA_VERSION)
        ):
            job.status = "WAITING_CONFIG"
            job.error_code = "ANALYSIS_CONFIGURATION_CHANGED"
            job.error_message = "Analysis instructions changed; create a new analysis job"
            job.reserved_tokens = 0
            db.commit()
            return job
        policy = db.scalar(
            select(AnalysisSettings)
            .where(AnalysisSettings.user_id == job.user_id)
            .execution_options(populate_existing=True)
        )
        # Recheck current permission before every new call, including the next
        # part. An owner can revoke scope or stop funding after admission.
        if policy is None or SCOPE_RANK.get(policy.cloud_scope, 0) < SCOPE_RANK[job.analysis_scope]:
            job.status = "WAITING_CONFIG"
            job.error_code = "CLOUD_SCOPE_NOT_ALLOWED"
            job.error_message = "Current cloud permission does not allow this job's input"
            job.reserved_tokens = 0
            db.commit()
            return job
        if policy.budget_mode == "PROVIDER_QUOTA" and job.provider_key != "codex":
            job.status = "WAITING_CONFIG"
            job.error_code = "BUDGET_MODE_UNSUPPORTED"
            job.error_message = "Provider quota mode requires the Codex account provider"
            job.reserved_tokens = 0
            db.commit()
            return job
        if not uses_provider_quota(policy, job.provider_key) and (
            policy.monthly_token_limit <= 0 or policy.daily_analysis_limit <= 0
        ):
            job.status = "WAITING_BUDGET"
            job.error_code = "BUDGET_EXHAUSTED"
            job.error_message = "Current owner budget disables further AI calls"
            job.reserved_tokens = 0
            db.commit()
            return job
        request = replace(
            effective_call_request(request, policy, job.provider_key),
            reasoning_effort=job.reasoning_effort,
        )
    if not local_finalization and (
        provider is None
        or provider.provider_key != job.provider_key
        or provider.model_key != job.model_key
    ):
        job.status = "WAITING_CONFIG"
        job.error_code = "MODEL_CONFIGURATION_CHANGED"
        job.error_message = "Configured AI provider/model differs from this job snapshot"
        job.reserved_tokens = 0
        db.commit()
        return job
    if job.part_count > 0:
        return await _process_part_job(db, job, provider, request)
    assert provider is not None
    if request.pdf_source is not None:
        try:
            request = await runtime_pdf_request(db, job, request)
        except DomainError as error:
            if _call_was_cancelled(db, job):
                db.commit()
                return job
            job.status = "FAILED"
            job.error_code, job.error_message = error.code, error.message
            job.reserved_tokens = 0
            db.commit()
            return job
        if _call_was_cancelled(db, job):
            db.commit()
            return job
        current_scope = db.scalar(
            select(AnalysisSettings.cloud_scope).where(AnalysisSettings.user_id == job.user_id)
        )
        if current_scope != "FULL_TEXT":
            job.status = "WAITING_CONFIG"
            job.error_code = "CLOUD_SCOPE_NOT_ALLOWED"
            job.error_message = "Original PDF transfer permission was revoked before submission"
            job.reserved_tokens = 0
            db.commit()
            return job
    job.status = "ANALYZING"
    job.attempt_count += 1
    job.started_at = datetime.now(UTC)
    job.error_code = None
    job.error_message = None
    db.commit()

    response: AIAnalysisResponse | None = None
    rejected_result: PaperAnalysisResult | None = None
    try:
        response = await provider.analyze_paper(request)
        if _call_was_cancelled(db, job):
            return _retain_cancelled_receipt(db, job, response)
        rejected_result = response.result.model_copy(deep=True)
        blocks = _validate_evidence(db, job, request, response)
        result_job = _persist_analysis_note(db, job, response, blocks)
        if db.get(PaperReadingApproval, job.id) is not None:
            await _attempt_note_export(db, job.user_id, job.id)
        return result_job
    except Exception as exc:
        db.rollback()
        failed = db.get(PaperAnalysisJob, job_id)
        assert failed is not None
        require_not_permanently_deleted(db, failed.user_id, failed.id)
        code = exc.code if isinstance(exc, DomainError) else "ANALYSIS_FAILED"
        failed.error_code = code
        failed.error_message = (
            str(exc)[:2000]
            if isinstance(exc, DomainError)
            else "Analysis failed; inspect server logs"
        )
        usage, response_id = error_receipt(exc)
        if response is not None:
            usage, response_id = response.usage, response.provider_response_id
        if _call_was_cancelled(db, failed):
            record_uncertain_call(
                db,
                failed,
                usage=usage,
                provider_response_id=response_id,
                validation_error=exc if isinstance(exc, DomainError) else None,
            )
            failed.error_code = "ANALYSIS_OUTCOME_UNCERTAIN"
        elif code in {
            "AI_OUTCOME_UNCERTAIN",
            "AI_TIMEOUT",
            "PROVIDER_UNAVAILABLE",
        } or not isinstance(exc, DomainError):
            failed.status = "NEEDS_ATTENTION"
            failed.error_code = "ANALYSIS_OUTCOME_UNCERTAIN"
            failed.error_message = (
                "Provider outcome is unknown; owner acknowledgement is required before retry"
            )
            record_uncertain_call(
                db,
                failed,
                usage=usage,
                provider_response_id=response_id,
                validation_error=exc if isinstance(exc, DomainError) else None,
            )
            failed.reserved_tokens = 0
        elif code == "AI_QUOTA_EXHAUSTED":
            failed.status = "WAITING_PROVIDER_QUOTA"
            failed.next_retry_at = None
            failed.reserved_tokens = 0
        elif (
            code in {"AI_REQUEST_NOT_SENT", "AI_RATE_LIMITED"}
            and failed.attempt_count < failed.max_attempts
        ):
            failed.status = "RETRY_WAIT"
            failed.next_retry_at = datetime.now(UTC) + timedelta(
                seconds=_retry_seconds(exc, failed.attempt_count)
            )
        else:
            failed.status = "FAILED"
            if code in {
                "AI_INVALID_OUTPUT",
                "AI_INCOMPLETE",
                "AI_INVALID_EVIDENCE",
                "ANALYTICAL_NOTE_INVALID",
                "ANALYTICAL_NOTE_ASSET_UNVERIFIED",
            }:
                record_uncertain_call(
                    db,
                    failed,
                    event_type=UNUSABLE_EVENT,
                    usage=usage,
                    provider_response_id=response_id,
                    result=rejected_result,
                    validation_error=exc if isinstance(exc, DomainError) else None,
                )
            failed.reserved_tokens = 0
        db.commit()
        return failed


async def process_next_analysis_job(db: Session, provider: AIProvider) -> PaperAnalysisJob | None:
    now = datetime.now(UTC)
    job = db.scalar(
        select(PaperAnalysisJob)
        .where(
            selectable_deletion_clause(PaperAnalysisJob.user_id, PaperAnalysisJob.id),
            PaperAnalysisJob.source_type == "PDF",
            PaperAnalysisJob.prompt_version == PDF_PROMPT_VERSION,
            PaperAnalysisJob.schema_version == CANONICAL_SCHEMA_VERSION,
            PaperAnalysisJob.id.in_(select(PaperReadingApproval.job_id)),
            PaperAnalysisJob.provider_key == provider.provider_key,
            PaperAnalysisJob.model_key == provider.model_key,
            PaperAnalysisJob.status.in_(["QUEUED", "RETRY_WAIT"]),
            (PaperAnalysisJob.next_retry_at.is_(None) | (PaperAnalysisJob.next_retry_at <= now)),
        )
        .order_by(PaperAnalysisJob.queued_at, PaperAnalysisJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    return await process_analysis_job(db, job.id, provider)


async def process_next_local_finalization(db: Session) -> PaperAnalysisJob | None:
    """Publish completed parts without requiring an AI provider or another model call."""
    now = datetime.now(UTC)
    job = db.scalar(
        select(PaperAnalysisJob)
        .where(
            selectable_deletion_clause(PaperAnalysisJob.user_id, PaperAnalysisJob.id),
            PaperAnalysisJob.part_count > 0,
            PaperAnalysisJob.id.in_(select(PaperReadingApproval.job_id)),
            PaperAnalysisJob.parts_completed == PaperAnalysisJob.part_count,
            PaperAnalysisJob.status.in_(["QUEUED", "RETRY_WAIT"]),
            (PaperAnalysisJob.next_retry_at.is_(None) | (PaperAnalysisJob.next_retry_at <= now)),
        )
        .order_by(PaperAnalysisJob.queued_at, PaperAnalysisJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    return await process_analysis_job(db, job.id, None)


def recover_stale_analysis_jobs(db: Session, *, stale_after_minutes: int = 30) -> int:
    """Quarantine uncertain model calls; requeue only local note publication."""
    cutoff = datetime.now(UTC) - timedelta(minutes=stale_after_minutes)
    jobs = list(
        db.scalars(
            select(PaperAnalysisJob)
            .where(
                selectable_deletion_clause(PaperAnalysisJob.user_id, PaperAnalysisJob.id),
                PaperAnalysisJob.status == "ANALYZING",
                PaperAnalysisJob.started_at.is_not(None),
                PaperAnalysisJob.started_at < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for job in jobs:
        parts = list(
            db.scalars(
                select(PaperAnalysisPart).where(
                    PaperAnalysisPart.job_id == job.id,
                    PaperAnalysisPart.user_id == job.user_id,
                )
            )
        )
        if (
            job.part_count > 0
            and job.parts_completed == job.part_count
            and len(parts) == job.part_count
            and all(part.status == "COMPLETED" for part in parts)
        ):
            job.status = "QUEUED"
            job.error_code = None
            job.error_message = None
            continue
        for part in parts:
            if part.status == "ANALYZING":
                record_uncertain_call(db, job, part)
                part.status = "NEEDS_ATTENTION"
                part.error_code = "PART_OUTCOME_UNCERTAIN"
                part.error_message = "Worker stopped while a provider call may have been in flight"
        job.status = "NEEDS_ATTENTION"
        if not parts:
            record_uncertain_call(db, job)
        job.error_code = "ANALYSIS_OUTCOME_UNCERTAIN"
        job.error_message = "Worker stopped during analysis; inspect before any retry"
        job.reserved_tokens = 0
    if jobs:
        db.commit()
    return len(jobs)
