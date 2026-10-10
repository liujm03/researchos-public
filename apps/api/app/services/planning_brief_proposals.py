"""Literal planning quotations become new drafts only through explicit owner selection."""

import hashlib
import json
import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.research_planning import (
    PLANNING_CONTRACT_V2,
    PlanningBriefQuotes,
    planning_quote_spans,
)
from app.errors import DomainError
from app.models_planning_brief_proposals import (
    PlanningBriefAdoptionReceipt,
    PlanningBriefProposal,
    PlanningBriefProposalSection,
)
from app.models_research_briefs import ResearchBrief
from app.models_research_planning import (
    ResearchExecutionPermit,
    ResearchPlanningAttempt,
    ResearchPlanningJob,
    ResearchPlanningResult,
)
from app.schemas_planning_brief_proposals import (
    PlanningBriefAdoptionCreate,
    PlanningBriefAdoptionOut,
    PlanningBriefAdoptionPreviewCreate,
    PlanningBriefAdoptionPreviewOut,
    PlanningBriefAdoptionReceiptOut,
    PlanningBriefDiffOut,
    PlanningBriefProposalOut,
    PlanningProposalSectionOut,
)
from app.schemas_research_briefs import ResearchBriefCreate, ResearchBriefSectionCreate
from app.services import research_briefs, research_planning


def _sections(db: Session, proposal: PlanningBriefProposal) -> list[PlanningBriefProposalSection]:
    rows = list(
        db.scalars(
            select(PlanningBriefProposalSection)
            .where(
                PlanningBriefProposalSection.job_id == proposal.job_id,
                PlanningBriefProposalSection.project_id == proposal.project_id,
                PlanningBriefProposalSection.user_id == proposal.user_id,
            )
            .execution_options(populate_existing=True)
        )
    )
    return sorted(rows, key=lambda row: research_briefs.KEYS.index(row.key))


def proposal_hash(
    proposal: PlanningBriefProposal, sections: list[PlanningBriefProposalSection]
) -> str:
    fields = {
        key: getattr(proposal, key)
        for key in (
            "job_id",
            "project_id",
            "user_id",
            "attempt_id",
            "result_sha256",
            "contract_version",
            "contract_sha256",
            "stop_rules_quote",
            "stop_source_start",
            "stop_source_end",
            "warnings_text",
        )
    }
    return research_briefs.digest(
        {
            **fields,
            "sections": [
                {
                    "key": row.key,
                    "content": row.content,
                    "source_start": row.source_start,
                    "source_end": row.source_end,
                    "uncertainty": row.uncertainty,
                }
                for row in sorted(sections, key=lambda row: research_briefs.KEYS.index(row.key))
            ],
        }
    )


def save_normalization(
    db: Session,
    result: ResearchPlanningResult,
    normalization: PlanningBriefQuotes | None,
    normalization_issue: str | None,
    contract_version: str,
    contract_sha256: str | None,
) -> None:
    if result.disposition == "QUARANTINED":
        result.normalization_status, result.normalization_issue = (
            "QUARANTINED",
            "RESULT_QUARANTINED",
        )
        return
    if contract_version != PLANNING_CONTRACT_V2:
        result.normalization_status, result.normalization_issue = "NOT_REQUESTED", None
        return
    if normalization is None or normalization_issue is not None or contract_sha256 is None:
        safe_issues = {
            "PLANNING_QUOTE_NOT_FOUND",
            "PLANNING_QUOTE_INVALID",
            "PLANNING_NORMALIZATION_INVALID",
        }
        result.normalization_status = "UNUSABLE"
        result.normalization_issue = (
            normalization_issue
            if normalization_issue in safe_issues
            else "NORMALIZATION_NOT_AVAILABLE"
        )
        return
    try:
        value = PlanningBriefQuotes.model_validate(normalization.model_dump())
        raw = result.markdown.encode()
        if hashlib.sha256(raw).hexdigest() != result.sha256 or len(raw) != result.size_bytes:
            raise ValueError("Raw result integrity")
        spans = planning_quote_spans(result.markdown, value)
    except (ValidationError, DomainError, ValueError, TypeError, UnicodeError):
        result.normalization_status, result.normalization_issue = (
            "UNUSABLE",
            "NORMALIZATION_QUOTE_INVALID",
        )
        return
    stop = spans["stop_rules"]
    proposal = PlanningBriefProposal(
        job_id=result.job_id,
        project_id=result.project_id,
        user_id=result.user_id,
        attempt_id=result.attempt_id,
        result_sha256=result.sha256,
        contract_version=contract_version,
        contract_sha256=contract_sha256,
        sha256="0" * 64,
        stop_rules_quote=value.stop_rules_quote,
        stop_source_start=stop[0] if stop else None,
        stop_source_end=stop[1] if stop else None,
        warnings_text=json.dumps(value.warnings, ensure_ascii=False),
    )
    rows = []
    for item in value.sections:
        span = spans[item.key]
        rows.append(
            PlanningBriefProposalSection(
                job_id=result.job_id,
                project_id=result.project_id,
                user_id=result.user_id,
                key=item.key,
                content=item.quote,
                source_start=span[0] if span else None,
                source_end=span[1] if span else None,
                uncertainty=item.uncertainty,
            )
        )
    proposal.sha256 = proposal_hash(proposal, rows)
    db.add(proposal)
    db.flush()
    db.add_all(rows)
    db.flush()
    result.normalization_status, result.normalization_issue = "AVAILABLE", None


def _span_valid(markdown: str, content: str | None, start: int | None, end: int | None) -> bool:
    if content is None:
        return start is None and end is None
    return (
        bool(content.strip())
        and start is not None
        and end is not None
        and 0 <= start < end <= len(markdown)
        and markdown[start:end] == content
    )


def _load(
    db: Session, owner: uuid.UUID, project: uuid.UUID, job_id: uuid.UUID
) -> tuple[ResearchPlanningJob, ResearchPlanningResult | None, PlanningBriefProposal | None]:
    job = research_planning.get_job(db, owner, project, job_id)
    result = db.scalar(
        select(ResearchPlanningResult)
        .where(
            ResearchPlanningResult.job_id == job_id,
            ResearchPlanningResult.user_id == owner,
            ResearchPlanningResult.project_id == project,
        )
        .execution_options(populate_existing=True)
    )
    proposal = db.scalar(
        select(PlanningBriefProposal)
        .where(
            PlanningBriefProposal.job_id == job_id,
            PlanningBriefProposal.user_id == owner,
            PlanningBriefProposal.project_id == project,
        )
        .execution_options(populate_existing=True)
    )
    return job, result, proposal


def _verified(
    db: Session,
    job: ResearchPlanningJob,
    result: ResearchPlanningResult | None,
    proposal: PlanningBriefProposal | None,
) -> bool:
    if (
        result is None
        or proposal is None
        or job.status != "COMPLETED"
        or result.disposition != "AVAILABLE"
        or result.normalization_status != "AVAILABLE"
    ):
        return False
    attempt = db.scalar(
        select(ResearchPlanningAttempt).where(
            ResearchPlanningAttempt.id == result.attempt_id,
            ResearchPlanningAttempt.job_id == job.id,
            ResearchPlanningAttempt.project_id == job.project_id,
            ResearchPlanningAttempt.user_id == job.user_id,
        )
    )
    grant = research_planning.get_grant(db, job.user_id, job.project_id, job.grant_id)
    payload = job.manifest_payload
    if not isinstance(payload, dict):
        return False
    if (
        research_briefs.digest(payload) != job.manifest_sha256
        or payload.get("job_id") != str(job.id)
        or payload.get("grant_id") != str(grant.id)
        or payload.get("grant_sha256") != grant.sha256
        or payload.get("grant_sha256") != grant.approved_sha256
        or payload.get("output_contract_version") != grant.output_contract_version
        or payload.get("output_contract_sha256") != grant.output_contract_sha256
        or payload.get("brief_id") != str(grant.brief_id)
        or payload.get("brief_sha256") != grant.brief_sha256
    ):
        return False
    permit = (
        db.scalar(
            select(ResearchExecutionPermit).where(
                ResearchExecutionPermit.id == attempt.permit_id,
                ResearchExecutionPermit.job_id == job.id,
                ResearchExecutionPermit.grant_id == grant.id,
                ResearchExecutionPermit.user_id == job.user_id,
                ResearchExecutionPermit.project_id == job.project_id,
            )
        )
        if attempt is not None
        else None
    )
    if permit is None or permit.manifest_sha256 != job.manifest_sha256:
        return False
    rows = _sections(db, proposal)
    raw = result.markdown.encode()
    return (
        attempt is not None
        and attempt.status == "COMPLETED"
        and proposal.attempt_id == result.attempt_id
        and proposal.result_sha256 == result.sha256
        and hashlib.sha256(raw).hexdigest() == result.sha256
        and len(raw) == result.size_bytes
        and proposal.contract_version == grant.output_contract_version == PLANNING_CONTRACT_V2
        and proposal.contract_sha256 == grant.output_contract_sha256
        and len(rows) == 8
        and {row.key for row in rows} == set(research_briefs.KEYS)
        and proposal_hash(proposal, rows) == proposal.sha256
        and all(
            _span_valid(result.markdown, row.content, row.source_start, row.source_end)
            for row in rows
        )
        and _span_valid(
            result.markdown,
            proposal.stop_rules_quote,
            proposal.stop_source_start,
            proposal.stop_source_end,
        )
    )


def proposal_out(
    db: Session, owner: uuid.UUID, project: uuid.UUID, job_id: uuid.UUID
) -> PlanningBriefProposalOut:
    job, result, proposal = _load(db, owner, project, job_id)
    verified = _verified(db, job, result, proposal)
    rows = _sections(db, proposal) if proposal else []
    gaps = ["AI_QUOTATIONS_ARE_CANDIDATES_NOT_AUTHOR_OR_EXPERIMENTAL_FACTS"]
    if not verified:
        gaps.append("PLANNING_PROPOSAL_NOT_ADOPTABLE")
    if proposal and not any(row.content for row in rows) and not proposal.stop_rules_quote:
        gaps.append("NO_EFFECTIVE_PROPOSED_CONTENT")
    warnings = []
    if proposal is not None:
        try:
            value = json.loads(proposal.warnings_text)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError("Invalid warning snapshot")
            warnings = value
        except (ValueError, TypeError):
            gaps.append("PROPOSAL_WARNING_METADATA_INVALID")
    return PlanningBriefProposalOut(
        job_id=job.id,
        attempt_id=result.attempt_id if result else None,
        result_sha256=result.sha256 if result else None,
        proposal_sha256=proposal.sha256 if proposal else None,
        normalization_status=result.normalization_status if result else "NOT_RECORDED",
        normalization_issue=result.normalization_issue if result else None,
        contract_version=proposal.contract_version if proposal else None,
        sections=[PlanningProposalSectionOut.model_validate(row) for row in rows],
        stop_rules_quote=proposal.stop_rules_quote if proposal else None,
        stop_source_start=proposal.stop_source_start if proposal else None,
        stop_source_end=proposal.stop_source_end if proposal else None,
        warnings=warnings,
        gaps=gaps,
        adoptable=verified
        and proposal is not None
        and bool(any(row.content for row in rows) or proposal.stop_rules_quote),
    )


def _preview(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    job_id: uuid.UUID,
    body: PlanningBriefAdoptionPreviewCreate,
    *,
    lock: bool = False,
) -> tuple[
    PlanningBriefAdoptionPreviewOut,
    ResearchBrief,
    ResearchPlanningResult,
    PlanningBriefProposal,
    dict[str, PlanningBriefProposalSection],
]:
    job, result, proposal = _load(db, owner, project, job_id)
    if not _verified(db, job, result, proposal) or result is None or proposal is None:
        raise DomainError(
            "PLANNING_PROPOSAL_UNAVAILABLE",
            "Only a complete available and program-verified candidate can be selected",
            409,
        )
    if (
        result.sha256 != body.expected_result_sha256
        or proposal.sha256 != body.expected_proposal_sha256
    ):
        raise DomainError(
            "PLANNING_PROPOSAL_CHANGED", "Candidate hashes differ from the reviewed selection", 409
        )
    base = research_briefs.get_brief(db, owner, project, body.base_brief_id)
    if lock:
        from app.models import ResearchProject

        db.scalar(
            select(ResearchProject.id)
            .where(ResearchProject.id == project, ResearchProject.user_id == owner)
            .with_for_update()
        )
    latest = db.scalar(
        select(ResearchBrief.id)
        .where(ResearchBrief.user_id == owner, ResearchBrief.project_id == project)
        .order_by(ResearchBrief.revision.desc())
        .limit(1)
    )
    if (
        latest != base.id
        or base.sha256 != body.expected_base_sha256
        or not research_briefs._intact(db, base)
    ):
        raise DomainError(
            "BRIEF_BASE_CHANGED", "Select the latest intact base revision and its exact hash", 409
        )
    source = job.manifest_payload
    stale = (
        source.get("brief_id") != str(base.id)
        or source.get("brief_sha256") != base.sha256
        or not research_briefs.context_current(db, base)
    )
    proposed = {row.key: row for row in _sections(db, proposal)}
    current = {row.key: row for row in research_briefs._sections(db, base)}
    diffs = []
    for key in body.selected_section_keys:
        content = proposed[key].content
        if content is None:
            raise DomainError(
                "PLANNING_SECTION_UNAVAILABLE",
                "A selected section has no literal candidate quotation",
                409,
            )
        diffs.append(
            PlanningBriefDiffOut(
                key=key,
                current_content=current[key].content,
                proposed_content=content,
                current_origin=current[key].origin_type,
                overwrites_owner_input=current[key].origin_type == "OWNER_INPUT"
                and current[key].content != content,
            )
        )
    if body.include_stop_rules:
        if proposal.stop_rules_quote is None:
            raise DomainError(
                "PLANNING_STOP_RULE_UNAVAILABLE", "No literal stopping rule was proposed", 409
            )
        diffs.append(
            PlanningBriefDiffOut(
                key="stop_rules",
                current_content=base.stop_rules,
                proposed_content=proposal.stop_rules_quote,
                current_origin=base.stop_rules_origin,
                overwrites_owner_input=base.stop_rules_origin in (None, "OWNER_INPUT")
                and base.stop_rules is not None
                and base.stop_rules != proposal.stop_rules_quote,
            )
        )
    effective = any(row.current_content != row.proposed_content for row in diffs)
    warnings = (
        ["OVERWRITES_OWNER_INPUT"] if any(row.overwrites_owner_input for row in diffs) else []
    )
    if stale:
        warnings.append("SOURCE_CONTEXT_DIFFERS_FROM_CURRENT_BASE")
    preview = PlanningBriefAdoptionPreviewOut(
        job_id=job.id,
        base_brief_id=base.id,
        base_sha256=base.sha256,
        result_sha256=result.sha256,
        proposal_sha256=proposal.sha256,
        source_stale=stale,
        effective_changes=effective,
        diffs=diffs,
        warnings=warnings,
        gaps=["NO_NEW_MODEL_CALL_OR_STAGE_GRANT", "METADATA_EVIDENCE_SNAPSHOTS_ARE_INHERITED"],
    )
    return preview, base, result, proposal, proposed


def adoption_preview(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    job_id: uuid.UUID,
    body: PlanningBriefAdoptionPreviewCreate,
) -> PlanningBriefAdoptionPreviewOut:
    with db.no_autoflush:
        return _preview(db, owner, project, job_id, body)[0]


def _request_hash(job_id: uuid.UUID, body: PlanningBriefAdoptionCreate) -> str:
    values = body.model_dump(mode="json")
    values.pop("idempotency_key")
    values["selected_section_keys"] = sorted(values["selected_section_keys"])
    return research_briefs.digest({"job_id": str(job_id), **values})


def adopt_brief(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    job_id: uuid.UUID,
    body: PlanningBriefAdoptionCreate,
) -> PlanningBriefAdoptionOut:
    research_planning.get_job(db, owner, project, job_id)
    request_hash = _request_hash(job_id, body)
    receipt = db.scalar(
        select(PlanningBriefAdoptionReceipt).where(
            PlanningBriefAdoptionReceipt.user_id == owner,
            PlanningBriefAdoptionReceipt.project_id == project,
            PlanningBriefAdoptionReceipt.idempotency_key == body.idempotency_key,
        )
    )
    if receipt is not None:
        if receipt.request_sha256 != request_hash or receipt.job_id != job_id:
            raise DomainError(
                "PLANNING_ADOPTION_KEY_CONFLICT",
                "This selection key already records another immutable adoption",
                409,
            )
        return PlanningBriefAdoptionOut(
            brief=research_briefs.detail_out(
                db, research_briefs.get_brief(db, owner, project, receipt.new_brief_id)
            ),
            receipt=PlanningBriefAdoptionReceiptOut.model_validate(receipt),
        )
    try:
        preview, base, result, proposal, sections = _preview(
            db, owner, project, job_id, body, lock=True
        )
        if not preview.effective_changes:
            raise DomainError(
                "PLANNING_ADOPTION_NO_CHANGE",
                "Selected literal candidates make no effective change",
                409,
            )
        if preview.source_stale and not body.acknowledge_stale_context:
            raise DomainError(
                "PLANNING_ADOPTION_STALE_CONTEXT",
                "Explicitly acknowledge the original planning context before merging into this newer base",
                409,
            )
        values = {
            "idea": base.idea,
            "base_brief_id": base.id,
            "expected_base_sha256": base.sha256,
            "sections": [
                ResearchBriefSectionCreate(key=key, content=sections[key].content)
                for key in body.selected_section_keys
            ],
        }
        if body.include_stop_rules:
            values["stop_rules"] = proposal.stop_rules_quote
        fresh = research_briefs.create_brief(
            db,
            owner,
            project,
            ResearchBriefCreate(**values),
            commit=False,
            derived_sections={
                key: (job_id, result.sha256, sections[key].uncertainty)
                for key in body.selected_section_keys
            },
            derived_stop=(job_id, result.sha256) if body.include_stop_rules else None,
        )
        receipt = PlanningBriefAdoptionReceipt(
            id=uuid.uuid4(),
            user_id=owner,
            project_id=project,
            job_id=job_id,
            new_brief_id=fresh.id,
            base_brief_id=base.id,
            result_sha256=result.sha256,
            proposal_sha256=proposal.sha256,
            request_sha256=request_hash,
            idempotency_key=body.idempotency_key,
            include_stop_rules=body.include_stop_rules,
        )
        db.add(receipt)
        db.commit()
        db.refresh(receipt)
        return PlanningBriefAdoptionOut(
            brief=research_briefs.detail_out(db, fresh),
            receipt=PlanningBriefAdoptionReceiptOut.model_validate(receipt),
        )
    except DomainError:
        db.rollback()
        completed = db.scalar(
            select(PlanningBriefAdoptionReceipt).where(
                PlanningBriefAdoptionReceipt.user_id == owner,
                PlanningBriefAdoptionReceipt.project_id == project,
                PlanningBriefAdoptionReceipt.idempotency_key == body.idempotency_key,
            )
        )
        if (
            completed is not None
            and completed.job_id == job_id
            and completed.request_sha256 == request_hash
        ):
            return PlanningBriefAdoptionOut(
                brief=research_briefs.detail_out(
                    db, research_briefs.get_brief(db, owner, project, completed.new_brief_id)
                ),
                receipt=PlanningBriefAdoptionReceiptOut.model_validate(completed),
            )
        raise
    except IntegrityError:
        db.rollback()
        completed = db.scalar(
            select(PlanningBriefAdoptionReceipt).where(
                PlanningBriefAdoptionReceipt.user_id == owner,
                PlanningBriefAdoptionReceipt.project_id == project,
                PlanningBriefAdoptionReceipt.idempotency_key == body.idempotency_key,
            )
        )
        if (
            completed is not None
            and completed.job_id == job_id
            and completed.request_sha256 == request_hash
        ):
            return PlanningBriefAdoptionOut(
                brief=research_briefs.detail_out(
                    db, research_briefs.get_brief(db, owner, project, completed.new_brief_id)
                ),
                receipt=PlanningBriefAdoptionReceiptOut.model_validate(completed),
            )
        raise DomainError(
            "PLANNING_ADOPTION_CONFLICT",
            "A revision or adoption was committed concurrently; reload the saved receipt",
            409,
        ) from None
