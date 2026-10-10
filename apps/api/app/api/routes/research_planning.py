import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas import PageMeta
from app.schemas_research_planning import (
    PlanningCapabilityOut,
    PlanningGrantApprove,
    PlanningGrantCreate,
    PlanningGrantOut,
    PlanningGrantPage,
    PlanningJobCreate,
    PlanningJobOut,
    PlanningJobPage,
)
from app.services import research_planning as service

router = APIRouter(tags=["research-planning"])


@router.get("/research-planning/capability", response_model=PlanningCapabilityOut)
def capability(context: AuthContext = Depends(current_context)) -> PlanningCapabilityOut:
    return service.capability()


@router.get("/projects/{project_id}/planning-grants", response_model=PlanningGrantPage)
def list_grants(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PlanningGrantPage:
    rows, cursor = service.list_grants(db, context.user.id, project_id, limit, cursor)
    return PlanningGrantPage(
        items=[service.grant_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=cursor),
    )


@router.post(
    "/projects/{project_id}/planning-grants", response_model=PlanningGrantOut, status_code=201
)
async def create_grant(
    project_id: uuid.UUID,
    body: PlanningGrantCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PlanningGrantOut:
    return service.grant_out(db, await service.create_grant(db, context.user.id, project_id, body))


@router.get("/projects/{project_id}/planning-grants/{grant_id}", response_model=PlanningGrantOut)
def get_grant(
    project_id: uuid.UUID,
    grant_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PlanningGrantOut:
    return service.grant_out(db, service.get_grant(db, context.user.id, project_id, grant_id))


@router.post(
    "/projects/{project_id}/planning-grants/{grant_id}/approve", response_model=PlanningGrantOut
)
def approve_grant(
    project_id: uuid.UUID,
    grant_id: uuid.UUID,
    body: PlanningGrantApprove,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PlanningGrantOut:
    return service.grant_out(
        db, service.approve_grant(db, context.user.id, project_id, grant_id, body)
    )


@router.post(
    "/projects/{project_id}/planning-grants/{grant_id}/revoke", response_model=PlanningGrantOut
)
def revoke_grant(
    project_id: uuid.UUID,
    grant_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PlanningGrantOut:
    return service.grant_out(db, service.revoke_grant(db, context.user.id, project_id, grant_id))


@router.get(
    "/projects/{project_id}/planning-grants/{grant_id}/jobs", response_model=list[PlanningJobOut]
)
def list_jobs(
    project_id: uuid.UUID,
    grant_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[PlanningJobOut]:
    return [
        service.job_out(db, row)
        for row in service.list_jobs(db, context.user.id, project_id, grant_id)
    ]


@router.post(
    "/projects/{project_id}/planning-grants/{grant_id}/jobs",
    response_model=PlanningJobOut,
    status_code=201,
)
def enqueue_job(
    project_id: uuid.UUID,
    grant_id: uuid.UUID,
    body: PlanningJobCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PlanningJobOut:
    return service.job_out(db, service.enqueue_job(db, context.user.id, project_id, grant_id, body))


@router.get("/projects/{project_id}/planning-jobs", response_model=PlanningJobPage)
def list_project_jobs(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PlanningJobPage:
    rows, cursor = service.list_project_jobs(db, context.user.id, project_id, limit, cursor)
    return PlanningJobPage(
        items=[service.job_out(db, row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=cursor),
    )


@router.get("/projects/{project_id}/planning-jobs/{job_id}", response_model=PlanningJobOut)
def get_job(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PlanningJobOut:
    return service.job_out(db, service.get_job(db, context.user.id, project_id, job_id))


@router.post("/projects/{project_id}/planning-jobs/{job_id}/cancel", response_model=PlanningJobOut)
def cancel_job(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PlanningJobOut:
    return service.job_out(db, service.cancel_job(db, context.user.id, project_id, job_id))
