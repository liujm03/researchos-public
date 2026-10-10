"""Owner-reviewed local bibliography import; preview never writes research data."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context
from app.db import get_db
from app.domain.bibliography import BibliographyFormat
from app.providers.registry import bibliography_parser
from app.services.bibliography_import import (
    ImportSelection,
    ImportStatus,
    confirm_bibliography,
    preview_bibliography,
)

router = APIRouter(prefix="/bibliography-imports", tags=["bibliography-import"])


class ImportPreviewRequest(BaseModel):
    format: BibliographyFormat
    content: str = Field(min_length=1, max_length=1_048_576)


class ImportRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_key: str
    source_hash: str
    key: str | None
    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    abstract: str | None
    url: str | None
    entry_type: str
    status: ImportStatus
    existing_paper_id: uuid.UUID | None
    warning: str | None


class ImportPreviewOut(BaseModel):
    input_sha256: str
    records: list[ImportRecordOut]


class ImportSelectionIn(BaseModel):
    source_key: str = Field(min_length=1, max_length=120)
    expected_status: ImportStatus
    existing_paper_id: uuid.UUID | None = None


class ImportConfirmRequest(ImportPreviewRequest):
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selections: list[ImportSelectionIn] = Field(min_length=1, max_length=500)


class ImportConfirmOut(BaseModel):
    created: list[uuid.UUID]
    linked: list[uuid.UUID]
    skipped: list[uuid.UUID]


@router.post("/preview", response_model=ImportPreviewOut)
def preview(
    body: ImportPreviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ImportPreviewOut:
    result = preview_bibliography(
        db, context.user.id, bibliography_parser(), body.format, body.content
    )
    return ImportPreviewOut(
        input_sha256=result.input_sha256,
        records=[ImportRecordOut.model_validate(record) for record in result.records],
    )


@router.post("/confirm", response_model=ImportConfirmOut)
def confirm(
    body: ImportConfirmRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ImportConfirmOut:
    result = confirm_bibliography(
        db,
        context.user.id,
        bibliography_parser(),
        body.format,
        body.content,
        body.input_sha256,
        [
            ImportSelection(
                source_key=item.source_key,
                expected_status=item.expected_status,
                existing_paper_id=item.existing_paper_id,
            )
            for item in body.selections
        ],
    )
    return ImportConfirmOut(created=result.created, linked=result.linked, skipped=result.skipped)
