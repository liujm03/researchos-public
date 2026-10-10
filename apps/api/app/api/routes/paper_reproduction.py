"""Owner-reviewed frozen paper sources create Codex drafts, never model calls."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.api.routes.codex import CodexTaskOut, CodexTaskSummaryOut
from app.db import get_db
from app.models import CodexTask, PaperReproductionContext
from app.schemas_paper_reproduction import (
    PaperReproductionCreateRequest,
    PaperReproductionPreviewOut,
    PaperReproductionPreviewRequest,
    ReproductionSourceContentOut,
    ReproductionSourcePage,
)
from app.services import canonical_reproduction
from app.services import paper_reproduction as service
from app.services.papers import get_paper

router = APIRouter(tags=["paper-reproduction"])


@router.get("/papers/{paper_id}/reproduction-sources", response_model=ReproductionSourcePage)
def sources(
    paper_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ReproductionSourcePage:
    return canonical_reproduction.list_sources(db, context.user.id, paper_id, limit, cursor)


@router.get(
    "/papers/{paper_id}/reproduction-sources/{canonical_id}",
    response_model=ReproductionSourceContentOut,
)
def source_content(
    paper_id: uuid.UUID,
    canonical_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ReproductionSourceContentOut:
    return canonical_reproduction.source_content(db, context.user.id, paper_id, canonical_id)


@router.post(
    "/papers/{paper_id}/reproduction-tasks/preview", response_model=PaperReproductionPreviewOut
)
async def preview(
    paper_id: uuid.UUID,
    body: PaperReproductionPreviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PaperReproductionPreviewOut:
    selection = body.selection()
    result = (
        await canonical_reproduction.preview_canonical_context(
            db, context.user.id, paper_id, selection
        )
        if selection.canonical_note_id
        else service.preview_context(db, context.user.id, paper_id, selection)
    )
    return PaperReproductionPreviewOut.model_validate(result)


@router.post("/papers/{paper_id}/reproduction-tasks", response_model=CodexTaskOut, status_code=201)
async def create(
    paper_id: uuid.UUID,
    body: PaperReproductionCreateRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> CodexTaskOut:
    selection = body.selection()
    arguments: dict[str, Any] = dict(
        title=body.title,
        instructions=body.instructions,
        workspace_id=body.workspace_id,
        mode=body.mode,
        expected_context_sha256=body.expected_context_sha256,
        idempotency_key=body.idempotency_key,
    )
    task = (
        await canonical_reproduction.create_canonical_draft(
            db, context.user.id, paper_id, selection, **arguments
        )
        if selection.canonical_note_id
        else service.create_reproduction_draft(
            db,
            context.user.id,
            paper_id,
            selection,
            **arguments,
        )
    )
    return CodexTaskOut.model_validate(task)


@router.get("/papers/{paper_id}/reproduction-tasks", response_model=list[CodexTaskSummaryOut])
def history(
    paper_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[CodexTaskSummaryOut]:
    get_paper(db, context.user.id, paper_id)
    rows = db.scalars(
        select(CodexTask)
        .join(PaperReproductionContext, PaperReproductionContext.task_id == CodexTask.id)
        .where(
            CodexTask.user_id == context.user.id,
            PaperReproductionContext.user_id == context.user.id,
            PaperReproductionContext.paper_id == paper_id,
        )
        .order_by(CodexTask.created_at.desc(), CodexTask.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [CodexTaskSummaryOut.model_validate(row) for row in rows]


@router.get("/codex/tasks/{task_id}/paper-context", response_model=PaperReproductionPreviewOut)
def frozen_context(
    task_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PaperReproductionPreviewOut:
    return PaperReproductionPreviewOut.model_validate(
        service.context_out(db, context.user.id, task_id)
    )
