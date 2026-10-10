import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.models import LiteratureIngestJob
from app.providers.registry import reference_manager
from app.services.literature_ingest import (
    cancel_ingest,
    candidate_ids,
    clear_ingests,
    enqueue_ingest,
    get_ingest,
    list_ingests,
    resolve_ingest_paper,
    retry_ingest,
)

router = APIRouter(tags=["literature-ingest"])

IngestStatus = Literal[
    "QUEUED",
    "RUNNING",
    "WAITING_PARSE",
    "WAITING_ANALYSIS",
    "WAITING_CONFIG",
    "WAITING_BUDGET",
    "WAITING_PROVIDER_QUOTA",
    "WAITING_INPUT_REDUCTION",
    "WAITING_REVIEW",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]
IngestStage = Literal["SYNC", "COPY", "PARSE", "ANALYZE", "INBOX", "DONE"]


class IngestRequest(BaseModel):
    provider: Literal["zotero_local", "zotero_web"] | None = None
    copy_pdf: bool = False
    request_analysis: bool = False
    analysis_mode: Literal["FAST", "STANDARD", "DEEP"] = "STANDARD"


class ResolvePaperRequest(BaseModel):
    existing_paper_id: uuid.UUID


class IngestJobOut(BaseModel):
    id: uuid.UUID
    item_key: str
    item_title: str
    provider_key: str
    server_id: str
    library_type: str
    library_id: str
    source_version: int
    attachment_fingerprint: str | None
    status: IngestStatus
    stage: IngestStage
    copy_pdf: bool
    request_analysis: bool
    analysis_mode: Literal["FAST", "STANDARD", "DEEP"]
    paper_id: uuid.UUID | None
    candidate_paper_ids: list[uuid.UUID]
    attachment_id: uuid.UUID | None
    parse_job_id: uuid.UUID | None
    analysis_job_id: uuid.UUID | None
    inbox_item_id: uuid.UUID | None
    warning_code: str | None
    warning_message: str | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    cleared_at: datetime | None


class ClearIngestsOut(BaseModel):
    cleared: int
    cancelled: int


def ingest_out(db: Session, job: LiteratureIngestJob) -> IngestJobOut:
    return IngestJobOut.model_validate(
        {**job.__dict__, "candidate_paper_ids": candidate_ids(db, job.id)}
    )


@router.post(
    "/reference-managers/zotero/items/{item_key}/ingest",
    response_model=IngestJobOut,
    status_code=202,
)
async def create_ingest(
    item_key: str,
    body: IngestRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> IngestJobOut:
    provider = reference_manager()
    job = await enqueue_ingest(
        db,
        context.user.id,
        provider,
        item_key,
        copy_pdf=body.copy_pdf,
        request_analysis=body.request_analysis,
        analysis_mode=body.analysis_mode,
        expected_provider=body.provider,
    )
    return ingest_out(db, job)


@router.get("/literature-jobs", response_model=list[IngestJobOut])
def list_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[IngestJobOut]:
    return [ingest_out(db, job) for job in list_ingests(db, context.user.id, limit)]


@router.post("/literature-jobs/clear", response_model=ClearIngestsOut)
def clear_jobs(
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ClearIngestsOut:
    return ClearIngestsOut.model_validate(clear_ingests(db, context.user.id))


@router.get("/literature-jobs/{job_id}", response_model=IngestJobOut)
def get_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> IngestJobOut:
    return ingest_out(db, get_ingest(db, context.user.id, job_id))


@router.post("/literature-jobs/{job_id}/retry", response_model=IngestJobOut)
def retry_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> IngestJobOut:
    return ingest_out(db, retry_ingest(db, context.user.id, job_id))


@router.post("/literature-jobs/{job_id}/cancel", response_model=IngestJobOut)
def cancel_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> IngestJobOut:
    return ingest_out(db, cancel_ingest(db, context.user.id, job_id))


@router.post("/literature-jobs/{job_id}/resolve-paper", response_model=IngestJobOut)
async def resolve_paper(
    job_id: uuid.UUID,
    body: ResolvePaperRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> IngestJobOut:
    job = await resolve_ingest_paper(
        db, context.user.id, job_id, body.existing_paper_id, reference_manager()
    )
    return ingest_out(db, job)
