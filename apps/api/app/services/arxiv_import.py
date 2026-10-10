"""Version-pinned, owner-reviewed arXiv metadata import without PDF fetching."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.literature import PaperCandidate, PaperIdLookupProvider
from app.domain.literature_identity import parse_arxiv_identity, validate_doi
from app.errors import DomainError
from app.models import Paper, PaperSource, User
from app.schemas import PaperCreate
from app.services.papers import create_paper

ArxivStatus = Literal[
    "new",
    "existing_doi",
    "existing_arxiv",
    "already_linked",
    "possible_duplicate",
    "conflict",
    "invalid",
]


@dataclass(frozen=True)
class ArxivPreview:
    arxiv_id: str
    versioned_id: str
    source_version: int
    doi: str | None
    source_hash: str
    source_updated_at: datetime | None
    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    url: str | None
    pdf_url: str | None
    status: ArxivStatus
    existing_paper_id: uuid.UUID | None
    warning: str | None


@dataclass(frozen=True)
class ArxivImportResult:
    created: uuid.UUID | None = None
    linked: uuid.UUID | None = None
    skipped: uuid.UUID | None = None


async def _lookup(provider: PaperIdLookupProvider, arxiv_id: str) -> PaperCandidate:
    requested = parse_arxiv_identity(arxiv_id)
    candidate = await provider.get_paper_by_id(requested.query_id)
    if candidate is None:
        raise DomainError("NOT_FOUND", "arXiv article/version was not found", 404)
    try:
        returned = parse_arxiv_identity(candidate.provider_id)
        normalized_doi = validate_doi(candidate.doi) if candidate.doi is not None else None
    except DomainError as exc:
        raise DomainError(
            "PROVIDER_UNAVAILABLE", "Literature provider returned inconsistent identity", 503
        ) from exc
    if (
        provider.provider_key != candidate.provider_key
        or returned.canonical_id != requested.canonical_id
        or returned.version is None
        or returned.version != candidate.source_version
        or candidate.provider_id != returned.query_id
        or (requested.version is not None and returned.version != requested.version)
        or candidate.arxiv_id != returned.canonical_id
        or len(candidate.source_hash) != 64
        or any(character not in "0123456789abcdef" for character in candidate.source_hash)
        or candidate.doi != normalized_doi
    ):
        raise DomainError(
            "PROVIDER_UNAVAILABLE",
            "Literature provider returned inconsistent identity/version",
            503,
        )
    return candidate


def _assess(db: Session, user_id: uuid.UUID, candidate: PaperCandidate) -> ArxivPreview:
    assert candidate.arxiv_id is not None and candidate.source_version is not None
    errors: list[str] = []
    if not candidate.title or not candidate.title.strip():
        errors.append("missing_title")
    if candidate.title and len(candidate.title) > 600:
        errors.append("title_too_long")
    if candidate.year is not None and not 1400 <= candidate.year <= 2200:
        errors.append("invalid_year")
    if candidate.venue and len(candidate.venue) > 320:
        errors.append("venue_too_long")
    if (candidate.url and len(candidate.url) > 2000) or (
        candidate.pdf_url and len(candidate.pdf_url) > 2000
    ):
        errors.append("url_too_long")
    if any(len(author) > 240 for author in candidate.authors):
        errors.append("author_name_too_long")
    if candidate.doi and len(candidate.doi) > 300:
        errors.append("doi_too_long")
    status: ArxivStatus = "invalid"
    paper_id: uuid.UUID | None = None
    warning = ", ".join(errors) if errors else None
    if not errors:
        source = db.scalar(
            select(PaperSource).where(
                PaperSource.user_id == user_id,
                PaperSource.provider_key == candidate.provider_key,
                PaperSource.provider_id == candidate.provider_id,
            )
        )
        arxiv_match = db.scalar(
            select(Paper).where(
                Paper.user_id == user_id, Paper.normalized_arxiv_id == candidate.arxiv_id
            )
        )
        doi_match = (
            db.scalar(
                select(Paper).where(Paper.user_id == user_id, Paper.normalized_doi == candidate.doi)
            )
            if candidate.doi
            else None
        )
        target = (
            db.scalar(select(Paper).where(Paper.user_id == user_id, Paper.id == source.paper_id))
            if source
            else None
        )
        matched = target or arxiv_match or doi_match
        ids = {paper.id for paper in (target, arxiv_match, doi_match) if paper is not None}
        if len(ids) > 1 or (
            source is not None
            and (target is None or source.source_version != candidate.source_version)
        ):
            status, warning = "conflict", "DOI、arXiv 或来源身份指向不同记录，需人工核对。"
        elif matched is not None and (
            matched.normalized_arxiv_id not in (None, candidate.arxiv_id)
            or (matched.arxiv_id is not None and matched.normalized_arxiv_id is None)
            or (candidate.doi is not None and matched.normalized_doi not in (None, candidate.doi))
        ):
            status, paper_id, warning = (
                "conflict",
                matched.id,
                "现有论文的 DOI/arXiv 标识与候选不一致或无法规范，需人工核对。",
            )
        elif source is not None:
            status, paper_id = "already_linked", source.paper_id
            if source.payload_sha256 and source.payload_sha256 != candidate.source_hash:
                warning = "同一来源版本的元数据已变化；保留已确认来源和人工字段，请核对。"
        elif arxiv_match is not None or doi_match is not None:
            assert matched is not None
            status, paper_id = ("existing_arxiv" if arxiv_match else "existing_doi"), matched.id
            warning = "标识匹配现有论文；确认后只登记此版本来源和规范身份，不覆盖人工字段。"
            if matched.normalized_title != " ".join((candidate.title or "").casefold().split()):
                warning += " 标题不同，请核对。"
        else:
            title = " ".join((candidate.title or "").casefold().split())
            possible = list(
                db.scalars(
                    select(Paper).where(
                        Paper.user_id == user_id,
                        Paper.normalized_title == title,
                        Paper.year == candidate.year,
                    )
                )
            )
            if possible:
                status, paper_id, warning = (
                    "possible_duplicate",
                    possible[0].id if len(possible) == 1 else None,
                    "标题和年份匹配现有论文，需人工核对，暂不自动合并。",
                )
            else:
                status = "new"
    return ArxivPreview(
        arxiv_id=candidate.arxiv_id,
        versioned_id=candidate.provider_id,
        source_version=candidate.source_version,
        doi=candidate.doi,
        source_hash=candidate.source_hash,
        source_updated_at=candidate.source_updated_at,
        title=candidate.title,
        authors=list(candidate.authors),
        year=candidate.year,
        venue=candidate.venue,
        abstract=candidate.abstract,
        url=candidate.url,
        pdf_url=candidate.pdf_url,
        status=status,
        existing_paper_id=paper_id,
        warning=warning,
    )


async def preview_arxiv(
    db: Session, user_id: uuid.UUID, provider: PaperIdLookupProvider, arxiv_id: str
) -> ArxivPreview:
    return _assess(db, user_id, await _lookup(provider, arxiv_id))


async def confirm_arxiv(
    db: Session,
    user_id: uuid.UUID,
    provider: PaperIdLookupProvider,
    arxiv_id: str,
    expected_hash: str,
    expected_status: ArxivStatus,
    existing_paper_id: uuid.UUID | None,
    expected_version: int,
) -> ArxivImportResult:
    requested = parse_arxiv_identity(arxiv_id)
    if requested.version is None or requested.version != expected_version:
        raise DomainError("CONFLICT", "Confirm the exact previewed arXiv version", 409)
    candidate = await _lookup(provider, requested.query_id)
    if candidate.source_hash != expected_hash:
        raise DomainError("CONFLICT", "Provider metadata changed; preview again", 409)
    if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        db.rollback()
        raise DomainError("UNAUTHORIZED", "Owner account is unavailable", 401)
    current = _assess(db, user_id, candidate)
    if current.status == "already_linked" and expected_status in {
        "new",
        "existing_doi",
        "existing_arxiv",
        "already_linked",
    }:
        if existing_paper_id is not None and existing_paper_id != current.existing_paper_id:
            db.rollback()
            raise DomainError("CONFLICT", "Source target changed; preview again", 409)
        db.commit()
        return ArxivImportResult(skipped=current.existing_paper_id)
    if current.status != expected_status or current.existing_paper_id != existing_paper_id:
        db.rollback()
        raise DomainError("CONFLICT", "arXiv candidate changed; preview again", 409)
    if current.status not in {"new", "existing_doi", "existing_arxiv"}:
        db.rollback()
        raise DomainError("CONFLICT", "arXiv candidate needs manual review", 409)
    try:
        if current.status == "new":
            assert current.title is not None
            paper = create_paper(
                db,
                user_id,
                PaperCreate(
                    title=current.title,
                    year=current.year,
                    venue_name=current.venue,
                    venue_type="preprint",
                    authors=current.authors,
                    doi=current.doi,
                    arxiv_id=current.arxiv_id,
                    abstract=current.abstract,
                    url=current.url,
                    pdf_url=current.pdf_url,
                ),
                commit=False,
            )
        else:
            linked = db.scalar(
                select(Paper).where(Paper.id == current.existing_paper_id, Paper.user_id == user_id)
            )
            if linked is None:
                raise DomainError("CONFLICT", "Existing paper changed; preview again", 409)
            paper = linked
            # Internal identity projection from this reviewed source is not an owner field.
            if paper.normalized_arxiv_id is None:
                paper.normalized_arxiv_id = current.arxiv_id
        db.add(
            PaperSource(
                id=uuid.uuid4(),
                user_id=user_id,
                paper_id=paper.id,
                provider_key=candidate.provider_key,
                provider_id=candidate.provider_id,
                source_version=candidate.source_version,
                source_url=candidate.url,
                payload_sha256=candidate.source_hash,
                source_updated_at=candidate.source_updated_at,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("CONFLICT", "arXiv import conflicted; preview again", 409) from exc
    except Exception:
        db.rollback()
        raise
    return ArxivImportResult(
        created=paper.id if current.status == "new" else None,
        linked=paper.id if current.status != "new" else None,
    )
