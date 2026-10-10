"""One owner reviews and approves independent project initialization."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas_provisioning import (
    ProvisionCapabilityOut,
    ProvisionEventOut,
    ProvisionJobListOut,
    ProvisionJobOut,
    ProvisionObservedConfirm,
    ProvisionPlanCreate,
    ProvisionPlanOut,
    ProvisionStart,
)
from app.services import provisioning as service

router = APIRouter(tags=["project-provisioning"])


@router.get("/project-provisioning/capability", response_model=ProvisionCapabilityOut)
def get_capability(context: AuthContext = Depends(current_context)) -> ProvisionCapabilityOut:
    return service.capability()


@router.post(
    "/projects/{project_id}/provision-plans", response_model=ProvisionPlanOut, status_code=201
)
async def create_plan(
    project_id: uuid.UUID,
    body: ProvisionPlanCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProvisionPlanOut:
    return service.plan_out(await service.create_plan(db, context.user.id, project_id, body))


@router.get("/projects/{project_id}/provision-plans/{plan_id}", response_model=ProvisionPlanOut)
def get_plan(
    project_id: uuid.UUID,
    plan_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProvisionPlanOut:
    return service.plan_out(service.get_plan(db, context.user.id, project_id, plan_id))


@router.post(
    "/projects/{project_id}/provision-jobs", response_model=ProvisionJobOut, status_code=201
)
def start_job(
    project_id: uuid.UUID,
    body: ProvisionStart,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProvisionJobOut:
    return ProvisionJobOut.model_validate(service.start(db, context.user.id, project_id, body))


@router.get("/projects/{project_id}/provision-jobs", response_model=ProvisionJobListOut)
def list_jobs(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProvisionJobListOut:
    return ProvisionJobListOut(
        items=[
            ProvisionJobOut.model_validate(row)
            for row in service.list_jobs(db, context.user.id, project_id)
        ]
    )


@router.get(
    "/projects/{project_id}/provision-jobs/{job_id}/events", response_model=list[ProvisionEventOut]
)
def get_events(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ProvisionEventOut]:
    return [
        ProvisionEventOut.model_validate(row)
        for row in service.events(db, context.user.id, project_id, job_id)
    ]


@router.post(
    "/projects/{project_id}/provision-jobs/{job_id}/cancel", response_model=ProvisionJobOut
)
def cancel_job(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProvisionJobOut:
    return ProvisionJobOut.model_validate(service.cancel(db, context.user.id, project_id, job_id))


@router.post(
    "/projects/{project_id}/provision-jobs/{job_id}/reconcile", response_model=ProvisionJobOut
)
async def reconcile_job(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProvisionJobOut:
    service.quarantine(db, context.user.id)
    return ProvisionJobOut.model_validate(
        await service.reconcile(db, service.get_job(db, context.user.id, project_id, job_id))
    )


@router.post(
    "/projects/{project_id}/provision-jobs/{job_id}/confirm-observed-repository",
    response_model=ProvisionJobOut,
)
async def confirm_repository(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    body: ProvisionObservedConfirm,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProvisionJobOut:
    return ProvisionJobOut.model_validate(
        await service.confirm_observed(
            db,
            service.get_job(db, context.user.id, project_id, job_id),
            body.expected_repository_id,
        )
    )
