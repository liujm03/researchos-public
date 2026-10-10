import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.schemas_planning_brief_proposals import (
    PlanningBriefAdoptionCreate,
    PlanningBriefAdoptionOut,
    PlanningBriefAdoptionPreviewCreate,
    PlanningBriefAdoptionPreviewOut,
    PlanningBriefProposalOut,
)
from app.services import planning_brief_proposals as service

router = APIRouter(
    prefix="/projects/{project_id}/planning-jobs/{job_id}", tags=["planning-brief-proposals"]
)


@router.get("/brief-proposal", response_model=PlanningBriefProposalOut)
def proposal(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PlanningBriefProposalOut:
    with db.no_autoflush:
        return service.proposal_out(db, context.user.id, project_id, job_id)


@router.post("/brief-adoption-preview", response_model=PlanningBriefAdoptionPreviewOut)
def preview(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    body: PlanningBriefAdoptionPreviewCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PlanningBriefAdoptionPreviewOut:
    return service.adoption_preview(db, context.user.id, project_id, job_id, body)


@router.post("/adopt-brief", response_model=PlanningBriefAdoptionOut, status_code=201)
def adopt(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    body: PlanningBriefAdoptionCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PlanningBriefAdoptionOut:
    return service.adopt_brief(db, context.user.id, project_id, job_id, body)
