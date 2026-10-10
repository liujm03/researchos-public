"""Bounded owner artifact upload; existing attachment download is reused."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.api.deps import AuthContext, csrf_context
from app.api.pdf_upload import parse_file_form, upload_chunks
from app.core.config import get_settings
from app.db import get_db
from app.domain.experiments import ArtifactType, ExperimentArtifactOut
from app.providers.registry import storage_provider
from app.services.experiment_artifact_upload import upload_experiment_artifact
from app.services.experiments import artifact_out, get_run

router = APIRouter(tags=["experiment-artifacts"])


class ArtifactUploadOut(BaseModel):
    artifact: ExperimentArtifactOut
    duplicate: bool


@router.post(
    "/experiment-runs/{run_id}/artifacts/upload",
    response_model=ArtifactUploadOut,
    status_code=201,
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
async def upload_artifact(
    run_id: uuid.UUID,
    request: Request,
    artifact_type: ArtifactType = Query(default="OTHER"),
    description: str | None = Query(default=None, max_length=4000),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ArtifactUploadOut:
    get_run(db, context.user.id, run_id)
    form = await parse_file_form(request, max_bytes=get_settings().max_upload_mb * 1024 * 1024)
    try:
        file = form["file"]
        assert isinstance(file, UploadFile)
        result = await upload_experiment_artifact(
            db,
            context.user.id,
            run_id,
            upload_chunks(file),
            filename=file.filename,
            content_type=file.content_type,
            artifact_type=artifact_type,
            description=description,
            storage=storage_provider(),
            max_bytes=get_settings().max_upload_mb * 1024 * 1024,
        )
    finally:
        await form.close()
    return ArtifactUploadOut(
        artifact=artifact_out(db, context.user.id, result.artifact), duplicate=result.duplicate
    )
