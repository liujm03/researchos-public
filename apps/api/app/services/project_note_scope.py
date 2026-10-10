"""Current project membership for canonical reading sources; no content or file edits."""

import uuid

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    Paper,
    PaperAnalysisJob,
    PaperResearchNote,
    ProjectPaper,
    ResearchEntity,
    ResearchProject,
)
from app.models_analytical import CanonicalAnalyticalNote, PaperReadingApprovalPlan
from app.services.note_projects import get_contexts
from app.services.note_trash import selectable_job_clause


def _job_membership(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    # One metadata query covers even malformed cross-owner/cross-paper links. A job with
    # any historical note never gets the legacy paper fallback, including all-hidden jobs.
    entity = aliased(ResearchEntity)
    paper_entity = aliased(ResearchEntity)
    rows = db.execute(
        select(
            PaperAnalysisJob.id.label("job_id"),
            PaperAnalysisJob.paper_id.label("job_paper_id"),
            PaperResearchNote.id.label("note_id"),
            PaperResearchNote.user_id.label("note_owner"),
            PaperResearchNote.paper_id.label("note_paper_id"),
            PaperResearchNote.revision,
            entity.user_id.label("entity_owner"),
            entity.deleted_at,
        )
        .join(PaperResearchNote, PaperResearchNote.analysis_job_id == PaperAnalysisJob.id)
        .join(Paper, Paper.id == PaperAnalysisJob.paper_id)
        .join(paper_entity, paper_entity.id == Paper.id)
        .outerjoin(entity, entity.id == PaperResearchNote.id)
        .where(
            PaperAnalysisJob.user_id == owner,
            Paper.user_id == owner,
            paper_entity.user_id == owner,
            paper_entity.deleted_at.is_(None),
        )
        .order_by(PaperResearchNote.revision.desc(), PaperResearchNote.id)
    ).all()
    known = list(dict.fromkeys(row.job_id for row in rows))
    selected = {}
    invalid: set[uuid.UUID] = set()
    for row in rows:
        if row.job_id in selected or row.job_id in invalid:
            continue
        if (
            row.note_owner != owner
            or row.entity_owner != owner
            or row.note_paper_id != row.job_paper_id
        ):
            invalid.add(row.job_id)
            continue
        if row.deleted_at is None:
            selected[row.job_id] = row.note_id
    contexts = get_contexts(db, owner, list(selected.values()))
    matching = [
        jid
        for jid, nid in selected.items()
        if any(project.id == project_id for project in contexts[nid].projects)
    ]
    return known, matching


def canonical_note_project_clause(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID
) -> ColumnElement[bool]:
    """Apply to a query containing Paper and CanonicalAnalyticalNote before pagination."""
    known, matching = _job_membership(db, owner, project_id)
    paper_entity = aliased(ResearchEntity)
    project_entity = aliased(ResearchEntity)
    job_identity = exists(
        select(PaperAnalysisJob.id).where(
            PaperAnalysisJob.id == CanonicalAnalyticalNote.job_id,
            PaperAnalysisJob.user_id == owner,
            PaperAnalysisJob.paper_id == Paper.id,
        )
    ).correlate(Paper, CanonicalAnalyticalNote)
    plan_identity = exists(
        select(PaperReadingApprovalPlan.id).where(
            PaperReadingApprovalPlan.id == CanonicalAnalyticalNote.plan_id,
            PaperReadingApprovalPlan.user_id == owner,
            PaperReadingApprovalPlan.paper_id == Paper.id,
        )
    ).correlate(Paper, CanonicalAnalyticalNote)
    visible_paper = exists(
        select(paper_entity.id).where(
            paper_entity.id == Paper.id,
            paper_entity.user_id == owner,
            paper_entity.deleted_at.is_(None),
        )
    ).correlate(Paper)
    visible_project = exists(
        select(ResearchProject.id)
        .join(project_entity, project_entity.id == ResearchProject.id)
        .where(
            ResearchProject.id == project_id,
            ResearchProject.user_id == owner,
            project_entity.user_id == owner,
            project_entity.deleted_at.is_(None),
        )
    )
    legacy = exists(
        select(ProjectPaper.paper_id).where(
            ProjectPaper.paper_id == Paper.id, ProjectPaper.project_id == project_id
        )
    ).correlate(Paper)
    return and_(
        CanonicalAnalyticalNote.user_id == owner,
        Paper.user_id == owner,
        job_identity,
        plan_identity,
        visible_paper,
        visible_project,
        selectable_job_clause(owner, CanonicalAnalyticalNote.job_id),
        or_(
            CanonicalAnalyticalNote.job_id.in_(matching),
            and_(CanonicalAnalyticalNote.job_id.not_in(known), legacy),
        ),
    )


def canonical_in_project(
    db: Session,
    owner: uuid.UUID,
    canonical_id: uuid.UUID,
    project_id: uuid.UUID,
    paper_id: uuid.UUID | None = None,
) -> bool:
    query = (
        select(CanonicalAnalyticalNote.id)
        .join(PaperAnalysisJob, PaperAnalysisJob.id == CanonicalAnalyticalNote.job_id)
        .join(Paper, Paper.id == PaperAnalysisJob.paper_id)
    )
    query = query.where(
        CanonicalAnalyticalNote.id == canonical_id,
        canonical_note_project_clause(db, owner, project_id),
    )
    if paper_id is not None:
        query = query.where(Paper.id == paper_id)
    return db.scalar(query) is not None
