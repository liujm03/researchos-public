import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import schemas_baseline_runs as dto
from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas import PageMeta
from app.services import baseline_runs as service

router = APIRouter(tags=["baseline-runs"])


@router.get("/baseline-runs/runtime", response_model=dto.BaselineRuntimeOut)
async def runtime(context: AuthContext = Depends(current_context)) -> dto.BaselineRuntimeOut:
    return await service.runtime()


@router.get("/baseline-versions/{version_id}/run-plans", response_model=dto.BaselineRunPlanPage)
def plans(
    version_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineRunPlanPage:
    rows, next_cursor = service.list_plans(db, context.user.id, version_id, limit, cursor)
    return dto.BaselineRunPlanPage(
        items=[service.plan_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post(
    "/baseline-versions/{version_id}/run-plans",
    response_model=dto.BaselineRunPlanOut,
    status_code=201,
)
async def create(
    version_id: uuid.UUID,
    body: dto.BaselineRunPlanCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> dto.BaselineRunPlanOut:
    return service.plan_out(db, await service.create_plan(db, context.user.id, version_id, body))


@router.get("/baseline-run-plans/{plan_id}", response_model=dto.BaselineRunPlanOut)
def plan(
    plan_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineRunPlanOut:
    return service.plan_out(db, service.get_plan(db, context.user.id, plan_id))


@router.post("/baseline-run-plans/{plan_id}/approve", response_model=dto.BaselineRunPlanOut)
async def approve(
    plan_id: uuid.UUID,
    body: dto.BaselineRunPlanApprove,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> dto.BaselineRunPlanOut:
    return service.plan_out(db, await service.approve_plan(db, context.user.id, plan_id, body))


@router.post("/baseline-run-plans/{plan_id}/revoke", response_model=dto.BaselineRunPlanOut)
def revoke(
    plan_id: uuid.UUID, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> dto.BaselineRunPlanOut:
    return service.plan_out(db, service.revoke_plan(db, context.user.id, plan_id))


@router.get("/baseline-run-plans/{plan_id}/jobs", response_model=dto.BaselineRunJobPage)
def jobs(
    plan_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineRunJobPage:
    rows, next_cursor = service.list_jobs(db, context.user.id, plan_id, limit, cursor)
    return dto.BaselineRunJobPage(
        items=[service.job_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post(
    "/baseline-run-plans/{plan_id}/jobs", response_model=dto.BaselineRunJobOut, status_code=202
)
async def enqueue(
    plan_id: uuid.UUID,
    body: dto.BaselineRunJobCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> dto.BaselineRunJobOut:
    return service.job_out(db, await service.enqueue_job(db, context.user.id, plan_id, body))


@router.get("/baseline-run-jobs/{job_id}", response_model=dto.BaselineRunJobOut)
def job(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> dto.BaselineRunJobOut:
    return service.job_out(db, service.get_job(db, context.user.id, job_id))


@router.get("/baseline-run-jobs/{job_id}/attempts", response_model=list[dto.BaselineRunAttemptOut])
def attempts(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[dto.BaselineRunAttemptOut]:
    row = service.job_out(db, service.get_job(db, context.user.id, job_id))
    return [row.attempt] if row.attempt else []


@router.get(
    "/baseline-run-jobs/{job_id}/artifacts", response_model=list[dto.BaselineRunArtifactOut]
)
def artifacts(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[dto.BaselineRunArtifactOut]:
    return service.job_out(db, service.get_job(db, context.user.id, job_id)).artifacts


@router.get("/baseline-run-jobs/{job_id}/events", response_model=list[dto.BaselineRunEventOut])
def events(
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[dto.BaselineRunEventOut]:
    return service.events_out(db, service.get_job(db, context.user.id, job_id))


@router.post("/baseline-run-jobs/{job_id}/cancel", response_model=dto.BaselineRunJobOut)
async def cancel(
    job_id: uuid.UUID, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> dto.BaselineRunJobOut:
    job = service.get_job(db, context.user.id, job_id)
    if job.status == "NEEDS_ATTENTION" and job.lease_token is None:
        from app.services.baseline_run_worker import reconcile_job

        return service.job_out(db, await reconcile_job(db, context.user.id, job_id, stop=True))
    return service.job_out(db, service.cancel_job(db, context.user.id, job_id))


@router.post("/baseline-run-jobs/{job_id}/reconcile", response_model=dto.BaselineRunJobOut)
async def reconcile(
    job_id: uuid.UUID, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> dto.BaselineRunJobOut:
    from app.services.baseline_run_worker import reconcile_job

    return service.job_out(db, await reconcile_job(db, context.user.id, job_id))
