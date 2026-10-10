"""Owner-scoped canonical writer identity; historical approval does not upgrade contracts."""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaperAnalysisJob, PaperPDFReadingSource
from app.models_analytical import PaperReadingApproval, PaperReadingApprovalPlan


def valid_writer_binding(
    job: PaperAnalysisJob,
    plan: PaperReadingApprovalPlan | None,
    source: PaperPDFReadingSource | None,
) -> bool:
    """Verify already owner-joined rows without per-job database queries."""
    if (
        plan is None
        or source is None
        or job.source_type != "PDF"
        or job.analysis_scope != "FULL_TEXT"
        or job.provider_key != "codex"
        or plan.user_id != job.user_id
        or plan.paper_id != job.paper_id
        or source.user_id != job.user_id
        or source.job_id != job.id
    ):
        return False
    from app.services.analytical_plans import plan_payload
    from app.services.paper_analysis import _payload_hash

    return not (
        plan.skill_key != "zotero-analytical-writer"
        or source.skill_key != plan.skill_key
        or plan.attachment_id != source.attachment_id
        or plan.sha256 != source.sha256
        or plan.page_count != source.page_count
        or plan.skill_version != source.skill_version
        or plan.skill_sha256 != source.skill_sha256
        or plan.skill_instructions != source.skill_instructions
        or plan.note_output_contract != source.note_output_contract
        or not plan.template_text
        or not plan.template_sha256
        or hashlib.sha256(plan.template_text.encode()).hexdigest() != plan.template_sha256
        or hashlib.sha256(plan.skill_instructions.encode()).hexdigest() != plan.skill_sha256
        or _payload_hash(plan_payload(plan)) != plan.plan_sha256
    )


def approved_writer_plan(db: Session, job: PaperAnalysisJob) -> PaperReadingApprovalPlan | None:
    if job.source_type != "PDF" or job.analysis_scope != "FULL_TEXT" or job.provider_key != "codex":
        return None
    row = db.execute(
        select(PaperReadingApprovalPlan, PaperPDFReadingSource)
        .join(
            PaperReadingApproval,
            (PaperReadingApproval.plan_id == PaperReadingApprovalPlan.id)
            & (PaperReadingApproval.user_id == job.user_id),
        )
        .join(
            PaperPDFReadingSource,
            (PaperPDFReadingSource.job_id == PaperReadingApproval.job_id)
            & (PaperPDFReadingSource.user_id == job.user_id),
        )
        .where(
            PaperReadingApproval.job_id == job.id,
            PaperReadingApprovalPlan.user_id == job.user_id,
            PaperReadingApprovalPlan.paper_id == job.paper_id,
        )
        .execution_options(populate_existing=True)
    ).first()
    if row is None:
        return None
    plan, source = row
    return plan if valid_writer_binding(job, plan, source) else None


def is_current_writer_job(job: PaperAnalysisJob, plan: PaperReadingApprovalPlan | None) -> bool:
    """Check the job contract after its approved binding has been validated."""
    from app.services.paper_analysis import ANALYSIS_VERSION
    from app.services.pdf_reading import CANONICAL_SCHEMA_VERSION, PDF_PROMPT_VERSION

    return bool(
        plan is not None
        and plan.note_output_contract == "CANONICAL_MARKDOWN_V2"
        and job.prompt_version == PDF_PROMPT_VERSION
        and job.schema_version == CANONICAL_SCHEMA_VERSION
        and job.analysis_version == ANALYSIS_VERSION
    )


def uses_current_reading_skill(db: Session, job: PaperAnalysisJob) -> bool:
    return is_current_writer_job(job, approved_writer_plan(db, job))
