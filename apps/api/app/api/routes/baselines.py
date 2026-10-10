"""Owner baseline catalog and explicit readonly materials checks."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import schemas_baselines as dto
from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas import PageMeta
from app.services import baselines as service

router = APIRouter(tags=["baselines"])


@router.get("/baselines/capability", response_model=dto.BaselineCapabilityOut)
def capability(context: AuthContext = Depends(current_context)) -> dto.BaselineCapabilityOut:
    return service.capability()


@router.get("/projects/{project_id}/baselines", response_model=dto.BaselinePage)
def baselines(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselinePage:
    rows, next_cursor = service.list_baselines(db, context.user.id, project_id, limit, cursor)
    return dto.BaselinePage(
        items=[dto.BaselineOut.model_validate(row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post("/projects/{project_id}/baselines", response_model=dto.BaselineOut, status_code=201)
def create_baseline(
    project_id: uuid.UUID,
    body: dto.BaselineCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> dto.BaselineOut:
    return dto.BaselineOut.model_validate(
        service.create_baseline(db, context.user.id, project_id, body)
    )


@router.get("/baselines/{baseline_id}", response_model=dto.BaselineOut)
def baseline(
    baseline_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineOut:
    return dto.BaselineOut.model_validate(service.get_baseline(db, context.user.id, baseline_id))


@router.get("/baselines/{baseline_id}/versions", response_model=dto.BaselineVersionPage)
def versions(
    baseline_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineVersionPage:
    rows, next_cursor = service.list_versions(db, context.user.id, baseline_id, limit, cursor)
    return dto.BaselineVersionPage(
        items=[service.version_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post(
    "/baselines/{baseline_id}/versions", response_model=dto.BaselineVersionOut, status_code=201
)
def create_version(
    baseline_id: uuid.UUID,
    body: dto.BaselineVersionCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> dto.BaselineVersionOut:
    return service.version_out(db, service.create_version(db, context.user.id, baseline_id, body))


@router.get("/baseline-versions/{version_id}", response_model=dto.BaselineVersionOut)
def version(
    version_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineVersionOut:
    return service.version_out(db, service.get_version(db, context.user.id, version_id))


@router.post(
    "/baseline-versions/{version_id}/check-materials", response_model=dto.BaselineMaterialCheckOut
)
async def check_materials(
    version_id: uuid.UUID,
    body: dto.BaselineMaterialCheckCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> dto.BaselineMaterialCheckOut:
    return service.check_out(
        db, await service.check_materials(db, context.user.id, version_id, body)
    )


@router.get("/baseline-versions/{version_id}/checks", response_model=dto.BaselineMaterialCheckPage)
def checks(
    version_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineMaterialCheckPage:
    rows, next_cursor = service.list_checks(db, context.user.id, version_id, limit, cursor)
    return dto.BaselineMaterialCheckPage(
        items=[service.check_summary(row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.get(
    "/baseline-versions/{version_id}/checks/{check_id}", response_model=dto.BaselineMaterialCheckOut
)
def check(
    version_id: uuid.UUID,
    check_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineMaterialCheckOut:
    service.get_version(db, context.user.id, version_id)
    return service.check_out(db, service.get_check(db, context.user.id, version_id, check_id))


@router.get(
    "/projects/{project_id}/baseline-inputs/source-jobs", response_model=dto.BaselineSourceJobPage
)
def source_jobs(
    project_id: uuid.UUID,
    source_job_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineSourceJobPage:
    rows, next_cursor = service.source_jobs(
        db, context.user.id, project_id, limit, cursor, source_job_id
    )
    return dto.BaselineSourceJobPage(
        items=rows, page=PageMeta(limit=limit, next_cursor=next_cursor)
    )


@router.get(
    "/projects/{project_id}/baseline-inputs/source-jobs/{source_job_id}/files",
    response_model=dto.BaselineSourceFilePage,
)
def source_files(
    project_id: uuid.UUID,
    source_job_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineSourceFilePage:
    rows, next_cursor = service.source_files(
        db, context.user.id, project_id, source_job_id, limit, cursor
    )
    return dto.BaselineSourceFilePage(
        items=rows, page=PageMeta(limit=limit, next_cursor=next_cursor)
    )
