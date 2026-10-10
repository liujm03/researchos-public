import re
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.models_repository_assets import RepositoryAssetPlanFile
from app.schemas import PageMeta
from app.schemas_repository_assets import (
    AssetCapabilityOut,
    AssetEventOut,
    AssetFilePage,
    AssetJobOut,
    AssetJobPage,
    AssetPlanApprove,
    AssetPlanCreate,
    AssetPlanFileOut,
    AssetPlanFilePage,
    AssetPlanOut,
    AssetPlanPage,
    AssetSnapshotChoicePage,
)
from app.services import repository_assets as service

router = APIRouter(tags=["repository-assets"])


@router.get("/repository-assets/snapshots", response_model=AssetSnapshotChoicePage)
def snapshot_choices(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AssetSnapshotChoicePage:
    items, next_cursor = service.list_snapshot_choices(db, context.user.id, limit, cursor)
    return AssetSnapshotChoicePage(items=items, page=PageMeta(limit=limit, next_cursor=next_cursor))


@router.get("/repository-assets/capability", response_model=AssetCapabilityOut)
def capability(context: AuthContext = Depends(current_context)) -> AssetCapabilityOut:
    return service.capability()


@router.post(
    "/repository-sources/{source_id}/asset-plans", response_model=AssetPlanOut, status_code=201
)
async def create_plan(
    source_id: uuid.UUID,
    body: AssetPlanCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> AssetPlanOut:
    return service.plan_out(db, await service.create_plan(db, context.user.id, source_id, body))


@router.get("/repository-sources/{source_id}/asset-plans", response_model=AssetPlanPage)
def plans(
    source_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AssetPlanPage:
    rows, next_cursor = service.list_plans(db, context.user.id, source_id, limit, cursor)
    return AssetPlanPage(
        items=[service.plan_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.get("/repository-asset-plans/{plan_id}", response_model=AssetPlanOut)
def get_plan(
    plan_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AssetPlanOut:
    return service.plan_out(db, service.get_plan(db, context.user.id, plan_id))


@router.get("/repository-asset-plans/{plan_id}/files", response_model=AssetPlanFilePage)
def inventory(
    plan_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AssetPlanFilePage:
    service.get_plan(db, context.user.id, plan_id)
    if cursor is not None and not re.fullmatch(r"[a-f0-9]{64}", cursor):
        raise DomainError("INVALID_CURSOR", "Inventory cursor is invalid", 422)
    query = select(RepositoryAssetPlanFile).where(
        RepositoryAssetPlanFile.plan_id == plan_id,
        RepositoryAssetPlanFile.user_id == context.user.id,
    )
    if cursor is not None:
        query = query.where(RepositoryAssetPlanFile.file_key_sha256 > cursor)
    rows = list(
        db.scalars(query.order_by(RepositoryAssetPlanFile.file_key_sha256).limit(limit + 1))
    )
    return AssetPlanFilePage(
        items=[AssetPlanFileOut.model_validate(row) for row in rows[:limit]],
        page=PageMeta(
            limit=limit, next_cursor=rows[limit - 1].file_key_sha256 if len(rows) > limit else None
        ),
    )


@router.post("/repository-asset-plans/{plan_id}/approve", response_model=AssetPlanOut)
def approve(
    plan_id: uuid.UUID,
    body: AssetPlanApprove,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> AssetPlanOut:
    return service.plan_out(db, service.approve_plan(db, context.user.id, plan_id, body))


@router.get("/repository-asset-plans/{plan_id}/jobs", response_model=AssetJobPage)
def jobs(
    plan_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AssetJobPage:
    rows, next_cursor = service.list_jobs(db, context.user.id, plan_id, limit, cursor)
    return AssetJobPage(
        items=[service.job_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.get("/repository-asset-jobs/{job_id}", response_model=AssetJobOut)
def get_job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AssetJobOut:
    return service.job_out(db, service.get_job(db, context.user.id, job_id))


@router.get("/repository-asset-jobs/{job_id}/files", response_model=AssetFilePage)
def files(
    job_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AssetFilePage:
    rows, next_cursor = service.files_out(
        db, service.get_job(db, context.user.id, job_id), limit, cursor
    )
    return AssetFilePage(items=rows, page=PageMeta(limit=limit, next_cursor=next_cursor))


@router.get("/repository-asset-jobs/{job_id}/events", response_model=list[AssetEventOut])
def events(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[AssetEventOut]:
    return service.events_out(db, service.get_job(db, context.user.id, job_id))


@router.post("/repository-asset-jobs/{job_id}/cancel", response_model=AssetJobOut)
def cancel(
    job_id: uuid.UUID, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> AssetJobOut:
    return service.job_out(db, service.cancel_job(db, context.user.id, job_id))


@router.post("/repository-asset-jobs/{job_id}/resume", response_model=AssetJobOut)
def resume(
    job_id: uuid.UUID, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> AssetJobOut:
    return service.job_out(db, service.resume_job(db, context.user.id, job_id))
