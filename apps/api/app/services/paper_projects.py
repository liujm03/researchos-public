"""Owner-controlled paper project classification; never changes note content."""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import Paper, ProjectPaper, ResearchEntity, ResearchProject
from app.services.papers import get_paper


def replace_projects(
    db: Session,
    owner_id: uuid.UUID,
    paper_id: uuid.UUID,
    project_ids: list[uuid.UUID],
    expected_version: int,
) -> Paper:
    paper = get_paper(db, owner_id, paper_id)
    if not db.scalar(
        select(ResearchEntity.id).where(
            ResearchEntity.id == paper.id,
            ResearchEntity.user_id == owner_id,
            ResearchEntity.deleted_at.is_(None),
        )
    ):
        raise DomainError("NOT_FOUND", "Paper not found", 404)
    selected = set(project_ids)
    if len(project_ids) > 100:
        raise DomainError("VALIDATION_ERROR", "Select at most 100 projects", 422)
    valid = set(
        db.scalars(
            select(ResearchProject.id)
            .join(ResearchEntity, ResearchEntity.id == ResearchProject.id)
            .where(
                ResearchProject.user_id == owner_id,
                ResearchEntity.user_id == owner_id,
                ResearchEntity.deleted_at.is_(None),
                ResearchProject.id.in_(selected),
            )
        )
    )
    if valid != selected:
        raise DomainError("NOT_FOUND", "Selected project not found", 404)
    changed = db.execute(
        update(Paper)
        .where(Paper.id == paper_id, Paper.user_id == owner_id, Paper.version == expected_version)
        .values(version=Paper.version + 1, updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], changed).rowcount != 1:
        db.rollback()
        raise DomainError("CONFLICT", "Paper classification changed; reload before saving", 409)
    existing = set(
        db.scalars(select(ProjectPaper.project_id).where(ProjectPaper.paper_id == paper_id))
    )
    db.execute(
        delete(ProjectPaper).where(
            ProjectPaper.paper_id == paper_id, ProjectPaper.project_id.not_in(selected)
        )
    )
    for project_id in selected - existing:
        db.add(ProjectPaper(project_id=project_id, paper_id=paper_id, role="related"))
    db.commit()
    db.refresh(paper)
    return paper
