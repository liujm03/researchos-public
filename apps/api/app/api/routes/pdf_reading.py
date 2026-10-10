"""The manual original-PDF skill reading entry and owner frozen-source view."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.api.routes.analysis import AnalysisJobOut, approved_job_out
from app.db import get_db
from app.domain.ai import NoteOutputContract
from app.domain.analytical_notes import (
    ApprovedReadingCreate,
    CanonicalNoteOut,
    ReadingPlanCreate,
    ReadingPlanOut,
    ReadingSourceFileContentOut,
)
from app.domain.task_results import ReadingResultEnvelopeOut
from app.services import reading_source_bindings
from app.services.analytical_plans import plan_out, preview_reading_plan
from app.services.canonical_notes import canonical_note_out, get_canonical_note, save_canonical_note
from app.services.pdf_reading import enqueue_pdf_reading, source_out
from app.services.reading_result_envelope import reading_result_envelope
from app.services.result_file_checks import check_result_file

router = APIRouter(tags=["pdf-skill-reading"])


@router.get("/analysis-jobs/{job_id}/result-envelope", response_model=ReadingResultEnvelopeOut)
def result_envelope(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ReadingResultEnvelopeOut:
    return reading_result_envelope(db, context.user.id, job_id)


class ResultFileCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post(
    "/analysis-jobs/{job_id}/result-envelope/check-file", response_model=ReadingResultEnvelopeOut
)
async def result_envelope_file(
    job_id: uuid.UUID,
    body: ResultFileCheckRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ReadingResultEnvelopeOut:
    return await check_result_file(db, context.user.id, job_id)


class PDFPageBatchOut(BaseModel):
    part_index: int
    pages: list[int]


class PDFReadingSourceOut(BaseModel):
    job_id: uuid.UUID
    attachment_id: uuid.UUID
    sha256: str
    page_count: int
    skill_key: str
    skill_version: str
    skill_sha256: str
    render_version: str
    note_output_contract: NoteOutputContract = "PAPER_ANALYSIS_V1"
    page_batches: list[PDFPageBatchOut]


@router.post("/papers/{paper_id}/pdf-reading-jobs", response_model=AnalysisJobOut)
async def create_pdf_reading(
    paper_id: uuid.UUID,
    body: ApprovedReadingCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> AnalysisJobOut:
    return approved_job_out(
        db,
        context.user.id,
        await enqueue_pdf_reading(
            db,
            context.user.id,
            paper_id,
            body.attachment_id,
            idempotency_key=body.idempotency_key,
            approval_plan_id=body.approval_plan_id,
            expected_plan_sha256=body.expected_plan_sha256,
            approved=body.approved,
        ),
    )


@router.get("/analysis-jobs/{job_id}/pdf-source", response_model=PDFReadingSourceOut)
def frozen_source(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PDFReadingSourceOut:
    return PDFReadingSourceOut.model_validate(source_out(db, context.user.id, job_id))


@router.post("/papers/{paper_id}/reading-plans", response_model=ReadingPlanOut)
async def preview_plan(
    paper_id: uuid.UUID,
    body: ReadingPlanCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ReadingPlanOut:
    return plan_out(
        await preview_reading_plan(
            db, context.user.id, paper_id, body.attachment_id, body.collection
        ),
        db=db,
    )


@router.get(
    "/papers/{paper_id}/reading-plans/{plan_id}/source-files",
    response_model=list[ReadingSourceFileContentOut],
)
def reading_source_files(
    paper_id: uuid.UUID,
    plan_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ReadingSourceFileContentOut]:
    plan = reading_source_bindings.owned_plan(db, context.user.id, paper_id, plan_id)
    rows = reading_source_bindings.sources(db, plan)
    reading_source_bindings.validate(plan, rows)
    return [
        ReadingSourceFileContentOut(
            path=row.path,
            role=row.role,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            content=row.content,
        )
        for row in rows
    ]


@router.get("/analysis-jobs/{job_id}/canonical-note", response_model=CanonicalNoteOut)
def canonical_note(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> CanonicalNoteOut:
    return CanonicalNoteOut.model_validate(
        canonical_note_out(get_canonical_note(db, context.user.id, job_id), db=db)
    )


@router.post("/analysis-jobs/{job_id}/canonical-note/save", response_model=CanonicalNoteOut)
async def retry_canonical_save(
    job_id: uuid.UUID, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> CanonicalNoteOut:
    return CanonicalNoteOut.model_validate(
        canonical_note_out(await save_canonical_note(db, context.user.id, job_id), db=db)
    )
