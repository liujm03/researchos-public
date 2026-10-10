import uuid
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.domain.ai import AnalysisBudgetMode, PaperAnalysisResult
from app.errors import DomainError
from app.models import (
    AnalysisSettings,
    InboxItem,
    NoteReviewAction,
    Paper,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperPDFReadingSource,
    PaperReadingApproval,
    PaperReadingApprovalPlan,
    PaperResearchNote,
    ResearchEntity,
    ResearchEvent,
    ResearchNoteEvidence,
    ResearchNoteSection,
)
from app.schemas_literature_context import PaperLiteratureContextOut
from app.schemas_note_checks import NoteAutoReviewOut
from app.schemas_note_projects import NoteProjectContextOut
from app.services import note_projects
from app.services.analysis_outcomes import (
    CALL_BUDGET_EVENTS,
    bounded_candidate_result,
    bounded_diagnostics,
    reported_call_tokens,
    reported_job_tokens,
)
from app.services.literature_context import (
    project_literature_contexts,
    zotero_collection_paper_filter,
)
from app.services.note_checks import automatic_note_review
from app.services.note_deletion_state import require_not_permanently_deleted
from app.services.note_trash import selectable_job_clause
from app.services.paper_analysis import (
    acknowledge_uncertain_analysis,
    analysis_settings,
    cancel_analysis,
    monthly_accounted_tokens,
    retry_analysis,
)
from app.services.papers import get_paper
from app.services.research_inbox import (
    decide_inbox,
    get_note,
    review_section,
    sections_for_note,
    verify_note,
)

router = APIRouter(tags=["literature-analysis"])


class AutomationSettingsOut(BaseModel):
    cloud_scope: Literal["NONE", "METADATA_ONLY", "ABSTRACT_ONLY", "FULL_TEXT"]
    budget_mode: AnalysisBudgetMode
    auto_sync_zotero: bool
    auto_copy_pdf: bool
    auto_analyze_paper: bool = Field(
        deprecated=True, description="Automatic analysis is disabled; submit papers explicitly"
    )
    auto_sync_interval_minutes: int
    auto_sync_next_run_at: datetime | None
    auto_sync_last_run_at: datetime | None
    auto_sync_last_error: str | None
    daily_analysis_limit: int
    monthly_token_limit: int
    max_papers_per_sync: int
    max_concurrent_jobs: int
    max_input_tokens_per_job: int
    max_output_tokens_per_job: int


class AutomationSettingsPatch(BaseModel):
    cloud_scope: Literal["NONE", "METADATA_ONLY", "ABSTRACT_ONLY", "FULL_TEXT"] | None = None
    budget_mode: AnalysisBudgetMode | None = None
    auto_sync_zotero: bool | None = None
    auto_copy_pdf: bool | None = None
    auto_analyze_paper: bool | None = Field(
        default=None, deprecated=True, description="Compatibility field; only false is accepted"
    )
    auto_sync_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    daily_analysis_limit: int | None = Field(default=None, ge=0, le=100)
    monthly_token_limit: int | None = Field(default=None, ge=0, le=100_000_000)
    max_papers_per_sync: int | None = Field(default=None, ge=1, le=1000)
    max_input_tokens_per_job: int | None = Field(default=None, ge=500, le=1_000_000)
    max_output_tokens_per_job: int | None = Field(default=None, ge=100, le=100_000)


def settings_out(settings: AnalysisSettings) -> AutomationSettingsOut:
    return AutomationSettingsOut.model_validate(
        {
            name: False if name == "auto_analyze_paper" else getattr(settings, name)
            for name in AutomationSettingsOut.model_fields
        }
    )


@router.get("/settings/literature-automation", response_model=AutomationSettingsOut)
def get_automation_settings(
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AutomationSettingsOut:
    settings = analysis_settings(db, context.user.id)
    db.commit()
    return settings_out(settings)


@router.patch("/settings/literature-automation", response_model=AutomationSettingsOut)
def update_automation_settings(
    body: AutomationSettingsPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> AutomationSettingsOut:
    settings = analysis_settings(db, context.user.id)
    changes = body.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise DomainError("VALIDATION_ERROR", "Automation settings cannot be null", 422)
    if changes.get("auto_analyze_paper") is True:
        raise DomainError(
            "MANUAL_ANALYSIS_ONLY", "Submit papers explicitly to start AI analysis", 422
        )
    if changes.get("budget_mode") == "PROVIDER_QUOTA":
        from app.providers.registry import ai_provider_descriptor

        descriptor = ai_provider_descriptor()
        if descriptor.provider_key != "codex" or not descriptor.configured:
            raise DomainError(
                "BUDGET_MODE_UNSUPPORTED",
                "Provider quota mode requires a configured Codex account provider",
                409,
            )
    reset_schedule = (
        "auto_sync_zotero" in changes and changes["auto_sync_zotero"] != settings.auto_sync_zotero
    ) or "auto_sync_interval_minutes" in changes
    for key, value in changes.items():
        setattr(settings, key, value)
    if reset_schedule:
        settings.auto_sync_next_run_at = None
    db.commit()
    db.refresh(settings)
    return settings_out(settings)


class AICapabilitiesOut(BaseModel):
    provider_key: str
    configured: bool
    model_key: str | None
    cloud_scope: str
    available: bool
    reason_code: str | None
    reason_message: str | None


@router.get("/ai/capabilities", response_model=AICapabilitiesOut)
def ai_capabilities(
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AICapabilitiesOut:
    from app.providers.registry import ai_provider_descriptor

    descriptor = ai_provider_descriptor()
    settings = analysis_settings(db, context.user.id)
    db.commit()
    if descriptor.provider_key != "codex":
        return AICapabilitiesOut(
            provider_key=descriptor.provider_key,
            configured=descriptor.configured,
            model_key=descriptor.model_key,
            cloud_scope=settings.cloud_scope,
            available=False,
            reason_code="PDF_READING_PROVIDER_UNSUPPORTED",
            reason_message="Paper reading requires Codex and the original PDF skill entry",
        )
    return AICapabilitiesOut(
        provider_key=descriptor.provider_key,
        configured=descriptor.configured,
        model_key=descriptor.model_key,
        cloud_scope=settings.cloud_scope,
        available=descriptor.available,
        reason_code=descriptor.reason_code,
        reason_message=descriptor.reason_message,
    )


class AnalysisJobOut(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    analysis_scope: str
    analysis_mode: str
    source_type: Literal["TEXT", "PDF"]
    approval_plan_id: uuid.UUID | None = Field(
        default=None,
        description="Owner-approved analytical reading plan; null for historical workflows",
    )
    uses_current_reading_skill: bool = Field(
        default=False,
        description="Verified owner-bound current Zotero writer/template and frozen Markdown output contract; historical approvals remain false",
    )
    provider_key: str
    model_key: str
    reasoning_effort: str | None
    status: str
    priority: str
    attempt_count: int
    part_count: int
    parts_completed: int
    reserved_tokens: int
    input_tokens: int | None
    output_tokens: int | None
    cost_estimate: float | None
    cost_currency: str | None
    pricing_version: str | None
    error_code: str | None
    error_message: str | None
    queued_at: str
    started_at: str | None
    completed_at: str | None


def job_out(
    job: PaperAnalysisJob,
    *,
    approval_plan_id: uuid.UUID | None = None,
    uses_current_reading_skill: bool = False,
) -> AnalysisJobOut:
    return AnalysisJobOut(
        id=job.id,
        paper_id=job.paper_id,
        analysis_scope=job.analysis_scope,
        analysis_mode=job.analysis_mode,
        source_type=job.source_type,
        approval_plan_id=approval_plan_id,
        uses_current_reading_skill=uses_current_reading_skill,
        provider_key=job.provider_key,
        model_key=job.model_key,
        reasoning_effort=job.reasoning_effort,
        status=job.status,
        priority=job.priority,
        attempt_count=job.attempt_count,
        part_count=job.part_count,
        parts_completed=job.parts_completed,
        reserved_tokens=job.reserved_tokens,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        cost_estimate=float(job.cost_estimate) if job.cost_estimate is not None else None,
        cost_currency=job.cost_currency,
        pricing_version=job.pricing_version,
        error_code=job.error_code,
        error_message=job.error_message,
        queued_at=job.queued_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def approved_job_out(db: Session, user_id: uuid.UUID, job: PaperAnalysisJob) -> AnalysisJobOut:
    """Project the persisted approval, never infer approval from provider/profile."""
    if job.user_id != user_id:
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    plan_id = db.scalar(
        select(PaperReadingApproval.plan_id).where(
            PaperReadingApproval.job_id == job.id,
            PaperReadingApproval.user_id == user_id,
        )
    )
    from app.services.current_reading import uses_current_reading_skill

    return job_out(
        job,
        approval_plan_id=plan_id,
        uses_current_reading_skill=uses_current_reading_skill(db, job),
    )


class AIUsageOut(BaseModel):
    month: str
    used_tokens: int
    budget_accounted_tokens: int
    reserved_tokens: int
    estimated_cost: float | None
    cost_currency: str | None
    unknown_cost_jobs: int


@router.get("/ai/usage", response_model=AIUsageOut)
def ai_usage(
    month: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AIUsageOut:
    zone = ZoneInfo(context.user.timezone)
    local_today = datetime.now(zone).date()
    if month is None:
        first = local_today.replace(day=1)
    else:
        try:
            first = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise DomainError("VALIDATION_ERROR", "month must be YYYY-MM", 422) from exc
    next_month = date(
        first.year + (first.month == 12), 1 if first.month == 12 else first.month + 1, 1
    )
    start = datetime.combine(first, time.min, zone).astimezone(UTC)
    end = datetime.combine(next_month, time.min, zone).astimezone(UTC)
    rows = list(
        db.scalars(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.user_id == context.user.id,
                PaperAnalysisJob.queued_at >= start,
                PaperAnalysisJob.queued_at < end,
            )
        )
    )
    cost_rows = [row.cost_estimate for row in rows if row.cost_estimate is not None]
    currencies = {row.cost_currency for row in rows if row.cost_estimate is not None}
    policy = db.get(AnalysisSettings, context.user.id) or AnalysisSettings(user_id=context.user.id)
    unknown_jobs = {
        row.id for row in rows if row.status == "COMPLETED" and row.cost_estimate is None
    }
    unknown_jobs.update(
        db.scalars(
            select(ResearchEvent.correlation_id).where(
                ResearchEvent.user_id == context.user.id,
                ResearchEvent.event_type.in_(CALL_BUDGET_EVENTS),
                ResearchEvent.occurred_at >= start,
                ResearchEvent.occurred_at < end,
                ResearchEvent.correlation_id.is_not(None),
            )
        )
    )
    return AIUsageOut(
        month=f"{first.year:04d}-{first.month:02d}",
        used_tokens=reported_job_tokens(db, context.user.id, rows)
        + reported_call_tokens(db, context.user.id, start, end),
        budget_accounted_tokens=monthly_accounted_tokens(
            db, rows, policy, period_start=start, period_end=end
        ),
        reserved_tokens=sum(
            row.reserved_tokens
            for row in rows
            if row.status in {"QUEUED", "ANALYZING", "RETRY_WAIT"}
        ),
        estimated_cost=float(sum(cost_rows)) if cost_rows and len(currencies) == 1 else None,
        cost_currency=next(iter(currencies)) if len(currencies) == 1 else None,
        unknown_cost_jobs=len(unknown_jobs),
    )


@router.get("/papers/{paper_id}/analysis-jobs", response_model=list[AnalysisJobOut])
def list_analysis_jobs(
    paper_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[AnalysisJobOut]:
    get_paper(db, context.user.id, paper_id)
    rows = db.execute(
        select(
            PaperAnalysisJob,
            PaperReadingApproval.plan_id,
            PaperReadingApprovalPlan,
            PaperPDFReadingSource,
        )
        .outerjoin(
            PaperReadingApproval,
            (PaperReadingApproval.job_id == PaperAnalysisJob.id)
            & (PaperReadingApproval.user_id == context.user.id),
        )
        .outerjoin(
            PaperReadingApprovalPlan,
            (PaperReadingApprovalPlan.id == PaperReadingApproval.plan_id)
            & (PaperReadingApprovalPlan.user_id == context.user.id)
            & (PaperReadingApprovalPlan.paper_id == paper_id),
        )
        .outerjoin(
            PaperPDFReadingSource,
            (PaperPDFReadingSource.job_id == PaperAnalysisJob.id)
            & (PaperPDFReadingSource.user_id == context.user.id),
        )
        .where(PaperAnalysisJob.paper_id == paper_id, PaperAnalysisJob.user_id == context.user.id)
        .where(selectable_job_clause(context.user.id, PaperAnalysisJob.id))
        .order_by(PaperAnalysisJob.queued_at.desc())
        .limit(100)
    )
    from app.services.current_reading import is_current_writer_job, valid_writer_binding

    return [
        job_out(
            job,
            approval_plan_id=plan_id,
            uses_current_reading_skill=is_current_writer_job(
                job, plan if valid_writer_binding(job, plan, source) else None
            ),
        )
        for job, plan_id, plan, source in rows
    ]


@router.get("/analysis-jobs/{job_id}", response_model=AnalysisJobOut)
def get_analysis_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AnalysisJobOut:
    job = db.scalar(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.id == job_id, PaperAnalysisJob.user_id == context.user.id
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    return approved_job_out(db, context.user.id, job)


@router.post("/analysis-jobs/{job_id}/cancel", response_model=AnalysisJobOut)
def cancel_analysis_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> AnalysisJobOut:
    return approved_job_out(db, context.user.id, cancel_analysis(db, context.user.id, job_id))


class AnalysisResultIssueOut(BaseModel):
    event_id: uuid.UUID
    event_type: str
    job_id: uuid.UUID
    part_id: uuid.UUID | None
    part_index: int | None
    attempt: int
    occurred_at: datetime
    error_code: str | None
    error_message: str | None
    reported_input_tokens: int | None
    reported_output_tokens: int | None
    diagnostics: dict[str, object] | None
    diagnostics_truncated: bool
    candidate_result: PaperAnalysisResult | None
    candidate_result_truncated: bool
    candidate_result_omitted_reason: str | None
    candidate_result_sha256: str | None = None
    revalidation_event_id: uuid.UUID | None = None
    revalidated_at: datetime | None = None


@router.get("/analysis-jobs/{job_id}/result-issues", response_model=list[AnalysisResultIssueOut])
def analysis_result_issues(
    job_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[AnalysisResultIssueOut]:
    if (
        db.scalar(
            select(PaperAnalysisJob.id).where(
                PaperAnalysisJob.id == job_id,
                PaperAnalysisJob.user_id == context.user.id,
            )
        )
        is None
    ):
        raise DomainError("NOT_FOUND", "Analysis job not found", 404)
    require_not_permanently_deleted(db, context.user.id, job_id)
    events = db.scalars(
        select(ResearchEvent)
        .where(
            ResearchEvent.user_id == context.user.id,
            ResearchEvent.correlation_id == job_id,
            ResearchEvent.event_type.in_(CALL_BUDGET_EVENTS),
        )
        .order_by(ResearchEvent.occurred_at.desc(), ResearchEvent.event_id.desc())
        .limit(limit)
        .offset(offset)
    )
    parts = {
        str(part.id): part
        for part in db.scalars(
            select(PaperAnalysisPart).where(
                PaperAnalysisPart.user_id == context.user.id,
                PaperAnalysisPart.job_id == job_id,
            )
        )
    }
    issues: list[AnalysisResultIssueOut] = []
    for event in events:
        from app.services.saved_analysis_results import candidate_sha256, revalidation_for_event

        recovery = revalidation_for_event(db, context.user.id, event.event_id)
        envelope = event.payload.get("result_issue")
        if not isinstance(envelope, dict):
            envelope = {}
        diagnostics, clipped_diagnostics = bounded_diagnostics(envelope.get("diagnostics"))
        candidate, clipped_candidate, omitted_reason = bounded_candidate_result(
            envelope.get("candidate_result")
        )
        part_key = event.payload.get("part_id")
        part = parts.get(part_key) if isinstance(part_key, str) else None
        attempt = event.payload.get("attempt")
        reason = envelope.get("candidate_result_omitted_reason")
        error_code, error_message = envelope.get("error_code"), envelope.get("error_message")

        def reported_token(key: str, payload: dict[str, object] = event.payload) -> int | None:
            value = payload.get(key)
            return (
                value
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                else None
            )

        issues.append(
            AnalysisResultIssueOut(
                event_id=event.event_id,
                event_type=event.event_type,
                job_id=job_id,
                part_id=part.id if part else None,
                part_index=part.part_index if part else None,
                attempt=attempt
                if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt >= 0
                else 0,
                occurred_at=event.occurred_at,
                error_code=error_code[:80] if isinstance(error_code, str) else None,
                error_message=error_message[:2000] if isinstance(error_message, str) else None,
                reported_input_tokens=reported_token("reported_input_tokens"),
                reported_output_tokens=reported_token("reported_output_tokens"),
                diagnostics=diagnostics,
                diagnostics_truncated=envelope.get("diagnostics_truncated") is True
                or clipped_diagnostics,
                candidate_result=PaperAnalysisResult.model_validate(candidate)
                if candidate is not None
                else None,
                candidate_result_sha256=candidate_sha256(candidate) if candidate else None,
                revalidation_event_id=recovery.event_id if recovery else None,
                revalidated_at=recovery.occurred_at if recovery else None,
                candidate_result_truncated=envelope.get("candidate_result_truncated") is True
                or clipped_candidate,
                candidate_result_omitted_reason=(
                    reason[:80] if isinstance(reason, str) else omitted_reason
                )
                if envelope
                else "NOT_RECORDED",
            )
        )
    return issues


class SavedResultRevalidateRequest(BaseModel):
    expected_result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post(
    "/analysis-jobs/{job_id}/result-issues/{event_id}/revalidate",
    response_model=AnalysisJobOut,
)
async def revalidate_analysis_result(
    job_id: uuid.UUID,
    event_id: uuid.UUID,
    body: SavedResultRevalidateRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> AnalysisJobOut:
    from app.services.saved_analysis_results import revalidate_saved_result

    result = await revalidate_saved_result(
        db, context.user.id, job_id, event_id, body.expected_result_sha256
    )
    return approved_job_out(db, context.user.id, result)


@router.post("/analysis-jobs/{job_id}/retry", response_model=AnalysisJobOut)
def retry_analysis_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> AnalysisJobOut:
    return approved_job_out(db, context.user.id, retry_analysis(db, context.user.id, job_id))


class UncertainRetryRequest(BaseModel):
    acknowledge_possible_duplicate_charge: Literal[True]


@router.post("/analysis-jobs/{job_id}/acknowledge-uncertain", response_model=AnalysisJobOut)
def acknowledge_uncertain_analysis_job(
    job_id: uuid.UUID,
    body: UncertainRetryRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> AnalysisJobOut:
    assert body.acknowledge_possible_duplicate_charge is True
    return approved_job_out(
        db, context.user.id, acknowledge_uncertain_analysis(db, context.user.id, job_id)
    )


class EvidenceOut(BaseModel):
    claim_type: str
    source_section: str | None
    source_page: int | None
    source_block_id: uuid.UUID | None
    evidence_text: str | None
    locator: str | None


class NoteSectionOut(BaseModel):
    id: uuid.UUID
    section_key: str
    body_markdown: str | None
    origin_type: str
    review_status: str
    uncertainty: str | None
    evidence: list[EvidenceOut]


class ResearchNoteOut(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    analysis_job_id: uuid.UUID | None
    parent_note_id: uuid.UUID | None
    revision: int
    summary: str | None
    analysis_scope: str
    analysis_mode: str
    created_by: str
    review_status: str
    created_at: str
    sections: list[NoteSectionOut]
    auto_review: NoteAutoReviewOut


def note_out(db: Session, note: PaperResearchNote) -> ResearchNoteOut:
    result: list[NoteSectionOut] = []
    note_sections = sections_for_note(db, note.id)
    for section in note_sections:
        evidence = db.scalars(
            select(ResearchNoteEvidence).where(ResearchNoteEvidence.section_id == section.id)
        )
        result.append(
            NoteSectionOut(
                id=section.id,
                section_key=section.section_key,
                body_markdown=section.body_markdown,
                origin_type=section.origin_type,
                review_status=section.review_status,
                uncertainty=section.uncertainty,
                evidence=[
                    EvidenceOut(
                        claim_type=item.claim_type,
                        source_section=item.source_section,
                        source_page=item.source_page,
                        source_block_id=item.source_block_id,
                        evidence_text=item.evidence_text,
                        locator=item.locator,
                    )
                    for item in evidence
                ],
            )
        )
    return ResearchNoteOut(
        id=note.id,
        paper_id=note.paper_id,
        analysis_job_id=note.analysis_job_id,
        parent_note_id=note.parent_note_id,
        revision=note.revision,
        summary=note.summary,
        analysis_scope=note.analysis_scope,
        analysis_mode=note.analysis_mode,
        created_by=note.created_by,
        review_status=note.review_status,
        created_at=note.created_at.isoformat(),
        sections=result,
        auto_review=automatic_note_review(db, note, note_sections),
    )


@router.get("/papers/{paper_id}/research-notes", response_model=list[ResearchNoteOut])
def list_research_notes(
    paper_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ResearchNoteOut]:
    get_paper(db, context.user.id, paper_id)
    rows = db.scalars(
        select(PaperResearchNote)
        .join(
            ResearchEntity,
            (ResearchEntity.id == PaperResearchNote.id)
            & (ResearchEntity.user_id == context.user.id),
        )
        .where(
            PaperResearchNote.paper_id == paper_id,
            PaperResearchNote.user_id == context.user.id,
            ResearchEntity.deleted_at.is_(None),
        )
        .order_by(PaperResearchNote.revision.desc())
        .limit(50)
    )
    return [note_out(db, row) for row in rows]


@router.get("/research-notes/{note_id}", response_model=ResearchNoteOut)
def get_research_note(
    note_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ResearchNoteOut:
    return note_out(db, get_note(db, context.user.id, note_id))


class SectionReviewRequest(BaseModel):
    action: Literal["CONFIRM", "REJECT", "COMMENT", "EDIT"]
    comment: str | None = None
    edited_body_markdown: str | None = None


@router.post(
    "/research-notes/{note_id}/sections/{section_key}/review", response_model=ResearchNoteOut
)
def review_note_section(
    note_id: uuid.UUID,
    section_key: str,
    body: SectionReviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ResearchNoteOut:
    note = review_section(
        db,
        context.user.id,
        note_id,
        section_key,
        body.action,
        comment=body.comment,
        edited_body=body.edited_body_markdown,
    )
    return note_out(db, note)


@router.post("/research-notes/{note_id}/verify", response_model=ResearchNoteOut)
def verify_research_note(
    note_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ResearchNoteOut:
    return note_out(db, verify_note(db, context.user.id, note_id))


class InboxOut(BaseModel):
    id: uuid.UUID
    item_type: str
    status: str
    note_id: uuid.UUID
    paper_id: uuid.UUID
    paper_title: str
    note_revision: int
    note_review_status: str
    created_at: str
    literature_context: PaperLiteratureContextOut = Field(default_factory=PaperLiteratureContextOut)
    note_classification: NoteProjectContextOut | None = None


class ReviewActionOut(BaseModel):
    id: uuid.UUID
    section_key: str | None
    action: str
    comment: str | None
    reviewed_revision: int
    reviewed_at: str


@router.get("/research-notes/{note_id}/reviews", response_model=list[ReviewActionOut])
def list_note_reviews(
    note_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ReviewActionOut]:
    get_note(db, context.user.id, note_id)
    rows = db.scalars(
        select(NoteReviewAction)
        .where(NoteReviewAction.note_id == note_id)
        .order_by(NoteReviewAction.reviewed_at, NoteReviewAction.id)
    )
    result: list[ReviewActionOut] = []
    for action in rows:
        section = db.get(ResearchNoteSection, action.section_id) if action.section_id else None
        result.append(
            ReviewActionOut(
                id=action.id,
                section_key=section.section_key if section else None,
                action=action.action,
                comment=action.comment,
                reviewed_revision=action.reviewed_revision,
                reviewed_at=action.reviewed_at.isoformat(),
            )
        )
    return result


@router.get("/research-inbox", response_model=list[InboxOut])
def list_inbox(
    status: str | None = Query(default=None),
    project_id: uuid.UUID | None = None,
    unclassified: bool = False,
    collection_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[InboxOut]:
    query = (
        select(InboxItem, PaperResearchNote, Paper)
        .join(PaperResearchNote, PaperResearchNote.id == InboxItem.note_id)
        .join(
            ResearchEntity,
            (ResearchEntity.id == PaperResearchNote.id)
            & (ResearchEntity.user_id == context.user.id),
        )
        .join(Paper, Paper.id == PaperResearchNote.paper_id)
        .where(
            InboxItem.user_id == context.user.id,
            PaperResearchNote.user_id == context.user.id,
            Paper.user_id == context.user.id,
            ResearchEntity.deleted_at.is_(None),
        )
    )
    if status:
        query = query.where(InboxItem.status == status)
    if project_id is not None or unclassified:
        selected = note_projects.matching_note_ids(
            db, context.user.id, project_id=project_id, unclassified=unclassified
        )
        if not selected:
            return []
        query = query.where(PaperResearchNote.id.in_(selected))
    if collection_id is not None:
        query = query.where(zotero_collection_paper_filter(context.user.id, collection_id))
    rows = db.execute(
        query.order_by(InboxItem.created_at.desc(), InboxItem.id.desc()).offset(offset).limit(limit)
    ).all()
    sources = project_literature_contexts(db, context.user.id, [paper.id for _, _, paper in rows])
    classes = note_projects.get_contexts(db, context.user.id, [note.id for _, note, _ in rows])
    return [
        InboxOut(
            id=item.id,
            item_type=item.item_type,
            status=item.status,
            note_id=note.id,
            paper_id=paper.id,
            paper_title=paper.title,
            note_revision=note.revision,
            note_review_status=note.review_status,
            created_at=item.created_at.isoformat(),
            literature_context=sources[paper.id],
            note_classification=classes[note.id],
        )
        for item, note, paper in rows
    ]


class InboxDecisionRequest(BaseModel):
    action: Literal["ACCEPT", "REJECT"]
    comment: str | None = None


@router.post("/research-inbox/{inbox_id}/decision", response_model=InboxOut)
def decide_inbox_item(
    inbox_id: uuid.UUID,
    body: InboxDecisionRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> InboxOut:
    item = decide_inbox(db, context.user.id, inbox_id, body.action, body.comment)
    note = get_note(db, context.user.id, item.note_id)
    paper = get_paper(db, context.user.id, note.paper_id)
    return InboxOut(
        id=item.id,
        item_type=item.item_type,
        status=item.status,
        note_id=note.id,
        paper_id=paper.id,
        paper_title=paper.title,
        note_revision=note.revision,
        note_review_status=note.review_status,
        created_at=item.created_at.isoformat(),
    )
