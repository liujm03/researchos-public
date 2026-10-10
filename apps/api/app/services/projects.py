import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import Milestone, Paper, ProjectPaper, ResearchProject, ResearchQuestion
from app.schemas import (
    MilestoneCreate,
    MilestonePatch,
    ProjectCreate,
    ProjectPatch,
    QuestionCreate,
    QuestionPatch,
)
from app.services.common import assert_version, cursor_filter, encode_cursor, register_entity


def get_project(db: Session, user_id: uuid.UUID, project_id: uuid.UUID) -> ResearchProject:
    project = db.scalar(
        select(ResearchProject).where(
            ResearchProject.id == project_id, ResearchProject.user_id == user_id
        )
    )
    if project is None:
        raise DomainError("NOT_FOUND", "Project not found", 404)
    return project


def _slug(name: str, item_id: uuid.UUID) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "project"
    return f"{stem}-{item_id.hex[:8]}"


def create_project(db: Session, user_id: uuid.UUID, data: ProjectCreate) -> ResearchProject:
    if data.parent_project_id is not None:
        get_project(db, user_id, data.parent_project_id)
    item_id = register_entity(db, user_id, "project")
    project = ResearchProject(
        id=item_id,
        user_id=user_id,
        slug=_slug(data.name, item_id),
        **data.model_dump(),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(
    db: Session,
    user_id: uuid.UUID,
    limit: int,
    cursor: str | None,
    status: str | None,
) -> tuple[list[ResearchProject], str | None]:
    query = select(ResearchProject).where(
        ResearchProject.user_id == user_id, cursor_filter(ResearchProject, cursor)
    )
    if status:
        query = query.where(ResearchProject.status == status)
    rows = list(
        db.scalars(
            query.order_by(ResearchProject.created_at.desc(), ResearchProject.id.desc()).limit(
                limit + 1
            )
        )
    )
    next_cursor = (
        encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    )
    return rows[:limit], next_cursor


def update_project(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    data: ProjectPatch,
    if_match: str | None,
) -> ResearchProject:
    project = get_project(db, user_id, project_id)
    assert_version(project.version, if_match)
    changes = data.model_dump(exclude_unset=True)
    for required in ("name", "status", "pipeline_stage"):
        if required in changes and changes[required] is None:
            raise DomainError("VALIDATION_ERROR", f"{required} cannot be null", 422)
    if "parent_project_id" in changes and changes["parent_project_id"] is not None:
        current: ResearchProject | None = get_project(db, user_id, changes["parent_project_id"])
        seen = {project_id}
        while current is not None:
            if current.id in seen:
                raise DomainError("VALIDATION_ERROR", "Project tree cannot contain a cycle", 422)
            seen.add(current.id)
            current = (
                get_project(db, user_id, current.parent_project_id)
                if current.parent_project_id
                else None
            )
    for key, value in changes.items():
        setattr(project, key, value)
    project.version += 1
    project.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(project)
    return project


def archive_project(db: Session, user_id: uuid.UUID, project_id: uuid.UUID) -> None:
    project = get_project(db, user_id, project_id)
    project.status = "archived"
    project.version += 1
    db.commit()


def create_question(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID, data: QuestionCreate
) -> ResearchQuestion:
    get_project(db, user_id, project_id)
    if data.parent_question_id:
        parent = db.get(ResearchQuestion, data.parent_question_id)
        if parent is None or parent.project_id != project_id:
            raise DomainError("VALIDATION_ERROR", "Parent question must be in this project", 422)
    item_id = register_entity(db, user_id, "question")
    question = ResearchQuestion(id=item_id, project_id=project_id, **data.model_dump())
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def create_milestone(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID, data: MilestoneCreate
) -> Milestone:
    get_project(db, user_id, project_id)
    item_id = register_entity(db, user_id, "milestone")
    milestone = Milestone(id=item_id, project_id=project_id, **data.model_dump())
    db.add(milestone)
    db.commit()
    db.refresh(milestone)
    return milestone


def update_question(
    db: Session, user_id: uuid.UUID, question_id: uuid.UUID, data: QuestionPatch
) -> ResearchQuestion:
    question = db.get(ResearchQuestion, question_id)
    if question is None:
        raise DomainError("NOT_FOUND", "Question not found", 404)
    get_project(db, user_id, question.project_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("question", "valid") is None:
        raise DomainError("VALIDATION_ERROR", "question cannot be null", 422)
    for key, value in changes.items():
        setattr(question, key, value)
    db.commit()
    db.refresh(question)
    return question


def update_milestone(
    db: Session, user_id: uuid.UUID, milestone_id: uuid.UUID, data: MilestonePatch
) -> Milestone:
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise DomainError("NOT_FOUND", "Milestone not found", 404)
    get_project(db, user_id, milestone.project_id)
    changes = data.model_dump(exclude_unset=True)
    if any(changes.get(name, "valid") is None for name in ("title", "status", "sort_order")):
        raise DomainError("VALIDATION_ERROR", "Required milestone fields cannot be null", 422)
    if changes.get("status") == "completed" and milestone.status != "completed":
        changes["completed_at"] = datetime.now(UTC)
    elif "status" in changes and changes["status"] != "completed":
        changes["completed_at"] = None
    for key, value in changes.items():
        setattr(milestone, key, value)
    db.commit()
    db.refresh(milestone)
    return milestone


def link_paper(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID, paper_id: uuid.UUID, role: str
) -> None:
    get_project(db, user_id, project_id)
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.user_id == user_id))
    if paper is None:
        raise DomainError("NOT_FOUND", "Paper not found", 404)
    if db.get(ProjectPaper, (project_id, paper_id, role)) is None:
        db.add(ProjectPaper(project_id=project_id, paper_id=paper_id, role=role))
        db.commit()
