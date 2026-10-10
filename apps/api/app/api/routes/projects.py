import uuid

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.errors import DomainError
from app.models import Milestone, Paper, ProjectPaper, ResearchQuestion
from app.schemas import (
    MilestoneCreate,
    MilestoneOut,
    MilestonePatch,
    PageMeta,
    ProjectCreate,
    ProjectOut,
    ProjectPage,
    ProjectPaperSummary,
    ProjectPatch,
    QuestionCreate,
    QuestionOut,
    QuestionPatch,
)
from app.services import projects as service

router = APIRouter(prefix="/projects", tags=["projects"])
related_router = APIRouter(tags=["projects"])


@router.get("", response_model=ProjectPage)
def list_projects(
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProjectPage:
    rows, next_cursor = service.list_projects(db, context.user.id, limit, cursor, status)
    return ProjectPage(
        items=[ProjectOut.model_validate(row) for row in rows],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectOut:
    return ProjectOut.model_validate(service.create_project(db, context.user.id, body))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ProjectOut:
    return ProjectOut.model_validate(service.get_project(db, context.user.id, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def patch_project(
    project_id: uuid.UUID,
    body: ProjectPatch,
    if_match: str | None = Header(default=None),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ProjectOut:
    return ProjectOut.model_validate(
        service.update_project(db, context.user.id, project_id, body, if_match)
    )


@router.delete("/{project_id}", status_code=204)
def archive_project(
    project_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    service.archive_project(db, context.user.id, project_id)


@router.get("/{project_id}/questions", response_model=list[QuestionOut])
def list_questions(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[QuestionOut]:
    service.get_project(db, context.user.id, project_id)
    rows = db.scalars(
        select(ResearchQuestion)
        .where(ResearchQuestion.project_id == project_id)
        .order_by(ResearchQuestion.sort_order, ResearchQuestion.id)
    )
    return [QuestionOut.model_validate(row) for row in rows]


@router.post("/{project_id}/questions", response_model=QuestionOut, status_code=201)
def create_question(
    project_id: uuid.UUID,
    body: QuestionCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> QuestionOut:
    return QuestionOut.model_validate(
        service.create_question(db, context.user.id, project_id, body)
    )


@router.get("/{project_id}/milestones", response_model=list[MilestoneOut])
def list_milestones(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[MilestoneOut]:
    service.get_project(db, context.user.id, project_id)
    rows = db.scalars(
        select(Milestone)
        .where(Milestone.project_id == project_id)
        .order_by(Milestone.sort_order, Milestone.id)
    )
    return [MilestoneOut.model_validate(row) for row in rows]


@router.post("/{project_id}/milestones", response_model=MilestoneOut, status_code=201)
def create_milestone(
    project_id: uuid.UUID,
    body: MilestoneCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> MilestoneOut:
    return MilestoneOut.model_validate(
        service.create_milestone(db, context.user.id, project_id, body)
    )


class LinkPaperRequest(BaseModel):
    role: str = "related"


@router.get("/{project_id}/papers", response_model=list[ProjectPaperSummary])
def list_project_papers(
    project_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> list[ProjectPaperSummary]:
    service.get_project(db, context.user.id, project_id)
    rows = db.execute(
        select(Paper, ProjectPaper.role)
        .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
        .where(ProjectPaper.project_id == project_id, Paper.user_id == context.user.id)
        .order_by(Paper.year.desc().nullslast(), Paper.title)
    )
    return [
        ProjectPaperSummary(id=paper.id, title=paper.title, year=paper.year, role=role)
        for paper, role in rows
    ]


@router.post("/{project_id}/papers/{paper_id}", status_code=204)
def link_project_paper(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    body: LinkPaperRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    service.link_paper(db, context.user.id, project_id, paper_id, body.role)


@router.delete("/{project_id}/papers/{paper_id}", status_code=204)
def unlink_project_paper(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    role: str = "related",
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    service.get_project(db, context.user.id, project_id)
    row = db.get(ProjectPaper, (project_id, paper_id, role))
    if row:
        db.delete(row)
        db.commit()


@related_router.get("/questions/{question_id}", response_model=QuestionOut)
def get_question(
    question_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> QuestionOut:
    row = db.get(ResearchQuestion, question_id)
    if row is None:
        raise DomainError("NOT_FOUND", "Question not found", 404)
    service.get_project(db, context.user.id, row.project_id)
    return QuestionOut.model_validate(row)


@related_router.patch("/questions/{question_id}", response_model=QuestionOut)
def patch_question(
    question_id: uuid.UUID,
    body: QuestionPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> QuestionOut:
    return QuestionOut.model_validate(
        service.update_question(db, context.user.id, question_id, body)
    )


@related_router.delete("/questions/{question_id}", status_code=204)
def archive_question(
    question_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    service.update_question(db, context.user.id, question_id, QuestionPatch(status="archived"))


@related_router.patch("/milestones/{milestone_id}", response_model=MilestoneOut)
def patch_milestone(
    milestone_id: uuid.UUID,
    body: MilestonePatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> MilestoneOut:
    return MilestoneOut.model_validate(
        service.update_milestone(db, context.user.id, milestone_id, body)
    )


@related_router.delete("/milestones/{milestone_id}", status_code=204)
def cancel_milestone(
    milestone_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> None:
    service.update_milestone(db, context.user.id, milestone_id, MilestonePatch(status="cancelled"))
