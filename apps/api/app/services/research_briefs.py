"""Immutable owner briefs from explicit text and labeled local metadata only."""

import hashlib
import json
import uuid

from sqlalchemy import select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import Paper, ResearchProject
from app.models_ideas import ResearchBriefIdeaSource
from app.models_research_briefs import (
    ResearchBrief,
    ResearchBriefCanonicalSource,
    ResearchBriefEvidence,
    ResearchBriefReview,
    ResearchBriefSection,
)
from app.schemas_research_briefs import (
    ResearchBriefCreate,
    ResearchBriefDetailOut,
    ResearchBriefEvidenceOut,
    ResearchBriefReviewCreate,
    ResearchBriefReviewOut,
    ResearchBriefSectionOut,
)
from app.services import brief_canonical_sources as canonical
from app.services import brief_idea_sources as idea_sources_service
from app.services.common import decode_cursor, encode_cursor
from app.services.projects import get_project

KEYS = (
    "intent",
    "related_work",
    "hypotheses",
    "resources",
    "routes",
    "protocol",
    "stage_plan",
    "decision",
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def _paper_values(paper: Paper | ResearchBriefEvidence) -> dict[str, object]:
    return {
        "paper_id": str(paper.id if isinstance(paper, Paper) else paper.paper_id),
        "title": paper.title,
        "abstract": paper.abstract,
        "year": paper.year,
        "doi": paper.doi,
        "paper_version": paper.version if isinstance(paper, Paper) else paper.paper_version,
    }


def get_brief(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID
) -> ResearchBrief:
    get_project(db, owner, project)
    row = db.scalar(
        select(ResearchBrief).where(
            ResearchBrief.id == identity,
            ResearchBrief.user_id == owner,
            ResearchBrief.project_id == project,
        )
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned research brief not found", 404)
    return row


def _sections(db: Session, row: ResearchBrief) -> list[ResearchBriefSection]:
    found = list(
        db.scalars(
            select(ResearchBriefSection).where(
                ResearchBriefSection.brief_id == row.id,
                ResearchBriefSection.project_id == row.project_id,
                ResearchBriefSection.user_id == row.user_id,
            )
        )
    )
    return sorted(found, key=lambda item: KEYS.index(item.key))


def _evidence(db: Session, row: ResearchBrief) -> list[ResearchBriefEvidence]:
    return list(
        db.scalars(
            select(ResearchBriefEvidence)
            .where(
                ResearchBriefEvidence.brief_id == row.id,
                ResearchBriefEvidence.project_id == row.project_id,
                ResearchBriefEvidence.user_id == row.user_id,
            )
            .order_by(ResearchBriefEvidence.paper_id)
        )
    )


def brief_hash(
    row: ResearchBrief,
    sections: list[ResearchBriefSection],
    evidence: list[ResearchBriefEvidence],
    canonical_sources: list[ResearchBriefCanonicalSource] | None = None,
    idea_sources: list[ResearchBriefIdeaSource] | None = None,
) -> str:
    payload = {
        "id": str(row.id),
        "owner": str(row.user_id),
        "project": str(row.project_id),
        "revision": row.revision,
        "project_version": row.project_version,
        "base_brief_id": str(row.base_brief_id) if row.base_brief_id else None,
        "idea": row.idea,
        "stop_rules": row.stop_rules,
        "sections": [
            {
                "key": item.key,
                "content": item.content,
                "origin_type": item.origin_type,
                "uncertainty": item.uncertainty,
                **(
                    {
                        "source_planning_job_id": str(item.source_planning_job_id),
                        "source_result_sha256": item.source_result_sha256,
                    }
                    if item.source_planning_job_id is not None
                    else {}
                ),
            }
            for item in sorted(sections, key=lambda item: KEYS.index(item.key))
        ],
        "evidence": [
            {**_paper_values(item), "sha256": item.sha256}
            for item in sorted(evidence, key=lambda item: str(item.paper_id))
        ],
    }
    if row.stop_rules_origin is not None:
        payload["stop_rules_origin"] = row.stop_rules_origin
    if row.stop_source_planning_job_id is not None:
        payload.update(
            stop_source_planning_job_id=str(row.stop_source_planning_job_id),
            stop_source_result_sha256=row.stop_source_result_sha256,
        )
    if canonical_sources:
        payload["canonical_note_sources"] = [
            canonical.values(item)
            for item in sorted(canonical_sources, key=lambda item: str(item.canonical_note_id))
        ]
    if idea_sources:
        payload["idea_sources"] = [
            idea_sources_service.values(x)
            for x in sorted(idea_sources, key=lambda x: str(x.idea_id))
        ]
    return digest(payload)


def _intact(db: Session, row: ResearchBrief) -> bool:
    sections, evidence = _sections(db, row), _evidence(db, row)
    return (
        len(sections) == 8
        and {item.key for item in sections} == set(KEYS)
        and all(digest(_paper_values(item)) == item.sha256 for item in evidence)
        and all(canonical.intact(item) for item in canonical.rows(db, row))
        and all(idea_sources_service.intact(x) for x in idea_sources_service.rows(db, row))
        and brief_hash(
            row, sections, evidence, canonical.rows(db, row), idea_sources_service.rows(db, row)
        )
        == row.sha256
    )


def context_current(db: Session, row: ResearchBrief, *, lock: bool = False) -> bool:
    query = select(ResearchProject).where(
        ResearchProject.id == row.project_id, ResearchProject.user_id == row.user_id
    )
    project = db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )
    if project is None or project.version != row.project_version:
        return False
    for evidence in _evidence(db, row):
        query_paper = select(Paper).where(
            Paper.id == evidence.paper_id, Paper.user_id == row.user_id
        )
        paper = db.scalar(
            (query_paper.with_for_update() if lock else query_paper).execution_options(
                populate_existing=True
            )
        )
        if paper is None or digest(_paper_values(paper)) != evidence.sha256:
            return False
    return all(canonical.current(db, item) for item in canonical.rows(db, row)) and all(
        idea_sources_service.current(db, x) for x in idea_sources_service.rows(db, row)
    )


def detail_out(db: Session, row: ResearchBrief) -> ResearchBriefDetailOut:
    sections, evidence = _sections(db, row), _evidence(db, row)
    review = db.scalar(
        select(ResearchBriefReview).where(
            ResearchBriefReview.brief_id == row.id,
            ResearchBriefReview.user_id == row.user_id,
            ResearchBriefReview.project_id == row.project_id,
        )
    )
    current = context_current(db, row)
    gaps = ["PAPER_METADATA_IS_NOT_FULLTEXT_EVIDENCE", "NO_STAGE_GRANT_OR_EXECUTION_AUTHORITY"]
    gaps.extend("MISSING_" + item.key.upper() for item in sections if not item.content)
    if not row.stop_rules:
        gaps.append("STOP_RULES_NOT_DEFINED")
    if not current:
        gaps.append("SOURCE_CONTEXT_CHANGED")
    intact = _intact(db, row)
    if not intact:
        gaps.append("BRIEF_HASH_INVALID")
    review_valid = (
        intact
        and review is not None
        and review.sha256 == row.sha256
        and review.reviewer_id == row.user_id
    )
    if review is not None and not review_valid:
        gaps.append("REVIEW_HASH_INVALID")
    if any(item.origin_type == "PROJECT_CONTEXT" for item in sections):
        gaps.append("PROJECT_CONTEXT_CANDIDATES_NOT_INDEPENDENTLY_VERIFIED")
    return ResearchBriefDetailOut(
        id=row.id,
        user_id=row.user_id,
        project_id=row.project_id,
        revision=row.revision,
        project_version=row.project_version,
        base_brief_id=row.base_brief_id,
        idea=row.idea,
        stop_rules=row.stop_rules,
        stop_rules_origin=row.stop_rules_origin,
        stop_source_planning_job_id=row.stop_source_planning_job_id,
        stop_source_result_sha256=row.stop_source_result_sha256,
        sha256=row.sha256,
        created_at=row.created_at,
        status="DRAFT"
        if review is None or not review_valid
        else "ACCEPTED"
        if review.decision == "ACCEPT"
        else "REJECTED",
        sections=[ResearchBriefSectionOut.model_validate(item) for item in sections],
        evidence=[ResearchBriefEvidenceOut.model_validate(item) for item in evidence],
        canonical_note_sources=[canonical.out(db, item) for item in canonical.rows(db, row)],
        idea_sources=[
            {
                **idea_sources_service.values(x),
                "context_current": idea_sources_service.current(db, x),
            }
            for x in idea_sources_service.rows(db, row)
        ],
        review=ResearchBriefReviewOut.model_validate(review) if review else None,
        context_current=current,
        gaps=gaps,
    )


def create_brief(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    body: ResearchBriefCreate,
    *,
    commit: bool = True,
    derived_sections: dict[str, tuple[uuid.UUID, str, str | None]] | None = None,
    derived_stop: tuple[uuid.UUID, str] | None = None,
    idea_sources: list[ResearchBriefIdeaSource] | None = None,
) -> ResearchBrief:
    get_project(db, owner, project_id)
    project = db.scalar(
        select(ResearchProject)
        .where(ResearchProject.id == project_id, ResearchProject.user_id == owner)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert project is not None
    latest = db.scalar(
        select(ResearchBrief)
        .where(ResearchBrief.project_id == project_id, ResearchBrief.user_id == owner)
        .order_by(ResearchBrief.revision.desc())
        .limit(1)
    )
    if latest is None:
        if body.base_brief_id is not None:
            raise DomainError("BRIEF_BASE_CHANGED", "First revision has no base", 409)
    elif (
        latest.id != body.base_brief_id
        or latest.sha256 != body.expected_base_sha256
        or not _intact(db, latest)
    ):
        raise DomainError(
            "BRIEF_BASE_CHANGED",
            "Use the latest intact brief identity and hash to create a revision",
            409,
        )
    row = ResearchBrief(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project_id,
        revision=latest.revision + 1 if latest else 1,
        project_version=project.version,
        base_brief_id=latest.id if latest else None,
        idea=body.idea.strip(),
        stop_rules=body.stop_rules
        if "stop_rules" in body.model_fields_set or latest is None
        else latest.stop_rules,
        sha256="0" * 64,
    )
    if latest is not None:
        row.stop_rules_origin = latest.stop_rules_origin
        row.stop_source_planning_job_id = latest.stop_source_planning_job_id
        row.stop_source_result_sha256 = latest.stop_source_result_sha256
        if "stop_rules" in body.model_fields_set and body.stop_rules != latest.stop_rules:
            row.stop_rules_origin = "OWNER_INPUT" if latest.stop_source_planning_job_id else None
    if derived_stop is not None:
        row.stop_rules_origin = "AI_INFERRED"
        row.stop_source_planning_job_id, row.stop_source_result_sha256 = derived_stop
    prior = {item.key: item for item in _sections(db, latest)} if latest else {}
    supplied = {item.key: item.content for item in body.sections}
    context = {
        "intent": project.problem,
        "related_work": project.research_gap,
        "routes": project.method_overview,
    }
    sections = []
    for key in KEYS:
        if key in supplied:
            content, origin, uncertainty = supplied[key], "OWNER_INPUT", None
            if (
                key in prior
                and content == prior[key].content
                and prior[key].origin_type == "AI_INFERRED"
            ):
                origin, uncertainty = prior[key].origin_type, prior[key].uncertainty
        elif key in prior:
            old = prior[key]
            content, origin, uncertainty = old.content, old.origin_type, old.uncertainty
        else:
            content = context.get(key)
            origin = "PROJECT_CONTEXT" if content else "MISSING"
            uncertainty = (
                "Existing project text is a candidate context; no literature search, novelty check or experiment was performed."
                if content
                else "No information supplied; no search, AI call or experiment performed."
            )
        sections.append(
            ResearchBriefSection(
                brief_id=row.id,
                project_id=project_id,
                user_id=owner,
                key=key,
                content=content,
                origin_type=origin,
                uncertainty=uncertainty,
                source_planning_job_id=prior[key].source_planning_job_id if key in prior else None,
                source_result_sha256=prior[key].source_result_sha256 if key in prior else None,
            )
        )
        if derived_sections and key in derived_sections:
            source_job, source_hash, source_uncertainty = derived_sections[key]
            sections[-1].origin_type = "AI_INFERRED"
            sections[-1].source_planning_job_id = source_job
            sections[-1].source_result_sha256 = source_hash
            sections[-1].uncertainty = (
                source_uncertainty
                or "AI planning candidate; no author fact or experimental verification is established."
            )
    evidence_rows = []
    if latest is not None and "evidence_paper_ids" not in body.model_fields_set:
        selected = [_paper_values(item) for item in _evidence(db, latest)]
    else:
        selected = []
        for identity in body.evidence_paper_ids:
            paper = db.scalar(
                select(Paper)
                .where(Paper.id == identity, Paper.user_id == owner)
                .execution_options(populate_existing=True)
            )
            if paper is None:
                raise DomainError("NOT_FOUND", "Owned metadata evidence paper not found", 404)
            selected.append(_paper_values(paper))
    for values in selected:
        evidence_rows.append(
            ResearchBriefEvidence(
                id=uuid.uuid4(),
                brief_id=row.id,
                project_id=project_id,
                user_id=owner,
                **{**values, "paper_id": uuid.UUID(str(values["paper_id"]))},
                sha256=digest(values),
            )
        )
    if latest is not None and "canonical_note_sources" not in body.model_fields_set:
        canonical_rows = [
            ResearchBriefCanonicalSource(
                brief_id=row.id, project_id=project_id, user_id=owner, **canonical.values(item)
            )
            for item in canonical.rows(db, latest)
        ]
    else:
        canonical_rows = canonical.freeze(db, row, body.canonical_note_sources)
    if idea_sources is None:
        idea_sources = (
            [
                ResearchBriefIdeaSource(
                    brief_id=row.id,
                    project_id=project_id,
                    user_id=owner,
                    **idea_sources_service.values(x),
                )
                for x in idea_sources_service.rows(db, latest)
            ]
            if latest
            else []
        )
    elif latest:
        selected_ids = {x.idea_id for x in idea_sources}
        idea_sources = [
            ResearchBriefIdeaSource(
                brief_id=row.id,
                project_id=project_id,
                user_id=owner,
                **idea_sources_service.values(x),
            )
            for x in idea_sources_service.rows(db, latest)
            if x.idea_id not in selected_ids
        ] + idea_sources
    for selected_idea in idea_sources:
        selected_idea.brief_id = row.id
    if idea_sources:
        for item in sections:
            if item.key == "related_work" and item.key in supplied:
                item.uncertainty = "Owner selected AI-derived canonical note excerpts; these quotations are not independently verified author facts or scientific conclusions."
    row.sha256 = brief_hash(row, sections, evidence_rows, canonical_rows, idea_sources)
    try:
        db.add(row)
        db.flush()
        db.add_all([*sections, *evidence_rows, *canonical_rows, *idea_sources])
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "BRIEF_REVISION_CONFLICT",
            "Another revision was committed; reload the latest brief",
            409,
        ) from None
    db.refresh(row)
    return row


def review_brief(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    identity: uuid.UUID,
    body: ResearchBriefReviewCreate,
) -> ResearchBrief:
    row = get_brief(db, owner, project, identity)
    db.scalar(
        select(ResearchProject.id)
        .where(ResearchProject.id == project, ResearchProject.user_id == owner)
        .with_for_update()
    )
    if row.sha256 != body.expected_sha256 or not _intact(db, row):
        raise DomainError(
            "BRIEF_HASH_CHANGED", "Exact brief hash no longer matches the reviewed content", 409
        )
    existing = db.scalar(
        select(ResearchBriefReview).where(
            ResearchBriefReview.brief_id == row.id, ResearchBriefReview.user_id == owner
        )
    )
    if existing:
        if existing.decision == body.decision and existing.sha256 == row.sha256:
            return row
        raise DomainError(
            "BRIEF_REVIEW_CONFLICT", "This exact brief already has a different review decision", 409
        )
    if not context_current(db, row, lock=True):
        raise DomainError(
            "BRIEF_CONTEXT_CHANGED",
            "Project or metadata source changed; create and review a refreshed revision",
            409,
        )
    db.add(
        ResearchBriefReview(
            brief_id=row.id,
            project_id=project,
            user_id=owner,
            reviewer_id=owner,
            sha256=row.sha256,
            decision=body.decision,
            comment=body.comment,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "BRIEF_REVIEW_CONFLICT", "Another review was committed; reload the exact revision", 409
        ) from None
    return row


def list_briefs(
    db: Session, owner: uuid.UUID, project: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[ResearchBrief], str | None]:
    get_project(db, owner, project)
    boundary = None
    if cursor is not None:
        _, identity = decode_cursor(cursor)
        boundary = get_brief(db, owner, project, identity).revision
    rows = list(
        db.scalars(
            select(ResearchBrief)
            .where(
                ResearchBrief.user_id == owner,
                ResearchBrief.project_id == project,
                ResearchBrief.revision < boundary if boundary is not None else true(),
            )
            .order_by(ResearchBrief.revision.desc())
            .limit(limit + 1)
        )
    )
    next_cursor = (
        encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    )
    return rows[:limit], next_cursor
