import re
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.models_project_sources import ProjectSourcePlan, ProjectSourcePlanFile
from app.schemas import PageMeta
from app.schemas_project_sources import (
    ProjectPathBindingOut,
    ProjectSourceCapabilityOut,
    ProjectSourceEventOut,
    ProjectSourceFilePage,
    ProjectSourceJobOut,
    ProjectSourceJobPage,
    ProjectSourcePlanApprove,
    ProjectSourcePlanCreate,
    ProjectSourcePlanFileOut,
    ProjectSourcePlanFilePage,
    ProjectSourcePlanOut,
    ProjectSourcePlanPage,
    ProjectSourceVerifyOut,
)
from app.services import project_sources as service

router = APIRouter(tags=["project-sources"])


def owned_plan(db: Session, owner: uuid.UUID, plan_id: uuid.UUID) -> ProjectSourcePlan:
    row = db.scalar(
        select(ProjectSourcePlan).where(
            ProjectSourcePlan.id == plan_id, ProjectSourcePlan.user_id == owner
        )
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned source placement plan not found", 404)
    return service.get_plan(db, owner, row.project_id, plan_id)


@router.get("/project-sources/capability", response_model=ProjectSourceCapabilityOut)
def capability(context: AuthContext = Depends(current_context)) -> ProjectSourceCapabilityOut:
    return service.capability()


@router.post(
    "/projects/{project_id}/source-plans", response_model=ProjectSourcePlanOut, status_code=201
)
async def create_plan(
    project_id: uuid.UUID,
    body: ProjectSourcePlanCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectSourcePlanOut:
    return service.plan_out(db, await service.create_plan(db, context.user.id, project_id, body))


@router.get("/projects/{project_id}/source-plans", response_model=ProjectSourcePlanPage)
def plans(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProjectSourcePlanPage:
    rows, next_cursor = service.list_plans(db, context.user.id, project_id, limit, cursor)
    return ProjectSourcePlanPage(
        items=[service.plan_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.get("/project-source-plans/{plan_id}", response_model=ProjectSourcePlanOut)
def plan_detail(
    plan_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProjectSourcePlanOut:
    return service.plan_out(db, owned_plan(db, context.user.id, plan_id))


@router.get("/project-source-plans/{plan_id}/files", response_model=ProjectSourcePlanFilePage)
def inventory(
    plan_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProjectSourcePlanFilePage:
    plan = owned_plan(db, context.user.id, plan_id)
    if cursor is not None and not re.fullmatch(r"[a-f0-9]{64}", cursor):
        raise DomainError("INVALID_CURSOR", "Source file cursor is invalid", 422)
    query = select(ProjectSourcePlanFile).where(
        ProjectSourcePlanFile.plan_id == plan.id,
        ProjectSourcePlanFile.user_id == context.user.id,
        ProjectSourcePlanFile.project_id == plan.project_id,
    )
    if cursor is not None:
        query = query.where(ProjectSourcePlanFile.file_key_sha256 > cursor)
    rows = list(db.scalars(query.order_by(ProjectSourcePlanFile.file_key_sha256).limit(limit + 1)))
    return ProjectSourcePlanFilePage(
        items=[ProjectSourcePlanFileOut.model_validate(row) for row in rows[:limit]],
        page=PageMeta(
            limit=limit, next_cursor=rows[limit - 1].file_key_sha256 if len(rows) > limit else None
        ),
    )


@router.post("/project-source-plans/{plan_id}/approve", response_model=ProjectSourcePlanOut)
async def approve(
    plan_id: uuid.UUID,
    body: ProjectSourcePlanApprove,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectSourcePlanOut:
    plan = owned_plan(db, context.user.id, plan_id)
    return service.plan_out(
        db, await service.approve_plan(db, context.user.id, plan.project_id, plan_id, body)
    )


@router.get("/project-source-plans/{plan_id}/jobs", response_model=ProjectSourceJobPage)
def jobs(
    plan_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProjectSourceJobPage:
    plan = owned_plan(db, context.user.id, plan_id)
    rows, next_cursor = service.list_jobs(
        db, context.user.id, plan.project_id, plan_id, limit, cursor
    )
    return ProjectSourceJobPage(
        items=[service.job_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.get("/projects/{project_id}/source-jobs/{job_id}", response_model=ProjectSourceJobOut)
def job_detail(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProjectSourceJobOut:
    return service.job_out(db, service.get_job(db, context.user.id, project_id, job_id))


@router.get(
    "/projects/{project_id}/source-jobs/{job_id}/files", response_model=ProjectSourceFilePage
)
def files(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProjectSourceFilePage:
    rows, next_cursor = service.files_out(
        db, service.get_job(db, context.user.id, project_id, job_id), limit, cursor
    )
    return ProjectSourceFilePage(items=rows, page=PageMeta(limit=limit, next_cursor=next_cursor))


@router.get(
    "/projects/{project_id}/source-jobs/{job_id}/events", response_model=list[ProjectSourceEventOut]
)
def events(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ProjectSourceEventOut]:
    return service.events_out(db, service.get_job(db, context.user.id, project_id, job_id))


@router.post(
    "/projects/{project_id}/source-jobs/{job_id}/cancel", response_model=ProjectSourceJobOut
)
def cancel(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectSourceJobOut:
    return service.job_out(db, service.cancel_job(db, context.user.id, project_id, job_id))


@router.post(
    "/projects/{project_id}/source-jobs/{job_id}/resume", response_model=ProjectSourceJobOut
)
def resume(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectSourceJobOut:
    return service.job_out(db, service.resume_job(db, context.user.id, project_id, job_id))


@router.post(
    "/projects/{project_id}/source-jobs/{job_id}/verify", response_model=ProjectSourceVerifyOut
)
async def verify(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectSourceVerifyOut:
    return await service.verify_job(db, context.user.id, project_id, job_id)


@router.post(
    "/projects/{project_id}/source-jobs/{job_id}/reconcile", response_model=ProjectSourceJobOut
)
def reconcile(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectSourceJobOut:
    return service.job_out(db, service.reconcile_job(db, context.user.id, project_id, job_id))


@router.post(
    "/projects/{project_id}/path-bindings/{binding_id}/revoke", response_model=ProjectPathBindingOut
)
def revoke(
    project_id: uuid.UUID,
    binding_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectPathBindingOut:
    return ProjectPathBindingOut.model_validate(
        service.revoke_binding(db, context.user.id, project_id, binding_id)
    )
