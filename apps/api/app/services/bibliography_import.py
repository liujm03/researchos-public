"""Preview bibliography candidates before owner-confirmed, atomic Paper writes."""

import hashlib
import uuid
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.bibliography import (
    BibliographyCandidate,
    BibliographyFormat,
    BibliographyParseError,
    BibliographyParser,
)
from app.domain.literature_identity import normalized_arxiv_id
from app.errors import DomainError
from app.models import Paper, PaperSource
from app.schemas import PaperCreate
from app.services.papers import create_paper, normalize_doi

ImportStatus = Literal[
    "new",
    "existing_doi",
    "existing_arxiv",
    "already_linked",
    "possible_duplicate",
    "duplicate_in_batch",
    "conflict",
    "invalid",
]


@dataclass(frozen=True)
class ImportRecord:
    source_key: str
    source_hash: str
    key: str | None
    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    abstract: str | None
    url: str | None
    entry_type: str
    status: ImportStatus
    existing_paper_id: uuid.UUID | None
    warning: str | None


@dataclass(frozen=True)
class ImportPreview:
    input_sha256: str
    records: list[ImportRecord]


@dataclass(frozen=True)
class ImportSelection:
    source_key: str
    expected_status: ImportStatus
    existing_paper_id: uuid.UUID | None


@dataclass(frozen=True)
class ImportResult:
    created: list[uuid.UUID]
    linked: list[uuid.UUID]
    skipped: list[uuid.UUID]


def _parse(
    parser: BibliographyParser, content: str, source_format: BibliographyFormat
) -> list[BibliographyCandidate]:
    try:
        return parser.parse(content, source_format)
    except BibliographyParseError as exc:
        raise DomainError(exc.code.upper(), str(exc), 422) from exc


def _input_hash(content: str) -> str:
    try:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise DomainError("UNSUPPORTED_ENCODING", "Use UTF-8 text for import", 422) from exc


def _record(
    db: Session,
    user_id: uuid.UUID,
    source_format: BibliographyFormat,
    candidate: BibliographyCandidate,
) -> ImportRecord:
    errors = list(candidate.errors)
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
    if candidate.arxiv_id and len(candidate.arxiv_id) > 100:
        errors.append("arxiv_id_too_long")
    if candidate.arxiv_id and normalized_arxiv_id(candidate.arxiv_id) is None:
        errors.append("invalid_arxiv_id")
    if any(len(author) > 240 for author in candidate.authors):
        errors.append("author_name_too_long")
    doi = normalize_doi(candidate.doi)
    if doi and (not doi.startswith("10.") or "/" not in doi):
        errors.append("invalid_doi")
    if errors:
        status: ImportStatus = "invalid"
        paper_id = None
        warning = ", ".join(dict.fromkeys(errors))
    else:
        source = db.scalar(
            select(PaperSource).where(
                PaperSource.user_id == user_id,
                PaperSource.provider_key == source_format,
                PaperSource.provider_id == candidate.source_key,
            )
        )
        doi_match = (
            db.scalar(select(Paper).where(Paper.user_id == user_id, Paper.normalized_doi == doi))
            if doi
            else None
        )
        arxiv_match = (
            db.scalar(
                select(Paper).where(
                    Paper.user_id == user_id,
                    Paper.normalized_arxiv_id == normalized_arxiv_id(candidate.arxiv_id),
                )
            )
            if normalized_arxiv_id(candidate.arxiv_id)
            else None
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
            status, paper_id, warning = "already_linked", source.paper_id, None
        elif doi_match and arxiv_match and doi_match.id != arxiv_match.id:
            status, paper_id, warning = "conflict", None, "DOI 与 arXiv ID 指向不同论文"
        elif (
            doi_match
            and candidate.arxiv_id
            and doi_match.normalized_arxiv_id not in (None, normalized_arxiv_id(candidate.arxiv_id))
        ):
            status, paper_id, warning = (
                "conflict",
                doi_match.id,
                "现有论文的 arXiv ID 与导入记录不同",
            )
        elif arxiv_match and doi and arxiv_match.normalized_doi not in (None, doi):
            status, paper_id, warning = "conflict", arxiv_match.id, "现有论文的 DOI 与导入记录不同"
        elif doi_match:
            status, paper_id = "existing_doi", doi_match.id
            warning = "DOI 已存在；确认后只登记新来源，不覆盖现有字段。"
            if doi_match.normalized_title != title:
                warning += " 标题不同，请核对。"
        elif arxiv_match:
            status, paper_id = "existing_arxiv", arxiv_match.id
            warning = "arXiv ID 已存在；确认后只登记新来源，不覆盖现有字段。"
        elif possible:
            status = "possible_duplicate"
            paper_id = possible[0].id if len(possible) == 1 else None
            warning = "标题与年份匹配现有记录，需人工核对，暂不自动合并。"
        else:
            status, paper_id, warning = "new", None, None
    return ImportRecord(
        source_key=candidate.source_key,
        source_hash=candidate.source_hash,
        key=candidate.key,
        title=candidate.title,
        authors=list(candidate.authors),
        year=candidate.year,
        venue=candidate.venue,
        doi=candidate.doi,
        arxiv_id=candidate.arxiv_id,
        abstract=candidate.abstract,
        url=candidate.url,
        entry_type=candidate.entry_type,
        status=status,
        existing_paper_id=paper_id,
        warning=warning,
    )


def preview_bibliography(
    db: Session,
    user_id: uuid.UUID,
    parser: BibliographyParser,
    source_format: BibliographyFormat,
    content: str,
) -> ImportPreview:
    candidates = _parse(parser, content, source_format)
    seen: set[tuple[object, ...]] = set()
    records: list[ImportRecord] = []
    for candidate in candidates:
        record = _record(db, user_id, source_format, candidate)
        if record.status == "new":
            identity: tuple[object, ...] = (
                ("doi", normalize_doi(record.doi))
                if record.doi
                else ("arxiv", normalized_arxiv_id(record.arxiv_id))
                if normalized_arxiv_id(record.arxiv_id)
                else ("title_year", " ".join((record.title or "").casefold().split()), record.year)
            )
            if identity in seen:
                record = replace(
                    record,
                    status="duplicate_in_batch",
                    warning="本批次已有相同标识或标题/年份的候选",
                )
            else:
                seen.add(identity)
        records.append(record)
    return ImportPreview(
        input_sha256=_input_hash(content),
        records=records,
    )


def _venue_type(entry_type: str) -> Literal["journal", "conference", "preprint", "other"]:
    kind = entry_type.casefold()
    if kind in {"article", "journal", "jour", "jfull", "ejour"}:
        return "journal"
    if kind in {"inproceedings", "conference", "conf", "cpaper"}:
        return "conference"
    if kind in {"preprint", "unpublished", "unpb"}:
        return "preprint"
    return "other"


def confirm_bibliography(
    db: Session,
    user_id: uuid.UUID,
    parser: BibliographyParser,
    source_format: BibliographyFormat,
    content: str,
    input_sha256: str,
    selections: list[ImportSelection],
) -> ImportResult:
    if not selections:
        raise DomainError("VALIDATION_ERROR", "Select at least one bibliography record", 422)
    if _input_hash(content) != input_sha256:
        raise DomainError("CONFLICT", "Bibliography input changed after preview", 409)
    preview = preview_bibliography(db, user_id, parser, source_format, content)
    by_key = {record.source_key: record for record in preview.records}
    if len(by_key) != len(preview.records):
        raise DomainError("INVALID_BIBLIOGRAPHY", "Bibliography source keys are not unique", 422)
    if len({item.source_key for item in selections}) != len(selections):
        raise DomainError("VALIDATION_ERROR", "Selection contains duplicate source keys", 422)
    resolved: list[ImportRecord] = []
    for selection in selections:
        record = by_key.get(selection.source_key)
        if record is None:
            raise DomainError("VALIDATION_ERROR", "Selected bibliography record is missing", 422)
        if record.status == "already_linked" and selection.expected_status in {
            "new",
            "existing_doi",
            "existing_arxiv",
        }:
            if (
                selection.existing_paper_id is not None
                and selection.existing_paper_id != record.existing_paper_id
            ):
                raise DomainError("CONFLICT", "Bibliography source target changed", 409)
            resolved.append(record)
            continue
        if (
            record.status != selection.expected_status
            or record.existing_paper_id != selection.existing_paper_id
        ):
            raise DomainError("CONFLICT", "Bibliography candidate changed; preview again", 409)
        if record.status not in {"new", "existing_doi", "existing_arxiv"}:
            raise DomainError("CONFLICT", "This candidate needs manual review", 409)
        resolved.append(record)
    created: list[uuid.UUID] = []
    linked: list[uuid.UUID] = []
    skipped: list[uuid.UUID] = []
    try:
        for record in resolved:
            if record.status == "already_linked":
                assert record.existing_paper_id is not None
                skipped.append(record.existing_paper_id)
                continue
            if record.status == "new":
                assert record.title is not None
                paper = create_paper(
                    db,
                    user_id,
                    PaperCreate(
                        title=record.title,
                        year=record.year,
                        venue_name=record.venue,
                        venue_type=_venue_type(record.entry_type),
                        authors=record.authors,
                        doi=record.doi,
                        arxiv_id=record.arxiv_id,
                        abstract=record.abstract,
                        url=record.url,
                    ),
                    commit=False,
                )
                created.append(paper.id)
            else:
                assert record.existing_paper_id is not None
                matched = db.scalar(
                    select(Paper).where(
                        Paper.id == record.existing_paper_id,
                        Paper.user_id == user_id,
                    )
                )
                if matched is None:
                    raise DomainError("CONFLICT", "Existing paper changed; preview again", 409)
                paper = matched
                linked.append(paper.id)
            db.add(
                PaperSource(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    paper_id=paper.id,
                    provider_key=source_format,
                    provider_id=record.source_key,
                    source_version=None,
                    source_url=record.url,
                    payload_sha256=record.source_hash,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("CONFLICT", "Bibliography import conflicted; preview again", 409) from exc
    except Exception:
        db.rollback()
        raise
    return ImportResult(created=created, linked=linked, skipped=skipped)
