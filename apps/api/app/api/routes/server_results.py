import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.attachment_download import attachment_response
from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.providers import registry
from app.schemas import PageMeta
from app.schemas_server_results import (
    ServerResultNextBriefOut,
    ServerResultNextBriefRequest,
    ServerResultOptions,
    ServerResultOut,
    ServerResultPage,
    ServerResultRetryRequest,
    ServerResultReviewOut,
    ServerResultReviewRequest,
)
from app.services import server_results as service

router = APIRouter(prefix="/projects/{project_id}/server-results", tags=["server-results"])


@router.get("/options", response_model=ServerResultOptions)
def options(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerResultOptions:
    return service.options(db, context.user.id, project_id, limit, cursor)


@router.get("/lookup", response_model=ServerResultOut)
def lookup(
    project_id: uuid.UUID,
    idempotency_key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerResultOut:
    return service.detail_out(db, service.lookup(db, context.user.id, project_id, idempotency_key))


@router.get("", response_model=ServerResultPage)
def list_results(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerResultPage:
    rows, next_cursor = service.list_results(db, context.user.id, project_id, limit, cursor)
    return ServerResultPage(
        items=[service.summary_out(x) for x in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post("/import", response_model=ServerResultOut, status_code=201)
async def import_result(
    project_id: uuid.UUID,
    file: UploadFile = File(),
    package_id: uuid.UUID = Form(),
    idempotency_key: str = Form(min_length=1, max_length=120),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ServerResultOut:
    raw = bytearray()
    try:
        while chunk := await file.read(65536):
            raw.extend(chunk)
            if len(raw) > service.upload_limit():
                raise service.error("RESULT_SIZE_LIMIT", "Result ZIP exceeds upload limit", 413)
    finally:
        await file.close()
    row = await service.import_result(
        db, context.user.id, project_id, package_id, idempotency_key, bytes(raw)
    )
    return service.detail_out(db, row)


@router.get("/{result_id}", response_model=ServerResultOut)
def detail(
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerResultOut:
    return service.detail_out(db, service.get_result(db, context.user.id, project_id, result_id))


@router.post("/{result_id}/reviews", response_model=ServerResultReviewOut)
def review(
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    body: ServerResultReviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ServerResultReviewOut:
    return service.review_result(db, context.user.id, project_id, result_id, body)


@router.post("/{result_id}/next-brief", response_model=ServerResultNextBriefOut, status_code=201)
def next_brief(
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    body: ServerResultNextBriefRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ServerResultNextBriefOut:
    return service.next_brief(db, context.user.id, project_id, result_id, body)


@router.get(
    "/{result_id}/download",
    response_class=Response,
    responses={
        200: {
            "description": "Verified original uploaded ZIP",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def download(
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> Response:
    attachment = service.download_attachment(db, context.user.id, project_id, result_id)
    provider = registry.storage_provider(attachment.storage_provider)
    db.rollback()
    return await attachment_response(attachment, request, provider)


@router.post("/{result_id}/retry-import", response_model=ServerResultOut)
async def retry_import(
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    expected_result_sha256: str = Form(pattern=r"^[0-9a-f]{64}$"),
    input_sha256: str = Form(pattern=r"^[0-9a-f]{64}$"),
    acknowledge_unknown: bool = Form(),
    retry_idempotency_key: str = Form(min_length=1, max_length=120),
    file: UploadFile | None = File(default=None),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ServerResultOut:
    content = None
    if file is not None:
        raw = bytearray()
        try:
            while chunk := await file.read(65536):
                raw.extend(chunk)
                if len(raw) > service.upload_limit():
                    raise DomainError(
                        "RESULT_SIZE_LIMIT",
                        "Recovery ZIP exceeds upload bound",
                        413,
                        details={"committed": False},
                    )
        finally:
            await file.close()
        content = bytes(raw)
    body = ServerResultRetryRequest(
        expected_result_sha256=expected_result_sha256,
        input_sha256=input_sha256,
        acknowledge_unknown=acknowledge_unknown,
        retry_idempotency_key=retry_idempotency_key,
    )
    row = await service.retry_import(db, context.user.id, project_id, result_id, body, content)
    return service.detail_out(db, row)
