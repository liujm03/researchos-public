"""Owner-only single article metadata candidates and version-pinned confirmation."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context
from app.db import get_db
from app.providers.registry import literature_provider
from app.services.arxiv_import import ArxivStatus, confirm_arxiv, preview_arxiv

router = APIRouter(prefix="/literature/import/arxiv", tags=["literature-import"])


class ArxivPreviewRequest(BaseModel):
    arxiv_id: str = Field(min_length=6, max_length=512)


class ArxivPreviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    arxiv_id: str
    versioned_id: str
    source_version: int
    doi: str | None
    source_hash: str
    source_updated_at: datetime | None
    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    url: str | None
    pdf_url: str | None
    status: ArxivStatus
    existing_paper_id: uuid.UUID | None
    warning: str | None


class ArxivConfirmRequest(ArxivPreviewRequest):
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_status: ArxivStatus
    existing_paper_id: uuid.UUID | None = None
    expected_version: int = Field(ge=1, le=2_147_483_647)


class ArxivConfirmOut(BaseModel):
    created: uuid.UUID | None
    linked: uuid.UUID | None
    skipped: uuid.UUID | None


@router.post("/preview", response_model=ArxivPreviewOut)
async def preview(
    body: ArxivPreviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ArxivPreviewOut:
    return ArxivPreviewOut.model_validate(
        await preview_arxiv(db, context.user.id, literature_provider("arxiv"), body.arxiv_id)
    )


@router.post("/confirm", response_model=ArxivConfirmOut)
async def confirm(
    body: ArxivConfirmRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ArxivConfirmOut:
    result = await confirm_arxiv(
        db,
        context.user.id,
        literature_provider("arxiv"),
        body.arxiv_id,
        body.expected_hash,
        body.expected_status,
        body.existing_paper_id,
        body.expected_version,
    )
    return ArxivConfirmOut(created=result.created, linked=result.linked, skipped=result.skipped)
