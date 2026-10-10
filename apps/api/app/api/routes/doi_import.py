"""Explicit, owner-reviewed DOI metadata lookup and confirmation."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context
from app.db import get_db
from app.providers.registry import literature_provider
from app.services.doi_import import DoiStatus, confirm_doi, preview_doi

router = APIRouter(prefix="/literature/import/doi", tags=["literature-import"])


class DoiPreviewRequest(BaseModel):
    doi: str = Field(min_length=6, max_length=512)


class DoiPreviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doi: str
    source_hash: str
    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    url: str | None
    status: DoiStatus
    existing_paper_id: uuid.UUID | None
    warning: str | None


class DoiConfirmRequest(DoiPreviewRequest):
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_status: DoiStatus
    existing_paper_id: uuid.UUID | None = None


class DoiConfirmOut(BaseModel):
    created: uuid.UUID | None
    linked: uuid.UUID | None
    skipped: uuid.UUID | None


@router.post("/preview", response_model=DoiPreviewOut)
async def preview(
    body: DoiPreviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> DoiPreviewOut:
    result = await preview_doi(db, context.user.id, literature_provider(), body.doi)
    return DoiPreviewOut.model_validate(result)


@router.post("/confirm", response_model=DoiConfirmOut)
async def confirm(
    body: DoiConfirmRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> DoiConfirmOut:
    result = await confirm_doi(
        db,
        context.user.id,
        literature_provider(),
        body.doi,
        body.expected_hash,
        body.expected_status,
        body.existing_paper_id,
    )
    return DoiConfirmOut(created=result.created, linked=result.linked, skipped=result.skipped)
