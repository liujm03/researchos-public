"""Private document artifacts, bounded source approval and durable build recovery."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.attachment_download import _byte_range
from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.models import Attachment
from app.models_manuscript_builds import (
    ManuscriptBuild,
    ManuscriptBuildAttempt,
    ManuscriptBuildOperation,
)
from app.models_server_results import ServerResult
from app.schemas import PageMeta
from app.schemas_manuscript_builds import (
    BuildCancel,
    BuildCreate,
    BuildOperationReceipt,
    BuildOptions,
    BuildOut,
    BuildPage,
    BuildPreview,
    BuildRetry,
    BuildSelection,
    BuildSummary,
)
from app.schemas_server_results import ServerResultOut, ServerResultPage
from app.services import manuscript_builds as service
from app.services import publications, server_results
from app.services.common import cursor_filter, encode_cursor

router = APIRouter(
    prefix="/projects/{project_id}/publications/{publication_id}/builds", tags=["manuscript-builds"]
)


def receipt(
    db: Session, row: ManuscriptBuild, kind: Literal["create", "cancel", "retry"], key: str
) -> BuildOut:
    result = service.detail(db, row)
    if kind == "create":
        value = row.request_sha256
    else:
        action = db.scalar(
            select(ManuscriptBuildOperation).where(
                ManuscriptBuildOperation.build_id == row.id,
                ManuscriptBuildOperation.user_id == row.user_id,
                ManuscriptBuildOperation.kind == kind,
                ManuscriptBuildOperation.idempotency_key == key,
            )
        )
        if action is None:
            raise service.fail("NOT_FOUND", "Owned build operation not found", 404)
        value = action.request_sha256
    result.operation_receipt = BuildOperationReceipt(
        kind=kind, idempotency_key=key, request_sha256=value
    )
    return result


@router.get("/options", response_model=BuildOptions)
async def options(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> BuildOptions:
    publications.get(db, context.user.id, project_id, publication_id)
    db.rollback()
    return await service.options()


@router.get("/result-sources", response_model=ServerResultPage)
def result_sources(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerResultPage:
    publications.get(db, context.user.id, project_id, publication_id)
    rows = list(
        db.scalars(
            select(ServerResult)
            .where(
                ServerResult.user_id == context.user.id,
                ServerResult.project_id == project_id,
                ServerResult.status == "READY",
                cursor_filter(ServerResult, cursor),
            )
            .order_by(ServerResult.created_at.desc(), ServerResult.id.desc())
            .limit(limit + 1)
        )
    )
    return ServerResultPage(
        items=[server_results.summary_out(r) for r in rows[:limit]],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None,
        ),
    )


@router.get("/result-sources/{result_id}", response_model=ServerResultOut)
def result_source(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    result_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ServerResultOut:
    publications.get(db, context.user.id, project_id, publication_id)
    return server_results.detail_out(
        db, server_results.get_result(db, context.user.id, project_id, result_id)
    )


@router.post("/preview", response_model=BuildPreview)
async def preview(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    body: BuildSelection,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> BuildPreview:
    return (await service.prepare(db, context.user.id, project_id, publication_id, body)).preview


@router.post("", response_model=BuildOut, status_code=201)
async def create(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    body: BuildCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> BuildOut:
    return receipt(
        db,
        await service.create(db, context.user.id, project_id, publication_id, body),
        "create",
        body.idempotency_key,
    )


@router.get("", response_model=BuildPage)
def list_builds(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> BuildPage:
    publications.get(db, context.user.id, project_id, publication_id)
    rows = list(
        db.scalars(
            select(ManuscriptBuild)
            .where(
                ManuscriptBuild.user_id == context.user.id,
                ManuscriptBuild.publication_id == publication_id,
                cursor_filter(ManuscriptBuild, cursor),
            )
            .order_by(ManuscriptBuild.created_at.desc(), ManuscriptBuild.id.desc())
            .limit(limit + 1)
        )
    )
    return BuildPage(
        items=[BuildSummary.model_validate(r) for r in rows[:limit]],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None,
        ),
    )


@router.get("/lookup", response_model=BuildOut)
def lookup(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> BuildOut:
    return receipt(
        db, service.lookup(db, context.user.id, project_id, publication_id, key), "create", key
    )


@router.get("/{build_id}", response_model=BuildOut)
def get(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    build_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> BuildOut:
    return service.detail(
        db, service.get(db, context.user.id, project_id, publication_id, build_id)
    )


@router.post("/{build_id}/cancel", response_model=BuildOut)
async def cancel(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    build_id: uuid.UUID,
    body: BuildCancel,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> BuildOut:
    return receipt(
        db,
        await service.operate(
            db,
            service.get(db, context.user.id, project_id, publication_id, build_id),
            "cancel",
            body,
        ),
        "cancel",
        body.idempotency_key,
    )


@router.post("/{build_id}/retry", response_model=BuildOut)
async def retry(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    build_id: uuid.UUID,
    body: BuildRetry,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> BuildOut:
    return receipt(
        db,
        await service.operate(
            db,
            service.get(db, context.user.id, project_id, publication_id, build_id),
            "retry",
            body,
        ),
        "retry",
        body.idempotency_key,
    )


@router.get("/{build_id}/operations/lookup", response_model=BuildOut)
def operation_lookup(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    build_id: uuid.UUID,
    kind: Literal["cancel", "retry"],
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> BuildOut:
    return receipt(
        db, service.get(db, context.user.id, project_id, publication_id, build_id), kind, key
    )


@router.get("/{build_id}/download")
async def download(
    project_id: uuid.UUID,
    publication_id: uuid.UUID,
    build_id: uuid.UUID,
    request: Request,
    kind: Literal["source", "pdf", "log"],
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> Response:
    row = service.get(db, context.user.id, project_id, publication_id, build_id)
    identity = getattr(row, kind + "_attachment_id")
    if kind == "source" and identity is None:
        identity = row.input_source_attachment_id
    attachment = db.scalar(
        select(Attachment)
        .where(Attachment.id == identity, Attachment.user_id == context.user.id)
        .execution_options(populate_existing=True)
    )
    limit = {"source": 40 * 1024 * 1024, "pdf": 16 * 1024 * 1024, "log": 2 * 1024 * 1024}[kind]
    if attachment is None or attachment.deleted_at is not None or attachment.size_bytes > limit:
        raise service.fail(
            "BUILD_ARTIFACT_UNAVAILABLE", "Actual saved owner artifact is unavailable"
        )
    if kind == "source" and identity == row.input_source_attachment_id:
        if attachment.sha256 != row.input_source_zip_sha256:
            raise service.fail("BUILD_ARTIFACT_CHANGED", "Original source ZIP metadata changed")
    else:
        attempt = db.scalar(
            select(ManuscriptBuildAttempt)
            .where(
                ManuscriptBuildAttempt.build_id == row.id,
                ManuscriptBuildAttempt.user_id == context.user.id,
                getattr(ManuscriptBuildAttempt, kind + "_attachment_id") == identity,
            )
            .order_by(ManuscriptBuildAttempt.started_at.desc())
            .limit(1)
        )
        if attempt is None:
            raise service.fail(
                "BUILD_ARTIFACT_CHANGED", "Artifact is not bound to a real build attempt"
            )
        if kind in {"pdf", "log"} and (
            not attempt.result_payload
            or attempt.result_payload.get(kind + "_sha256") != attachment.sha256
            or attempt.result_payload.get(kind + "_size_bytes") != attachment.size_bytes
        ):
            raise service.fail("BUILD_ARTIFACT_CHANGED", "Compiler artifact receipt hash changed")
        if kind == "source" and (
            attempt.source_zip_sha256 != attachment.sha256
            or attempt.source_zip_size_bytes != attachment.size_bytes
            or row.source_zip_sha256 != attachment.sha256
            or row.source_zip_size_bytes != attachment.size_bytes
        ):
            raise service.fail("BUILD_ARTIFACT_CHANGED", "Compiled ZIP receipt changed")
    key, provider, expected, size, mime = (
        attachment.object_key,
        attachment.storage_provider,
        attachment.sha256,
        attachment.size_bytes,
        attachment.mime_type,
    )
    db.rollback()
    raw = await service.read_object(provider, key, expected, size)
    etag = '"' + expected + '"'
    headers = {
        "ETag": etag,
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'attachment; filename="manuscript-{build_id}.{ {"source": "zip", "pdf": "pdf", "log": "log"}[kind] }"',
    }
    asked = (
        request.headers.get("range") if request.headers.get("if-range") in {None, etag} else None
    )
    interval = _byte_range(asked, len(raw))
    if interval:
        start, end = interval
        headers["Content-Range"] = f"bytes {start}-{end - 1}/{len(raw)}"
        return Response(raw[start:end], status_code=206, headers=headers, media_type=mime)
    return Response(raw, headers=headers, media_type=mime)
