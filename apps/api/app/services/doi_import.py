"""Owner-reviewed Crossref DOI candidate lifecycle; no automatic metadata overwrite."""

import uuid
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.literature import DoiLookupProvider, PaperCandidate
from app.domain.literature_identity import validate_doi
from app.errors import DomainError
from app.models import Paper, PaperSource, User
from app.schemas import PaperCreate
from app.services.papers import create_paper, normalize_doi

DoiStatus = Literal[
    "new", "existing_doi", "already_linked", "possible_duplicate", "conflict", "invalid"
]


@dataclass(frozen=True)
class DoiPreview:
    doi: str
    source_hash: str
    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    url: str | None
    status: DoiStatus
    existing_paper_id: uuid.UUID | None
    warning: str | None


@dataclass(frozen=True)
class DoiImportResult:
    created: uuid.UUID | None = None
    linked: uuid.UUID | None = None
    skipped: uuid.UUID | None = None


def _validate_candidate(
    provider: DoiLookupProvider, requested: str, candidate: PaperCandidate
) -> None:
    if (
        candidate.provider_key != provider.provider_key
        or not candidate.provider_id
        or len(candidate.provider_id) > 320
        or any(ord(character) < 32 for character in candidate.provider_id)
        or normalize_doi(candidate.doi) != requested
        or len(candidate.source_hash) != 64
        or any(character not in "0123456789abcdef" for character in candidate.source_hash)
    ):
        raise DomainError(
            "PROVIDER_UNAVAILABLE", "Literature provider returned inconsistent metadata", 503
        )


def _assess(db: Session, user_id: uuid.UUID, candidate: PaperCandidate) -> DoiPreview:
    assert candidate.doi is not None  # The DOI lookup port validates its identity first.
    errors: list[str] = []
    status: DoiStatus
    paper_id: uuid.UUID | None
    warning: str | None
    if not candidate.title or not candidate.title.strip():
        errors.append("missing_title")
    if candidate.title and len(candidate.title) > 600:
        errors.append("title_too_long")
    if candidate.year is not None and not 1400 <= candidate.year <= 2200:
        errors.append("invalid_year")
    if candidate.venue and len(candidate.venue) > 320:
        errors.append("venue_too_long")
    if candidate.url and len(candidate.url) > 2000:
        errors.append("url_too_long")
    if any(len(author) > 240 for author in candidate.authors):
        errors.append("author_name_too_long")
    if candidate.doi is None:
        errors.append("missing_doi")
    elif len(candidate.doi) > 300:
        errors.append("doi_too_long")
    if errors:
        status = "invalid"
        paper_id = None
        warning = ", ".join(errors)
    else:
        source = db.scalar(
            select(PaperSource).where(
                PaperSource.user_id == user_id,
                PaperSource.provider_key == candidate.provider_key,
                PaperSource.provider_id == candidate.provider_id,
            )
        )
        existing = db.scalar(
            select(Paper).where(
                Paper.user_id == user_id,
                Paper.normalized_doi == candidate.doi,
            )
        )
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
        if source is not None:
            target = db.scalar(
                select(Paper).where(Paper.id == source.paper_id, Paper.user_id == user_id)
            )
            if (
                target is None
                or (existing is not None and existing.id != source.paper_id)
                or (target.normalized_doi not in (None, candidate.doi))
            ):
                status, paper_id, warning = (
                    "conflict",
                    source.paper_id,
                    "来源身份与现有 DOI 记录冲突，需人工核对。",
                )
            else:
                status, paper_id = "already_linked", source.paper_id
                warning = (
                    "来源元数据已变化；现有论文不自动更新，请人工核对。"
                    if source.payload_sha256 and source.payload_sha256 != candidate.source_hash
                    else None
                )
        elif existing is not None:
            status, paper_id = "existing_doi", existing.id
            warning = "DOI 已存在；确认后只登记来源，不覆盖人工字段。"
            if existing.normalized_title != title:
                warning += " 标题不同，请核对。"
        elif possible:
            status = "possible_duplicate"
            paper_id = possible[0].id if len(possible) == 1 else None
            warning = "标题和年份匹配现有记录，需人工核对，暂不自动合并。"
        else:
            status, paper_id, warning = "new", None, None
    return DoiPreview(
        doi=candidate.doi,
        source_hash=candidate.source_hash,
        title=candidate.title,
        authors=list(candidate.authors),
        year=candidate.year,
        venue=candidate.venue,
        abstract=candidate.abstract,
        url=candidate.url,
        status=status,
        existing_paper_id=paper_id,
        warning=warning,
    )


async def _lookup(provider: DoiLookupProvider, doi: str) -> PaperCandidate:
    requested = validate_doi(doi)
    candidate = await provider.get_paper_by_doi(requested)
    if candidate is None:
        raise DomainError("NOT_FOUND", "DOI was not found in the configured provider", 404)
    _validate_candidate(provider, requested, candidate)
    return replace(candidate, doi=requested)


async def preview_doi(
    db: Session, user_id: uuid.UUID, provider: DoiLookupProvider, doi: str
) -> DoiPreview:
    candidate = await _lookup(provider, doi)
    return _assess(db, user_id, candidate)


def _venue_type(paper_type: str | None) -> Literal["journal", "conference", "preprint", "other"]:
    if paper_type == "journal-article":
        return "journal"
    if paper_type in {"proceedings-article", "conference-paper"}:
        return "conference"
    if paper_type in {"posted-content", "preprint"}:
        return "preprint"
    return "other"


async def confirm_doi(
    db: Session,
    user_id: uuid.UUID,
    provider: DoiLookupProvider,
    doi: str,
    expected_hash: str,
    expected_status: DoiStatus,
    existing_paper_id: uuid.UUID | None,
) -> DoiImportResult:
    candidate = await _lookup(provider, doi)
    if candidate.source_hash != expected_hash:
        raise DomainError("CONFLICT", "Provider metadata changed; preview again", 409)
    if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        db.rollback()
        raise DomainError("UNAUTHORIZED", "Owner account is unavailable", 401)
    current = _assess(db, user_id, candidate)
    if current.status == "already_linked" and expected_status in {"new", "existing_doi"}:
        if existing_paper_id is not None and existing_paper_id != current.existing_paper_id:
            db.rollback()
            raise DomainError("CONFLICT", "DOI source target changed; preview again", 409)
        assert current.existing_paper_id is not None
        db.commit()
        return DoiImportResult(skipped=current.existing_paper_id)
    if current.status != expected_status or current.existing_paper_id != existing_paper_id:
        db.rollback()
        raise DomainError("CONFLICT", "DOI candidate changed; preview again", 409)
    if current.status not in {"new", "existing_doi"}:
        db.rollback()
        raise DomainError("CONFLICT", "DOI candidate needs manual review", 409)
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
                    venue_type=_venue_type(candidate.paper_type),
                    authors=current.authors,
                    doi=current.doi,
                    abstract=current.abstract,
                    url=current.url,
                ),
                commit=False,
            )
        else:
            assert current.existing_paper_id is not None
            linked = db.scalar(
                select(Paper).where(
                    Paper.id == current.existing_paper_id,
                    Paper.user_id == user_id,
                )
            )
            if linked is None:
                raise DomainError("CONFLICT", "Existing paper changed; preview again", 409)
            paper = linked
        db.add(
            PaperSource(
                id=uuid.uuid4(),
                user_id=user_id,
                paper_id=paper.id,
                provider_key=candidate.provider_key,
                provider_id=candidate.provider_id,
                source_version=None,
                source_url=candidate.url,
                payload_sha256=candidate.source_hash,
                source_updated_at=candidate.source_updated_at,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("CONFLICT", "DOI import conflicted; preview again", 409) from exc
    except Exception:
        db.rollback()
        raise
    return DoiImportResult(
        created=paper.id if current.status == "new" else None,
        linked=paper.id if current.status == "existing_doi" else None,
    )
