"""Owner-selected, readonly source registration of existing private project archives."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas_archive_jobs import (
    ArchiveJobCreate,
    ArchiveJobEventOut,
    ArchiveJobListOut,
    ArchiveJobOut,
    ArchivePolicyOut,
    ArchivePolicyPatch,
)
from app.schemas_project_archives import (
    ArchiveFileOut,
    ArchiveImportRequest,
    ArchiveInventoryOut,
    ArchiveStatusOut,
)
from app.services import archive_jobs, archive_worker
from app.services import project_archive_inventory as service

router = APIRouter(tags=["project-archives"])


@router.get("/projects/{project_id}/archive/policy", response_model=ArchivePolicyOut)
def get_archive_policy(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ArchivePolicyOut:
    return ArchivePolicyOut.model_validate(
        archive_jobs.binding_for(db, context.user.id, project_id)
    )


@router.patch("/projects/{project_id}/archive/policy", response_model=ArchivePolicyOut)
def patch_archive_policy(
    project_id: uuid.UUID,
    body: ArchivePolicyPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ArchivePolicyOut:
    return ArchivePolicyOut.model_validate(
        archive_jobs.update_policy(db, context.user.id, project_id, body)
    )


@router.get("/projects/{project_id}/archive/jobs", response_model=ArchiveJobListOut)
def list_archive_jobs(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ArchiveJobListOut:
    return ArchiveJobListOut(
        items=[
            ArchiveJobOut.model_validate(row)
            for row in archive_jobs.list_jobs(db, context.user.id, project_id)
        ]
    )


@router.post("/projects/{project_id}/archive/jobs", response_model=ArchiveJobOut, status_code=201)
def create_archive_job(
    project_id: uuid.UUID,
    body: ArchiveJobCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ArchiveJobOut:
    binding = archive_jobs.binding_for(db, context.user.id, project_id)
    return ArchiveJobOut.model_validate(archive_jobs.enqueue(db, binding, body.tag))


@router.get(
    "/projects/{project_id}/archive/jobs/{job_id}/events", response_model=list[ArchiveJobEventOut]
)
def get_archive_job_events(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ArchiveJobEventOut]:
    return [
        ArchiveJobEventOut.model_validate(row)
        for row in archive_jobs.job_events(db, context.user.id, project_id, job_id)
    ]


@router.post("/projects/{project_id}/archive/jobs/{job_id}/cancel", response_model=ArchiveJobOut)
def cancel_archive_job(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ArchiveJobOut:
    return ArchiveJobOut.model_validate(
        archive_jobs.cancel_queued(db, context.user.id, project_id, job_id)
    )


@router.post("/projects/{project_id}/archive/jobs/{job_id}/reconcile", response_model=ArchiveJobOut)
async def reconcile_archive_job(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ArchiveJobOut:
    archive_worker.quarantine_expired(db, context.user.id)
    job = archive_jobs.get_job(db, context.user.id, project_id, job_id)
    return ArchiveJobOut.model_validate(await archive_worker.reconcile(db, job))


@router.get("/project-archives/capability", response_model=ArchiveStatusOut)
def archive_capability(context: AuthContext = Depends(current_context)) -> ArchiveStatusOut:
    return service.capability()


@router.get("/projects/{project_id}/archive", response_model=ArchiveInventoryOut)
def project_archive(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ArchiveInventoryOut:
    return service.inventory(db, context.user.id, project_id)


@router.post("/projects/{project_id}/archive/import", response_model=ArchiveInventoryOut)
async def import_archive(
    project_id: uuid.UUID,
    body: ArchiveImportRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ArchiveInventoryOut:
    return await service.import_inventory(db, context.user.id, project_id, body.workspace_key)


@router.get(
    "/projects/{project_id}/archive/versions/{version_id}/files",
    response_model=list[ArchiveFileOut],
)
def archive_files(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ArchiveFileOut]:
    return service.version_files(db, context.user.id, project_id, version_id)
