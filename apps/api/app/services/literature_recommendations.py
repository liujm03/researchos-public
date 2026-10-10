"""Explicit metadata search; ordinary reads never invoke external providers."""

import asyncio
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.literature import (
    LiteratureSearchPage,
    LiteratureSearchQuery,
    PaperCandidate,
    SearchLiteratureProvider,
)
from app.domain.literature_identity import normalize_doi, validate_doi_name
from app.domain.literature_recommendations import (
    COVERAGE_NOTE,
    VENUES,
    classify_venue,
    literal_matches,
    sha256,
)
from app.errors import DomainError
from app.models import Paper, PaperSource, ProjectPaper, ResearchQuestion, User
from app.models_literature_recommendations import LiteratureRecommendationAuthor as Author
from app.models_literature_recommendations import LiteratureRecommendationBatch as Batch
from app.models_literature_recommendations import LiteratureRecommendationCandidate as Candidate
from app.models_literature_recommendations import LiteratureRecommendationTerm as Term
from app.models_literature_recommendations import LiteratureRecommendationVenue as Venue
from app.providers import registry
from app.schemas import PageMeta, PaperCreate
from app.schemas_literature_recommendations import (
    LiteratureCandidateAdoptOut,
    LiteratureCandidateAdoptRequest,
    LiteratureCandidateOut,
    LiteratureQuestionOption,
    LiteratureRecommendationOptions,
    LiteratureResearchLink,
    LiteratureResearchLinkGroup,
    LiteratureResearchLinks,
    LiteratureSearchBatchOut,
    LiteratureSearchBatchPage,
    LiteratureSearchBatchSummary,
    LiteratureSearchNextRequest,
    LiteratureSearchPreviewOut,
    LiteratureSearchSelection,
    LiteratureSearchStartRequest,
    LiteratureSearchTransmission,
    LiteratureVenueOption,
)
from app.services.common import cursor_filter, encode_cursor
from app.services.papers import create_paper
from app.services.projects import get_project


def _lock(db: Session, owner: uuid.UUID) -> None:
    if db.scalar(select(User.id).where(User.id == owner).with_for_update()) is None:
        raise DomainError("NOT_FOUND", "Owner not found", 404)


def recommendation_year_range() -> tuple[int, int]:
    """The owner wants the current and preceding publication years, never all-time."""
    year = datetime.now(ZoneInfo(get_settings().app_timezone)).year
    return year - 1, year


def recent_selection(selection: LiteratureSearchSelection) -> LiteratureSearchSelection:
    lower, upper = recommendation_year_range()
    start = lower if selection.from_year is None else selection.from_year
    end = upper if selection.until_year is None else selection.until_year
    if not lower <= start <= end <= upper:
        raise DomainError(
            "RECENT_LITERATURE_ONLY",
            f"文献推荐仅检索最近两个发表年度（{lower}–{upper}）；请重新预览年份范围。",
            422,
        )
    return selection.model_copy(update={"from_year": start, "until_year": end})


def discovery_links(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    query: str | None = None,
    question_id: uuid.UUID | None = None,
) -> LiteratureResearchLinks:
    row = get_project(db, owner, project)
    questions = list(
        db.scalars(
            select(ResearchQuestion)
            .where(
                ResearchQuestion.project_id == project,
            )
            .order_by(ResearchQuestion.sort_order, ResearchQuestion.id)
        )
    )
    selected_question = None
    if question_id is not None:
        selected_question = next((q for q in questions if q.id == question_id), None)
        if selected_question is None:
            raise DomainError("NOT_FOUND", "Research question not found in this project", 404)
    keyword = (
        query
        if query is not None
        else (selected_question.question if selected_question else row.name)
    )
    keyword = " ".join(keyword.split())
    if not keyword or len(keyword) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in keyword):
        raise DomainError("VALIDATION_ERROR", "检索关键词需要1至500个字符。", 422)
    lower, upper = recommendation_year_range()
    groups = registry.literature_discovery_links_provider().links(keyword, lower, upper)
    return LiteratureResearchLinks(
        project_id=project,
        project_name=row.name,
        query=keyword,
        recent_from_year=lower,
        recent_until_year=upper,
        questions=[LiteratureQuestionOption(id=q.id, question=q.question) for q in questions],
        groups=[
            LiteratureResearchLinkGroup(
                key=g.key,
                label=g.label,
                items=[
                    LiteratureResearchLink(
                        key=v.key,
                        label=v.label,
                        publisher=v.publisher,
                        homepage_url=v.homepage_url,
                        search_url=v.search_url,
                        search_note=v.search_note,
                    )
                    for v in g.items
                ],
            )
            for g in groups
        ],
    )


def options(db: Session, owner: uuid.UUID, project: uuid.UUID) -> LiteratureRecommendationOptions:
    row = get_project(db, owner, project)
    lower_year, upper_year = recommendation_year_range()
    questions = db.scalars(
        select(ResearchQuestion)
        .where(ResearchQuestion.project_id == project)
        .order_by(ResearchQuestion.sort_order, ResearchQuestion.id)
    )
    return LiteratureRecommendationOptions(
        owner_id=owner,
        project_id=project,
        project_name=row.name,
        project_version=row.version,
        recent_from_year=lower_year,
        recent_until_year=upper_year,
        questions=[LiteratureQuestionOption(id=q.id, question=q.question) for q in questions],
        venues=[LiteratureVenueOption(key=k, label=v[-1]) for k, v in VENUES.items()],
        provider_key="crossref",
        coverage_note=COVERAGE_NOTE,
    )


def preview(
    db: Session, owner: uuid.UUID, project: uuid.UUID, selection: LiteratureSearchSelection
) -> LiteratureSearchPreviewOut:
    row = get_project(db, owner, project)
    selection = recent_selection(selection)
    if selection.provider_key not in registry.literature_search_provider_keys():
        raise DomainError(
            "PROVIDER_NOT_SUPPORTED",
            "No registered metadata search provider supports this selection",
            422,
        )
    question_text = None
    if selection.question_id:
        question = db.scalar(
            select(ResearchQuestion).where(
                ResearchQuestion.id == selection.question_id, ResearchQuestion.project_id == project
            )
        )
        if question is None:
            raise DomainError("NOT_FOUND", "Research question not found in this project", 404)
        question_text = question.question
    if any(key not in VENUES for key in selection.venue_keys):
        raise DomainError("VALIDATION_ERROR", "Unknown venue selection", 422)
    context = sha256(
        {
            "contract": "project-literature-v1",
            "owner": str(owner),
            "project": str(project),
            "project_version": row.version,
            "project_name": row.name,
            "question": question_text,
            "selection": selection.model_dump(mode="json"),
        }
    )
    return LiteratureSearchPreviewOut(
        project_id=project,
        project_name=row.name,
        question=question_text,
        selection=selection,
        context_sha256=context,
        transmission=LiteratureSearchTransmission(
            query=selection.query,
            from_year=selection.from_year,
            until_year=selection.until_year,
            page_size=selection.page_size,
        ),
        coverage_note=COVERAGE_NOTE,
    )


def get_batch(db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID) -> Batch:
    get_project(db, owner, project)
    row = db.scalar(
        select(Batch)
        .where(Batch.id == identity, Batch.user_id == owner, Batch.project_id == project)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Metadata search batch not found", 404)
    return row


def _selection(db: Session, row: Batch) -> LiteratureSearchSelection:
    terms = list(
        db.scalars(
            select(Term.term)
            .where(Term.batch_id == row.id, Term.user_id == row.user_id)
            .order_by(Term.position)
        )
    )
    venues = list(
        db.scalars(
            select(Venue.venue_key)
            .where(Venue.batch_id == row.id, Venue.user_id == row.user_id)
            .order_by(Venue.position)
        )
    )
    return LiteratureSearchSelection(
        question_id=row.question_id,
        query=row.query,
        terms=terms,
        venue_keys=venues,
        from_year=row.from_year,
        until_year=row.until_year,
        page_size=row.page_size,
        provider_key=row.provider_key,
    )


def _receipt_delayed(row: Batch) -> bool:
    started = row.started_at
    started = started.replace(tzinfo=UTC) if started.tzinfo is None else started.astimezone(UTC)
    return row.status == "FETCHING" and (datetime.now(UTC) - started).total_seconds() > 300


def _summary(
    db: Session, row: Batch, candidate_count: int | None = None
) -> LiteratureSearchBatchSummary:
    count = (
        candidate_count
        if candidate_count is not None
        else (
            db.scalar(
                select(func.count())
                .select_from(Candidate)
                .where(Candidate.batch_id == row.id, Candidate.user_id == row.user_id)
            )
            or 0
        )
    )
    return LiteratureSearchBatchSummary.model_validate(
        dict(
            id=row.id,
            project_id=row.project_id,
            parent_batch_id=row.parent_batch_id,
            provider_key=row.provider_key,
            query=row.query,
            status=row.status,
            created_at=row.created_at,
            completed_at=row.completed_at,
            candidate_count=count,
            has_more=row.status == "COMPLETED" and row.next_cursor is not None,
            error_code="SEARCH_RECEIPT_DELAYED" if _receipt_delayed(row) else row.error_code,
            error_message="尚未收到完成回执，结果未知；先核查同批次，勿自动重播。"
            if _receipt_delayed(row)
            else row.error_message,
        )
    )


def _author_map(db: Session, row: Batch) -> dict[uuid.UUID, list[str]]:
    result: dict[uuid.UUID, list[str]] = {}
    for author in db.scalars(
        select(Author)
        .where(Author.batch_id == row.id, Author.user_id == row.user_id)
        .order_by(Author.candidate_id, Author.position)
    ):
        result.setdefault(author.candidate_id, []).append(author.name)
    return result


def _candidate_payload(item: Candidate, authors: list[str]) -> dict[str, object]:
    updated = item.source_updated_at
    if updated is not None:
        updated = updated.replace(tzinfo=UTC) if updated.tzinfo is None else updated.astimezone(UTC)
    return {
        "provider_key": item.provider_key,
        "provider_id": item.provider_id,
        "title": item.title,
        "doi": item.doi,
        "authors": authors,
        "year": item.year,
        "venue": item.venue,
        "paper_type": item.paper_type,
        "abstract": item.abstract,
        "url": item.url,
        "source_hash": item.source_hash,
        "source_updated_at": updated.isoformat() if updated else None,
        "venue_key": item.venue_key,
        "venue_status": item.venue_status,
        "in_scope": item.in_scope,
        "publication_status": item.publication_status,
        "rank_score": item.rank_score,
        "match_reasons": item.match_reasons_json,
        "warnings": item.warnings_json,
    }


def _adoption_warning(item: Candidate, status: str) -> str | None:
    if item.review_status == "ADOPTED":
        return None
    if status != "COMPLETED":
        return "Search context requires attention; this batch cannot be adopted"
    if (
        not item.title
        or not item.title.strip()
        or len(item.title) > 600
        or (item.venue is not None and len(item.venue) > 320)
    ):
        return "Metadata requires title or venue correction before adoption"
    if item.year is not None and not 1400 <= item.year <= 2200:
        return "Reported year is outside supported paper metadata bounds"
    if item.url is not None and len(item.url) > 2000:
        return "Source URL exceeds paper metadata bounds"
    return None


def _adoption_warnings(
    db: Session, row: Batch, items: list[Candidate], authors: dict[uuid.UUID, list[str]]
) -> dict[uuid.UUID, str | None]:
    # Fetch owner identities once, rather than an author/paper query per candidate.
    doi_values = [item.doi for item in items if item.doi]
    title_values = [(" ".join((item.title or "").lower().split()), item.year) for item in items]
    papers = list(
        db.execute(
            select(Paper.id, Paper.normalized_doi, Paper.normalized_title, Paper.year).where(
                Paper.user_id == row.user_id,
                or_(
                    Paper.normalized_doi.in_(doi_values),
                    tuple_(Paper.normalized_title, Paper.year).in_(
                        [value for value in title_values if value[1] is not None]
                    ),
                    Paper.normalized_title.in_(
                        [value[0] for value in title_values if value[1] is None]
                    )
                    & Paper.year.is_(None),
                ),
            )
        )
    )
    doi_papers = {paper.normalized_doi: paper for paper in papers if paper.normalized_doi}
    title_years = {(paper.normalized_title, paper.year) for paper in papers}
    sources = {
        (source.provider_key, source.provider_id): source
        for source in db.scalars(
            select(PaperSource).where(
                PaperSource.user_id == row.user_id,
                PaperSource.provider_key == row.provider_key,
                PaperSource.provider_id.in_([item.provider_id for item in items]),
            )
        )
    }
    result: dict[uuid.UUID, str | None] = {}
    for item in items:
        warning = _adoption_warning(item, row.status)
        if item.review_status != "ADOPTED" and warning is None:
            if any(len(name) > 240 for name in authors.get(item.id, [])):
                warning = "Author names exceed supported paper metadata bounds"
            paper = doi_papers.get(item.doi) if item.doi else None
            source = sources.get((item.provider_key, item.provider_id))
            if source and (paper is None or paper.id != source.paper_id):
                warning = "Provider identity requires manual reconciliation"
            elif (
                paper is None
                and (" ".join((item.title or "").lower().split()), item.year) in title_years
            ):
                warning = "A matching title and year needs manual merge review"
        result[item.id] = warning
    return result


def batch_out(db: Session, row: Batch) -> LiteratureSearchBatchOut:
    authors = _author_map(db, row)
    items = []
    candidates = list(
        db.scalars(
            select(Candidate)
            .where(Candidate.batch_id == row.id, Candidate.user_id == row.user_id)
            .order_by(Candidate.rank_score.desc(), Candidate.id)
        )
    )
    warnings = _adoption_warnings(db, row, candidates, authors)
    for item in candidates:
        warning = warnings[item.id]
        items.append(
            LiteratureCandidateOut.model_validate(
                dict(
                    id=item.id,
                    candidate_sha256=item.candidate_sha256,
                    **_candidate_payload(item, authors.get(item.id, [])),
                    review_status=item.review_status,
                    paper_id=item.paper_id,
                    can_adopt=warning is None,
                    adoption_warning=warning,
                )
            )
        )
    return LiteratureSearchBatchOut(
        **_summary(db, row).model_dump(),
        selection=_selection(db, row),
        project_name=row.project_name,
        project_version=row.project_version,
        question_text=row.question_text,
        context_sha256=row.context_sha256,
        source_url=row.source_url,
        fetched_at=row.fetched_at,
        total_results=row.total_results,
        retry_after_seconds=row.retry_after_seconds,
        warnings=[*row.warnings_json, "SEARCH_RECEIPT_DELAYED"]
        if _receipt_delayed(row)
        else row.warnings_json,
        coverage_note=COVERAGE_NOTE,
        items=items,
    )


def list_batches(
    db: Session, owner: uuid.UUID, project: uuid.UUID, limit: int, cursor: str | None
) -> LiteratureSearchBatchPage:
    get_project(db, owner, project)
    rows = list(
        db.scalars(
            select(Batch)
            .where(
                Batch.user_id == owner, Batch.project_id == project, cursor_filter(Batch, cursor)
            )
            .order_by(Batch.created_at.desc(), Batch.id.desc())
            .limit(limit + 1)
        )
    )
    following = (
        encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    )
    counts = dict(
        db.execute(
            select(Candidate.batch_id, func.count())
            .where(
                Candidate.user_id == owner, Candidate.batch_id.in_([row.id for row in rows[:limit]])
            )
            .group_by(Candidate.batch_id)
        ).all()
    )
    return LiteratureSearchBatchPage(
        items=[_summary(db, row, counts.get(row.id, 0)) for row in rows[:limit]],
        page=PageMeta(limit=limit, next_cursor=following),
    )


def _prior(db: Session, owner: uuid.UUID, project: uuid.UUID, key: str) -> Batch | None:
    return db.scalar(
        select(Batch).where(
            Batch.user_id == owner, Batch.project_id == project, Batch.idempotency_key == key
        )
    )


def _same(prior: Batch, context: str, parent: uuid.UUID | None, cursor: str | None) -> Batch:
    if (
        prior.context_sha256 != context
        or prior.parent_batch_id != parent
        or prior.request_cursor != cursor
    ):
        raise DomainError(
            "IDEMPOTENCY_CONFLICT", "This search key belongs to a different frozen query", 409
        )
    return prior


def _candidate(
    source: PaperCandidate, row: Batch, selection: LiteratureSearchSelection
) -> Candidate:
    key, venue_status = classify_venue(source.venue)
    score, reasons = literal_matches(source.title, source.abstract, selection.terms)
    publication = (
        "PREPRINT"
        if source.paper_type in {"posted-content", "preprint"}
        else "METADATA_REPORTED"
        if source.paper_type in {"journal-article", "proceedings-article"}
        else "UNKNOWN"
    )
    warnings = []
    if not source.abstract:
        warnings.append("ABSTRACT_UNAVAILABLE: matching uses available metadata only")
    if source.year is None:
        warnings.append("PUBLICATION_YEAR_UNVERIFIED")
    elif not (
        selection.from_year is not None
        and selection.until_year is not None
        and selection.from_year <= source.year <= selection.until_year
    ):
        warnings.append("OUTSIDE_RECOMMENDED_YEARS")
    if venue_status != "MATCHED":
        warnings.append("VENUE_REQUIRES_SOURCE_CHECK")
    if publication == "UNKNOWN":
        warnings.append("PUBLICATION_TYPE_UNVERIFIED")
    item = Candidate(
        id=uuid.uuid4(),
        user_id=row.user_id,
        project_id=row.project_id,
        batch_id=row.id,
        provider_key=source.provider_key,
        provider_id=source.provider_id,
        title=source.title,
        doi=normalize_doi(source.doi),
        year=source.year,
        venue=source.venue,
        paper_type=source.paper_type,
        abstract=source.abstract,
        url=source.url,
        source_hash=source.source_hash,
        source_updated_at=source.source_updated_at,
        venue_key=key,
        venue_status=venue_status,
        in_scope=bool(
            source.year is not None
            and selection.from_year is not None
            and selection.until_year is not None
            and selection.from_year <= source.year <= selection.until_year
            and (not selection.venue_keys or key in selection.venue_keys)
        ),
        publication_status=publication,
        rank_score=score,
        match_reasons_json=reasons,
        warnings_json=warnings,
        review_status="CANDIDATE",
    )
    item.candidate_sha256 = sha256(_candidate_payload(item, list(source.authors)))
    return item


def _safe_url(value: str | None) -> bool:
    if value is None:
        return True
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and len(value) <= 20000
            and not any(ord(c) < 32 for c in value)
        )
    except ValueError:
        return False


def _validate_page(
    page: LiteratureSearchPage, query: LiteratureSearchQuery, expected_provider_key: str
) -> None:
    if len(page.warnings) > 100 or any(
        not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", warning) for warning in page.warnings
    ):
        raise ValueError("Invalid provider warning receipt")
    if len(page.items) > query.limit or not _safe_url(page.source_url) or not page.source_url:
        raise ValueError("Invalid provider page bounds")
    if page.fetched_at.tzinfo is None or page.fetched_at.utcoffset() is None:
        raise ValueError("Provider receipt requires timezone")
    if page.total_results is not None and (
        type(page.total_results) is not int or page.total_results < 0
    ):
        raise ValueError("Invalid provider total")
    if page.next_cursor is not None and (
        not 1 <= len(page.next_cursor) <= 16384
        or any(ord(c) < 33 or ord(c) > 126 for c in page.next_cursor)
    ):
        raise ValueError("Invalid provider cursor")
    for source in page.items:
        if (
            source.provider_key != expected_provider_key
            or not source.provider_id
            or len(source.provider_id) > 320
            or not re.fullmatch(r"[0-9a-f]{64}", source.source_hash)
        ):
            raise ValueError("Invalid provider identity")
        if source.doi is not None and (len(source.doi) > 300 or not validate_doi_name(source.doi)):
            raise ValueError("Invalid provider DOI identity")
        if source.year is not None and (
            type(source.year) is not int or not 1400 <= source.year <= 2200
        ):
            raise ValueError("Invalid provider year")
        if (
            not _safe_url(source.url)
            or len(source.authors) > 1000
            or any(not name.strip() or len(name) > 1000 for name in source.authors)
        ):
            raise ValueError("Invalid provider metadata")
        if source.source_updated_at is not None and (
            source.source_updated_at.tzinfo is None or source.source_updated_at.utcoffset() is None
        ):
            raise ValueError("Provider timestamp requires timezone")
        if any(
            value is not None and len(value) > limit
            for value, limit in (
                (source.title, 10000),
                (source.venue, 10000),
                (source.abstract, 200000),
                (source.paper_type, 80),
            )
        ):
            raise ValueError("Invalid provider field bounds")


async def _execute(
    db: Session,
    row: Batch,
    provider: SearchLiteratureProvider,
    selection: LiteratureSearchSelection,
) -> Batch:
    owner, project, identity = row.user_id, row.project_id, row.id
    query = LiteratureSearchQuery(
        query=row.query,
        from_year=row.from_year,
        until_year=row.until_year,
        limit=row.page_size,
        cursor=row.request_cursor,
    )
    # FETCHING is committed, then all reads are released before network I/O.
    db.rollback()
    page: LiteratureSearchPage | None = None
    error = None
    retry_after = None
    try:
        page = await provider.search_papers(query)
        _validate_page(page, query, provider.provider_key)
    except asyncio.CancelledError:
        error = "SEARCH_OUTCOME_UNKNOWN"
    except DomainError as exc:
        error = (
            exc.code
            if exc.code in {"PROVIDER_RATE_LIMITED", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE"}
            else "PROVIDER_SEARCH_FAILED"
        )
        if exc.code == "PROVIDER_RATE_LIMITED" and isinstance(exc.details, dict):
            value = exc.details.get("retry_after_seconds")
            retry_after = value if type(value) is int and 0 <= value <= 86400 else None
    except Exception:
        error = "PROVIDER_SEARCH_FAILED"
    db.expire_all()
    _lock(db, owner)
    current = get_batch(db, owner, project, identity)
    if current.status != "FETCHING":
        return current
    if error:
        current.completed_at = datetime.now(UTC)
        current.status = "NEEDS_ATTENTION" if error == "SEARCH_OUTCOME_UNKNOWN" else "FAILED"
        current.error_code = error
        current.retry_after_seconds = retry_after
        current.error_message = "Metadata request did not complete; inspect this saved batch before a new explicit search"
        db.commit()
        return current
    assert page is not None
    try:
        fresh = preview(db, owner, project, selection)
        changed = fresh.context_sha256 != current.context_sha256
    except DomainError:
        changed = True
    current.completed_at = datetime.now(UTC)
    current.source_url = page.source_url
    current.fetched_at = page.fetched_at
    current.total_results = page.total_results
    current.next_cursor = page.next_cursor
    current.warnings_json = list(page.warnings)
    current.status = "NEEDS_ATTENTION" if changed else "COMPLETED"
    if changed:
        current.error_code = "SEARCH_CONTEXT_CHANGED"
        current.error_message = "Project or research question changed after approval; retained metadata is not eligible for adoption"
    identities: dict[str, str] = {}
    for source in page.items:
        identity_key = normalize_doi(source.doi) or f"{source.provider_key}:{source.provider_id}"
        if identity_key in identities:
            if identities[identity_key] != source.source_hash:
                current.warnings_json = [
                    *current.warnings_json,
                    "DUPLICATE_IDENTITY_METADATA_CONFLICT",
                ]
                current.status = "NEEDS_ATTENTION"
                current.error_code = "PROVIDER_IDENTITY_CONFLICT"
                current.error_message = "Provider returned conflicting metadata for one identity; retained candidates require source review"
            continue
        identities[identity_key] = source.source_hash
        item = _candidate(source, current, selection)
        db.add(item)
        db.flush()
        for position, name in enumerate(source.authors):
            db.add(
                Author(
                    candidate_id=item.id,
                    batch_id=current.id,
                    user_id=owner,
                    project_id=project,
                    position=position,
                    name=name,
                )
            )
    db.commit()
    return current


async def _start(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    selection: LiteratureSearchSelection,
    context: str,
    key: str,
    approve: bool,
    provider: SearchLiteratureProvider,
    *,
    parent: uuid.UUID | None = None,
    cursor: str | None = None,
) -> Batch:
    get_project(db, owner, project)
    if (
        provider.provider_key != selection.provider_key
        or "search_papers" not in provider.capabilities
    ):
        raise DomainError(
            "PROVIDER_NOT_SUPPORTED",
            "Registered provider does not support the approved metadata query",
            422,
        )
    if not approve:
        raise DomainError("APPROVAL_REQUIRED", "Explicit metadata search approval is required", 422)
    _lock(db, owner)
    prior = _prior(db, owner, project, key)
    if prior:
        return _same(prior, context, parent, cursor)
    db.expire_all()
    frozen = preview(db, owner, project, selection)
    if frozen.context_sha256 != context:
        raise DomainError(
            "SEARCH_CONTEXT_CHANGED", "Reload the metadata search preview before approval", 409
        )
    selection = frozen.selection
    project_row = get_project(db, owner, project)
    row = Batch(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project,
        parent_batch_id=parent,
        question_id=selection.question_id,
        query=selection.query,
        provider_key=selection.provider_key,
        from_year=selection.from_year,
        until_year=selection.until_year,
        page_size=selection.page_size,
        project_version=project_row.version,
        project_name=project_row.name,
        question_text=frozen.question,
        context_sha256=context,
        idempotency_key=key,
        status="FETCHING",
        started_at=datetime.now(UTC),
        request_cursor=cursor,
        warnings_json=[],
    )
    db.add(row)
    try:
        db.flush()
        for position, term in enumerate(selection.terms):
            db.add(
                Term(
                    batch_id=row.id, user_id=owner, project_id=project, position=position, term=term
                )
            )
        for position, venue in enumerate(selection.venue_keys):
            db.add(
                Venue(
                    batch_id=row.id,
                    user_id=owner,
                    project_id=project,
                    position=position,
                    venue_key=venue,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        prior = _prior(db, owner, project, key)
        if prior:
            return _same(prior, context, parent, cursor)
        raise DomainError(
            "SEARCH_CONFLICT", "Metadata search admission conflicts with current records", 409
        ) from exc
    return await _execute(db, row, provider, selection)


async def search(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    body: LiteratureSearchStartRequest,
    provider: SearchLiteratureProvider,
) -> Batch:
    return await _start(
        db,
        owner,
        project,
        body.selection,
        body.expected_context_sha256,
        body.idempotency_key,
        body.approve_metadata_search,
        provider,
    )


async def next_page(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    identity: uuid.UUID,
    body: LiteratureSearchNextRequest,
    provider: SearchLiteratureProvider,
) -> Batch:
    row = get_batch(db, owner, project, identity)
    if row.status != "COMPLETED" or row.next_cursor is None:
        raise DomainError("NO_NEXT_PAGE", "This saved batch has no eligible next page", 409)
    return await _start(
        db,
        owner,
        project,
        _selection(db, row),
        row.context_sha256,
        body.idempotency_key,
        body.approve_metadata_search,
        provider,
        parent=row.id,
        cursor=row.next_cursor,
    )


def adopt(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    batch_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: LiteratureCandidateAdoptRequest,
) -> LiteratureCandidateAdoptOut:
    _lock(db, owner)
    row = get_batch(db, owner, project, batch_id)
    item = db.scalar(
        select(Candidate)
        .where(
            Candidate.id == candidate_id,
            Candidate.batch_id == batch_id,
            Candidate.project_id == project,
            Candidate.user_id == owner,
        )
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise DomainError("NOT_FOUND", "Literature candidate not found", 404)
    authors = _author_map(db, row).get(item.id, [])
    if (
        body.expected_candidate_sha256 != item.candidate_sha256
        or sha256(_candidate_payload(item, authors)) != item.candidate_sha256
    ):
        raise DomainError("CANDIDATE_CHANGED", "Reload candidate provenance before adoption", 409)
    if item.review_status == "ADOPTED" and item.paper_id:
        return LiteratureCandidateAdoptOut(
            candidate_id=item.id, paper_id=item.paper_id, created=False, already_adopted=True
        )
    warning = _adoption_warnings(db, row, [item], {item.id: authors})[item.id]
    if warning:
        raise DomainError("CANDIDATE_NOT_ADOPTABLE", warning, 409)
    paper = (
        db.scalar(select(Paper).where(Paper.user_id == owner, Paper.normalized_doi == item.doi))
        if item.doi
        else None
    )
    source = db.scalar(
        select(PaperSource).where(
            PaperSource.user_id == owner,
            PaperSource.provider_key == item.provider_key,
            PaperSource.provider_id == item.provider_id,
        )
    )
    if source and (paper is None or source.paper_id != paper.id):
        raise DomainError(
            "SOURCE_IDENTITY_CONFLICT", "Provider identity requires manual reconciliation", 409
        )
    created = paper is None
    if paper is None:
        title = " ".join((item.title or "").lower().split())
        duplicate = db.scalar(
            select(Paper.id).where(
                Paper.user_id == owner, Paper.normalized_title == title, Paper.year == item.year
            )
        )
        if duplicate:
            raise DomainError(
                "MANUAL_MERGE_REQUIRED", "A matching title and year needs manual merge review", 409
            )
        paper = create_paper(
            db,
            owner,
            PaperCreate(
                title=item.title or "",
                year=item.year,
                doi=item.doi,
                venue_name=item.venue,
                venue_type="journal"
                if item.paper_type == "journal-article"
                else "conference"
                if item.paper_type == "proceedings-article"
                else "other",
                abstract=item.abstract,
                url=item.url,
                authors=authors,
                project_ids=[project],
            ),
            commit=False,
        )
    if source is None:
        db.add(
            PaperSource(
                user_id=owner,
                paper_id=paper.id,
                provider_key=item.provider_key,
                provider_id=item.provider_id,
                source_url=item.url,
                payload_sha256=item.source_hash,
                source_updated_at=item.source_updated_at,
                fetched_at=row.fetched_at or datetime.now(UTC),
            )
        )
    if db.get(ProjectPaper, (project, paper.id, "related")) is None:
        db.add(ProjectPaper(project_id=project, paper_id=paper.id, role="related"))
    item.review_status, item.paper_id = "ADOPTED", paper.id
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError(
            "ADOPTION_CONFLICT", "Current paper identity requires manual reconciliation", 409
        ) from exc
    return LiteratureCandidateAdoptOut(
        candidate_id=item.id, paper_id=paper.id, created=created, already_adopted=False
    )
