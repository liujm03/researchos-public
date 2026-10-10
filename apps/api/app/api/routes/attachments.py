import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.api.attachment_download import attachment_response
from app.api.deps import AuthContext, csrf_context, current_context
from app.api.pdf_upload import parse_pdf_form, upload_chunks
from app.core.config import get_settings
from app.db import get_db
from app.errors import DomainError
from app.models import (
    Attachment,
    PaperAttachment,
    PaperParseJob,
    ParsedBlock,
    ParsedDocument,
    ParsedSection,
    ParseWarning,
)
from app.providers.paper_parser.pdfplumber_parser import PdfPlumberParser
from app.providers.registry import storage_provider
from app.services.papers import get_paper
from app.services.parse_jobs import enqueue_parse_job
from app.services.pdf_upload import upload_paper_pdf

router = APIRouter(tags=["attachments"])

ATTACHMENT_DOWNLOAD_CONTENT = {
    mime: {"schema": {"type": "string", "format": "binary"}}
    for mime in (
        "application/pdf", "application/octet-stream", "application/json", "application/zip",
        "text/plain", "text/csv", "image/png", "image/jpeg",
    )
}
ATTACHMENT_DOWNLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Authenticated complete attachment; recorded MIME is preserved",
        "content": ATTACHMENT_DOWNLOAD_CONTENT,
    },
    206: {
        "description": "Authenticated single byte range",
        "content": ATTACHMENT_DOWNLOAD_CONTENT,
        "headers": {
            "Content-Range": {"schema": {"type": "string"}},
            "ETag": {"schema": {"type": "string"}},
        },
    },
    416: {
        "description": "Invalid or unsatisfiable single byte range",
        "headers": {"Content-Range": {"schema": {"type": "string"}}},
    },
}
ATTACHMENT_DOWNLOAD_HEADERS = {
    "parameters": [
        {
            "name": "Range",
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": "Single bytes range: start-end, start-, or -suffix",
        },
        {
            "name": "If-Range",
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": "Apply Range only for an exactly matching strong ETag",
        },
    ]
}


class PaperAttachmentOut(BaseModel):
    id: uuid.UUID
    attachment_id: uuid.UUID | None
    filename: str | None
    size_bytes: int | None
    sha256: str | None
    status: str
    source_version: int | None


class ParseJobOut(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    attachment_id: uuid.UUID
    parsed_document_id: uuid.UUID | None
    status: str
    attempt_count: int
    error_code: str | None
    error_message: str | None


class PdfUploadOut(BaseModel):
    attachment: PaperAttachmentOut
    parse_job: ParseJobOut
    duplicate: bool


def parse_job_out(job: PaperParseJob) -> ParseJobOut:
    return ParseJobOut(
        id=job.id,
        paper_id=job.paper_id,
        attachment_id=job.attachment_id,
        parsed_document_id=job.parsed_document_id,
        status=job.status,
        attempt_count=job.attempt_count,
        error_code=job.error_code,
        error_message=job.error_message,
    )


def paper_attachment_out(attachment: Attachment, link: PaperAttachment) -> PaperAttachmentOut:
    return PaperAttachmentOut(
        id=link.id,
        attachment_id=attachment.id,
        filename=attachment.original_filename,
        size_bytes=attachment.size_bytes,
        sha256=attachment.sha256,
        status=link.status,
        source_version=link.source_version,
    )


@router.post(
    "/papers/{paper_id}/pdf",
    response_model=PdfUploadOut,
    status_code=202,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "additionalProperties": False,
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload_pdf(
    paper_id: uuid.UUID,
    request: Request,
    response: Response,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PdfUploadOut:
    # Authentication, CSRF and Paper ownership precede multipart parsing/spooling.
    get_paper(db, context.user.id, paper_id)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if max_bytes <= 0:
        raise DomainError("CONFIGURATION_ERROR", "PDF upload size limit must be positive", 503)
    form = await parse_pdf_form(request, max_bytes=max_bytes)
    try:
        upload = form["file"]
        assert isinstance(upload, UploadFile)
        result = await upload_paper_pdf(
            db,
            context.user.id,
            paper_id,
            upload_chunks(upload),
            filename=upload.filename,
            content_type=upload.content_type,
            storage=storage_provider(),
            parser=PdfPlumberParser(),
            max_bytes=max_bytes,
        )
    finally:
        await form.close()
    response.headers["Location"] = f"/api/v1/parse-jobs/{result.parse_job.id}"
    return PdfUploadOut(
        attachment=paper_attachment_out(result.attachment, result.link),
        parse_job=parse_job_out(result.parse_job),
        duplicate=result.duplicate,
    )


class ParsedSectionOut(BaseModel):
    id: uuid.UUID
    section_key: str
    title: str | None
    start_page: int | None
    end_page: int | None
    coverage_status: str
    text: str | None
    semantic_key: str | None
    heading_level: int | None
    parent_section_id: uuid.UUID | None
    section_order: int | None


class ParseWarningOut(BaseModel):
    code: str
    message: str
    page_number: int | None


class ParsedDocumentOut(BaseModel):
    id: uuid.UUID
    paper_id: uuid.UUID
    attachment_id: uuid.UUID
    parser_name: str
    parser_version: str
    file_sha256: str
    page_count: int | None
    extracted_characters: int
    status: str
    sections: list[ParsedSectionOut]
    warnings: list[ParseWarningOut]


class ParsedBlockOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    block_index: int
    page_number: int
    text: str


@router.get("/papers/{paper_id}/attachments", response_model=list[PaperAttachmentOut])
def list_paper_attachments(
    paper_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[PaperAttachmentOut]:
    get_paper(db, context.user.id, paper_id)
    rows = db.scalars(
        select(PaperAttachment)
        .where(PaperAttachment.paper_id == paper_id)
        .order_by(PaperAttachment.created_at.desc())
    )
    result: list[PaperAttachmentOut] = []
    for row in rows:
        attachment = db.get(Attachment, row.attachment_id) if row.attachment_id else None
        result.append(
            PaperAttachmentOut(
                id=row.id,
                attachment_id=attachment.id if attachment else None,
                filename=attachment.original_filename if attachment else None,
                size_bytes=attachment.size_bytes if attachment else None,
                sha256=attachment.sha256 if attachment else None,
                status=row.status,
                source_version=row.source_version,
            )
        )
    return result


@router.head("/attachments/{attachment_id}/download", response_class=Response)
@router.get(
    "/attachments/{attachment_id}/download",
    response_class=Response,
    responses=ATTACHMENT_DOWNLOAD_RESPONSES,
    openapi_extra=ATTACHMENT_DOWNLOAD_HEADERS,
)
async def download_attachment(
    attachment_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> Response:
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.user_id == context.user.id,
            Attachment.deleted_at.is_(None),
        )
    )
    if attachment is None:
        raise DomainError("NOT_FOUND", "Attachment not found", 404)
    return await attachment_response(
        attachment, request, storage_provider(attachment.storage_provider)
    )


@router.head("/storage/{key:path}", response_class=Response)
@router.get(
    "/storage/{key:path}",
    response_class=Response,
    responses=ATTACHMENT_DOWNLOAD_RESPONSES,
    openapi_extra=ATTACHMENT_DOWNLOAD_HEADERS,
)
async def download_stored_object(
    key: str,
    request: Request,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> Response:
    """Resolve an opaque storage URL through the owner-scoped attachment registry."""
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.object_key == key,
            Attachment.user_id == context.user.id,
            Attachment.deleted_at.is_(None),
        )
    )
    if attachment is None:
        raise DomainError("NOT_FOUND", "Attachment not found", 404)
    return await attachment_response(
        attachment, request, storage_provider(attachment.storage_provider)
    )


@router.post(
    "/papers/{paper_id}/attachments/{attachment_id}/parse-jobs", response_model=ParseJobOut
)
def create_parse_job(
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ParseJobOut:
    return parse_job_out(
        enqueue_parse_job(
            db,
            context.user.id,
            paper_id,
            attachment_id,
            PdfPlumberParser(),
        )
    )


@router.get("/parse-jobs/{job_id}", response_model=ParseJobOut)
def get_parse_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ParseJobOut:
    job = db.scalar(
        select(PaperParseJob).where(
            PaperParseJob.id == job_id, PaperParseJob.user_id == context.user.id
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Parse job not found", 404)
    return parse_job_out(job)


@router.get("/papers/{paper_id}/parse-jobs", response_model=list[ParseJobOut])
def list_parse_jobs(
    paper_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ParseJobOut]:
    get_paper(db, context.user.id, paper_id)
    jobs = db.scalars(
        select(PaperParseJob)
        .where(PaperParseJob.user_id == context.user.id, PaperParseJob.paper_id == paper_id)
        .order_by(PaperParseJob.queued_at.desc(), PaperParseJob.id.desc())
        .limit(limit)
    )
    return [parse_job_out(job) for job in jobs]


@router.post("/parse-jobs/{job_id}/retry", response_model=ParseJobOut)
def retry_parse_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ParseJobOut:
    job = db.scalar(
        select(PaperParseJob).where(
            PaperParseJob.id == job_id, PaperParseJob.user_id == context.user.id
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Parse job not found", 404)
    if job.status != "FAILED":
        raise DomainError("CONFLICT", "Only failed parse jobs can be retried", 409)
    job.status = "QUEUED"
    job.error_code = None
    job.error_message = None
    db.commit()
    return parse_job_out(job)


def _owned_document(db: Session, user_id: uuid.UUID, document_id: uuid.UUID) -> ParsedDocument:
    document = db.get(ParsedDocument, document_id)
    if document is None:
        raise DomainError("NOT_FOUND", "Parsed document not found", 404)
    get_paper(db, user_id, document.paper_id)
    return document


@router.get("/papers/{paper_id}/parsed-documents", response_model=list[ParsedDocumentOut])
def list_parsed_documents(
    paper_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ParsedDocumentOut]:
    get_paper(db, context.user.id, paper_id)
    rows = db.scalars(
        select(ParsedDocument)
        .where(ParsedDocument.paper_id == paper_id)
        .order_by(ParsedDocument.created_at.desc())
        .limit(20)
    )
    return [_document_out(db, row) for row in rows]


def _document_out(db: Session, document: ParsedDocument) -> ParsedDocumentOut:
    sections = db.scalars(
        select(ParsedSection)
        .where(ParsedSection.document_id == document.id)
        .order_by(
            case((ParsedSection.section_order.is_(None), 1), else_=0),
            ParsedSection.section_order,
            ParsedSection.start_page,
            ParsedSection.section_key,
        )
    )
    warnings = db.scalars(select(ParseWarning).where(ParseWarning.document_id == document.id))
    return ParsedDocumentOut(
        id=document.id,
        paper_id=document.paper_id,
        attachment_id=document.attachment_id,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        file_sha256=document.file_sha256,
        page_count=document.page_count,
        extracted_characters=document.extracted_characters,
        status=document.status,
        sections=[
            ParsedSectionOut(
                id=section.id,
                section_key=section.section_key,
                title=section.title,
                start_page=section.start_page,
                end_page=section.end_page,
                coverage_status=section.coverage_status,
                text=section.text,
                semantic_key=section.semantic_key,
                heading_level=section.heading_level,
                parent_section_id=section.parent_section_id,
                section_order=section.section_order,
            )
            for section in sections
        ],
        warnings=[
            ParseWarningOut(
                code=warning.code, message=warning.message, page_number=warning.page_number
            )
            for warning in warnings
        ],
    )


@router.get("/parsed-documents/{document_id}", response_model=ParsedDocumentOut)
def get_parsed_document(
    document_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ParsedDocumentOut:
    return _document_out(db, _owned_document(db, context.user.id, document_id))


@router.get("/parsed-documents/{document_id}/blocks", response_model=list[ParsedBlockOut])
def list_parsed_blocks(
    document_id: uuid.UUID,
    after_index: int = Query(default=-1, ge=-1),
    limit: int = Query(default=100, ge=1, le=500),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ParsedBlockOut]:
    _owned_document(db, context.user.id, document_id)
    rows = db.scalars(
        select(ParsedBlock)
        .where(ParsedBlock.document_id == document_id, ParsedBlock.block_index > after_index)
        .order_by(ParsedBlock.block_index)
        .limit(limit)
    )
    return [
        ParsedBlockOut(
            id=row.id,
            document_id=row.document_id,
            block_index=row.block_index,
            page_number=row.page_number,
            text=row.text,
        )
        for row in rows
    ]
