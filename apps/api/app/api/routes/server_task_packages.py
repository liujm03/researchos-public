import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.attachment_download import attachment_response
from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.providers import registry
from app.schemas import PageMeta
from app.schemas_server_task_packages import (
    ServerTaskPackageCreateRequest,
    ServerTaskPackageOptions,
    ServerTaskPackageOut,
    ServerTaskPackagePage,
    ServerTaskPackagePreviewOut,
    ServerTaskPackageRetryRequest,
    ServerTaskPackageSelection,
)
from app.services import server_task_packages as service

router = APIRouter(
    prefix="/projects/{project_id}/server-task-packages", tags=["server-task-packages"]
)


@router.get("/options", response_model=ServerTaskPackageOptions)
def options(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    brief_cursor: str | None = None,
    archive_cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerTaskPackageOptions:
    return service.options(db, context.user.id, project_id, limit, brief_cursor, archive_cursor)


@router.post("/preview", response_model=ServerTaskPackagePreviewOut)
def preview(
    project_id: uuid.UUID,
    body: ServerTaskPackageSelection,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ServerTaskPackagePreviewOut:
    return service.preview(db, context.user.id, project_id, body)


@router.get("", response_model=ServerTaskPackagePage)
def list_packages(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerTaskPackagePage:
    rows, next_cursor = service.list_packages(db, context.user.id, project_id, limit, cursor)
    return ServerTaskPackagePage(
        items=[service.summary_out(x) for x in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post("", response_model=ServerTaskPackageOut, status_code=201)
async def create_package(
    project_id: uuid.UUID,
    body: ServerTaskPackageCreateRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ServerTaskPackageOut:
    row = await service.create_package(db, context.user.id, project_id, body)
    return service.detail_out(db, row)


@router.get("/{package_id}", response_model=ServerTaskPackageOut)
def detail(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerTaskPackageOut:
    return service.detail_out(db, service.get_package(db, context.user.id, project_id, package_id))


@router.post("/{package_id}/retry-save", response_model=ServerTaskPackageOut)
async def retry_save(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    body: ServerTaskPackageRetryRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ServerTaskPackageOut:
    return service.detail_out(
        db, await service.retry_save(db, context.user.id, project_id, package_id, body)
    )


@router.get(
    "/{package_id}/download",
    response_class=Response,
    responses={
        200: {
            "description": "Authenticated original ZIP bytes",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        },
        206: {
            "description": "Authenticated single ZIP byte range",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {"Content-Range": {"schema": {"type": "string"}}},
        },
        416: {"description": "Invalid or unsatisfiable single byte range"},
    },
    openapi_extra={
        "parameters": [
            {"name": "Range", "in": "header", "required": False, "schema": {"type": "string"}},
            {"name": "If-Range", "in": "header", "required": False, "schema": {"type": "string"}},
        ]
    },
)
async def download(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> Response:
    attachment = service.download_attachment(db, context.user.id, project_id, package_id)
    provider = registry.storage_provider(attachment.storage_provider)
    db.rollback()
    return await attachment_response(attachment, request, provider)
