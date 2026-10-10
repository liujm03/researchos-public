"""Owner-only research claim and source routes."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.models import Paper
from app.models_analytical import CanonicalAnalyticalNote, PaperReadingApprovalPlan
from app.models_claims import ClaimReview, ClaimRevision
from app.models_server_results import ServerResult
from app.schemas import PageMeta
from app.schemas_claims import (
    ClaimCreate,
    ClaimOut,
    ClaimPage,
    ClaimResultSourceOption,
    ClaimResultSourcePage,
    ClaimReviewOut,
    ClaimReviewRequest,
    ClaimRevise,
    ClaimRevisionOut,
    ClaimRevisionPage,
    ClaimSummary,
)
from app.schemas_paper_reproduction import ReproductionSourceContentOut, ReproductionSourcePage
from app.services import canonical_reproduction as canonical
from app.services import claims as service
from app.services import server_results as results
from app.services.common import cursor_filter, encode_cursor
from app.services.note_trash import selectable_job_clause
from app.services.project_note_scope import canonical_in_project, canonical_note_project_clause
from app.services.projects import get_project

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("/canonical-sources", response_model=ReproductionSourcePage)
def canonical_sources(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ReproductionSourcePage:
    get_project(db, context.user.id, project_id)
    q = (
        select(CanonicalAnalyticalNote, PaperReadingApprovalPlan.paper_id)
        .join(
            PaperReadingApprovalPlan,
            (CanonicalAnalyticalNote.plan_id == PaperReadingApprovalPlan.id)
            & (PaperReadingApprovalPlan.user_id == context.user.id),
        )
        .join(
            Paper,
            (Paper.id == PaperReadingApprovalPlan.paper_id) & (Paper.user_id == context.user.id),
        )
        .where(
            CanonicalAnalyticalNote.user_id == context.user.id,
            canonical_note_project_clause(db, context.user.id, project_id),
            selectable_job_clause(context.user.id, CanonicalAnalyticalNote.job_id),
            cursor_filter(CanonicalAnalyticalNote, cursor),
        )
        .order_by(CanonicalAnalyticalNote.created_at.desc(), CanonicalAnalyticalNote.id.desc())
        .limit(limit + 1)
    )
    rows = list(db.execute(q))
    return ReproductionSourcePage(
        items=[canonical._choice(db, context.user.id, p, n) for n, p in rows[:limit]],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(rows[limit - 1][0].created_at, rows[limit - 1][0].id)
            if len(rows) > limit
            else None,
        ),
    )


@router.get("/canonical-sources/{note_id}", response_model=ReproductionSourceContentOut)
def canonical_source_content(
    note_id: uuid.UUID,
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ReproductionSourceContentOut:
    get_project(db, context.user.id, project_id)
    if not canonical_in_project(db, context.user.id, note_id, project_id, paper_id):
        raise service.fail(
            "CLAIM_PAPER_NOT_LINKED",
            "Classify this reading note under the owned project first",
            404,
        )
    return canonical.source_content(db, context.user.id, paper_id, note_id)


@router.get("", response_model=ClaimPage)
def list_claims(
    project_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ClaimPage:
    rows, next_cursor = service.list_claims(db, context.user.id, project_id, limit, cursor)
    return ClaimPage(
        items=[
            ClaimSummary(
                id=r.id,
                project_id=r.project_id,
                title=r.title,
                revision=r.revision,
                created_at=r.created_at,
            )
            for r in rows
        ],
        page=PageMeta(limit=limit, next_cursor=next_cursor),
    )


@router.post("", response_model=ClaimOut, status_code=201)
def create(
    body: ClaimCreate, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> ClaimOut:
    return service.out(db, service.create(db, context.user.id, body))


@router.get("/lookup", response_model=ClaimOut)
def lookup(
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ClaimOut:
    return service.out(db, service.lookup(db, context.user.id, key))


@router.get("/result-sources", response_model=ClaimResultSourcePage)
def result_sources(
    project_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ClaimResultSourcePage:
    get_project(db, context.user.id, project_id)
    rows = list(
        db.scalars(
            select(ServerResult)
            .where(
                ServerResult.user_id == context.user.id,
                ServerResult.project_id == project_id,
                ServerResult.status == "READY",
                cursor_filter(ServerResult, cursor),
            )
            .order_by(ServerResult.created_at.desc(), ServerResult.id.desc())
            .limit(limit + 1)
        )
    )
    return ClaimResultSourcePage(
        items=[
            ClaimResultSourceOption(
                id=r.id,
                receipt_id=r.receipt_id,
                result_sha256=r.result_sha256,
                claimed_run_status=r.claimed_run_status,
                origin_verification=r.origin_verification,
                validation_status=r.validation_status,
                integrity_valid=results._intact(db, r),
            )
            for r in rows[:limit]
        ],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None,
        ),
    )


@router.get("/{identity}", response_model=ClaimOut)
def get(
    identity: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ClaimOut:
    return service.out(db, service.get(db, context.user.id, identity))


@router.patch("/{identity}", response_model=ClaimOut)
def revise(
    identity: uuid.UUID,
    body: ClaimRevise,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ClaimOut:
    return service.out(db, service.revise(db, context.user.id, identity, body))


@router.get("/{identity}/operations/lookup", response_model=ClaimOut)
def operation_lookup(
    identity: uuid.UUID,
    key: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ClaimOut:
    row = service.get(db, context.user.id, identity)
    found = db.scalar(
        select(ClaimRevision).where(
            ClaimRevision.claim_id == row.id,
            ClaimRevision.user_id == context.user.id,
            ClaimRevision.idempotency_key == key,
        )
    ) or db.scalar(
        select(ClaimReview).where(
            ClaimReview.claim_id == row.id,
            ClaimReview.user_id == context.user.id,
            ClaimReview.idempotency_key == key,
        )
    )
    if found is None:
        raise service.fail("NOT_FOUND", "Owned claim operation not found", 404)
    return service.out(db, row)


@router.get("/{identity}/revisions", response_model=ClaimRevisionPage)
def revisions(
    identity: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ClaimRevisionPage:
    row = service.get(db, context.user.id, identity)
    rows = list(
        db.scalars(
            select(ClaimRevision)
            .where(
                ClaimRevision.claim_id == row.id,
                ClaimRevision.user_id == context.user.id,
                cursor_filter(ClaimRevision, cursor),
            )
            .order_by(ClaimRevision.created_at.desc(), ClaimRevision.id.desc())
            .limit(limit + 1)
        )
    )
    return ClaimRevisionPage(
        items=[service.revision_out(db, r) for r in rows[:limit]],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None,
        ),
    )


@router.get("/{identity}/revisions/{revision_id}", response_model=ClaimRevisionOut)
def revision(
    identity: uuid.UUID,
    revision_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ClaimRevisionOut:
    return service.revision_out(
        db, service.revision(db, service.get(db, context.user.id, identity), revision_id)
    )


@router.post("/{identity}/reviews", response_model=ClaimReviewOut, status_code=201)
def review(
    identity: uuid.UUID,
    body: ClaimReviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> ClaimReviewOut:
    return ClaimReviewOut.model_validate(service.review(db, context.user.id, identity, body))
