"""Bounded, read-only BibTeX and RIS file parsing.

The resulting candidates are deliberately not persisted. Import confirmation must
reparse the same bytes and apply owner-scoped provenance and conflict checks.
"""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Any, cast

import rispy  # type: ignore[import-untyped]
from pybtex.database import parse_string  # type: ignore[import-untyped]

from app.domain.bibliography import (
    BibliographyCandidate,
    BibliographyFormat,
    BibliographyParseError,
)
from app.domain.literature_identity import extract_doi_name, parse_arxiv_identity
from app.errors import DomainError

MAX_BYTES = 1024 * 1024
MAX_RECORDS = 500
_RIS_TAG = re.compile(r"^([A-Za-z0-9]{2})  -(?:[ \t]?(.*))?$")


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return _text(value[0]) if value else None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _bibtex_text(value: object) -> str | None:
    cleaned = _text(value)
    if cleaned is None:
        return None
    # BibTeX braces group case-sensitive text; the grouping is not title content.
    return cleaned.replace("{", "").replace("}", "") or None


def _year(value: object, errors: list[str]) -> int | None:
    cleaned = _text(value)
    if cleaned is None:
        return None
    match = re.match(r"^(\d{4})(?:\b|[/-])", cleaned)
    if match is None:
        errors.append("invalid_year")
        return None
    year = int(match.group(1))
    if not 1000 <= year <= 2999:
        errors.append("invalid_year")
        return None
    return year


def _doi(value: object) -> str | None:
    cleaned = _text(value)
    if cleaned is None:
        return None
    return extract_doi_name(cleaned)


def _arxiv(value: object, url: str | None) -> str | None:
    for identifier in (_text(value), url):
        if identifier:
            try:
                return parse_arxiv_identity(identifier).query_id
            except DomainError:
                continue
    return None


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k).lower(): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if value is None:
        return None
    return _text(value)


def _finish(
    *,
    format: BibliographyFormat,
    key: str | None,
    title: str | None,
    authors: tuple[str, ...],
    year: int | None,
    venue: str | None,
    doi: str | None,
    arxiv_id: str | None,
    abstract: str | None,
    url: str | None,
    entry_type: str,
    raw: object,
    errors: list[str],
    occurrences: dict[str, int],
) -> BibliographyCandidate:
    if title is None:
        errors.append("missing_title")
    payload = json.dumps(
        {"format": format, "raw": _canonical(raw)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    source_hash = hashlib.sha256(payload).hexdigest()
    occurrences[source_hash] += 1
    return BibliographyCandidate(
        key=key,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        abstract=abstract,
        url=url,
        entry_type=entry_type,
        source_key=f"{format}:{source_hash}:{occurrences[source_hash]}",
        source_hash=source_hash,
        errors=tuple(errors),
    )


def _parse_bibtex(content: str) -> list[BibliographyCandidate]:
    try:
        bibliography = parse_string(content, "bibtex")
    except Exception as exc:
        raise BibliographyParseError("invalid_bibtex", "BibTeX syntax is invalid.") from exc
    entries: Mapping[str, Any] = cast(Mapping[str, Any], bibliography.entries)
    if len(entries) > MAX_RECORDS:
        raise BibliographyParseError("too_many_records", "At most 500 records are allowed.")
    occurrences: dict[str, int] = defaultdict(int)
    candidates: list[BibliographyCandidate] = []
    for key, entry in entries.items():
        fields: Mapping[str, object] = cast(Mapping[str, object], entry.fields)
        persons: Mapping[str, list[object]] = cast(Mapping[str, list[object]], entry.persons)
        errors: list[str] = []
        title = _bibtex_text(fields.get("title"))
        url = _text(fields.get("url"))
        eprint = fields.get("eprint") or fields.get("arxiv_id")
        archive = _text(fields.get("archiveprefix"))
        arxiv_id = _arxiv(eprint, url) if archive is None or archive.lower() == "arxiv" else None
        raw = {
            "key": key,
            "type": str(entry.type),
            "fields": fields,
            "authors": [str(person) for person in persons.get("author", [])],
        }
        candidates.append(
            _finish(
                format="bibtex",
                key=key,
                title=title,
                authors=tuple(str(person) for person in persons.get("author", [])),
                year=_year(fields.get("year"), errors),
                venue=_bibtex_text(
                    fields.get("journal") or fields.get("booktitle") or fields.get("howpublished")
                ),
                doi=_doi(fields.get("doi")),
                arxiv_id=arxiv_id,
                abstract=_bibtex_text(fields.get("abstract")),
                url=url,
                entry_type=str(entry.type).lower(),
                raw=raw,
                errors=errors,
                occurrences=occurrences,
            )
        )
    return candidates


def _ris_records(content: str) -> list[tuple[tuple[str, ...], dict[str, list[str]]]]:
    records: list[tuple[tuple[str, ...], dict[str, list[str]]]] = []
    active = False
    current: list[str] = []
    raw_tags: dict[str, list[str]] = {}
    previous_tag: str | None = None
    for line in content.lstrip("\ufeff").splitlines():
        if not line.strip():
            continue
        match = _RIS_TAG.fullmatch(line)
        if match is None:
            if active and line[:1].isspace() and previous_tag is not None:
                raw_tags[previous_tag][-1] += " " + line.strip()
                if previous_tag in {"AU", "A1"} and current:
                    current[-1] += " " + line.strip()
                continue  # rispy attaches the continuation to the previous tag.
            raise BibliographyParseError("invalid_ris", "RIS tag syntax is invalid.")
        tag, value = match.group(1).upper(), (match.group(2) or "").strip()
        if tag == "TY":
            if active or not value:
                raise BibliographyParseError("invalid_ris", "RIS record boundary is invalid.")
            active = True
            current = []
            raw_tags = {}
            if len(records) >= MAX_RECORDS:
                raise BibliographyParseError("too_many_records", "At most 500 records are allowed.")
        elif tag == "ER":
            if not active:
                raise BibliographyParseError("invalid_ris", "RIS record boundary is invalid.")
            records.append((tuple(current), raw_tags))
            active = False
            previous_tag = None
            continue
        elif not active:
            raise BibliographyParseError("invalid_ris", "RIS data is outside a record.")
        elif tag in {"AU", "A1"} and value:
            current.append(value)
        raw_tags.setdefault(tag, []).append(value)
        previous_tag = tag
    if active:
        raise BibliographyParseError("invalid_ris", "RIS record is missing ER.")
    return records


def _parse_ris(content: str) -> list[BibliographyCandidate]:
    source_records = _ris_records(content)
    try:
        parsed = rispy.loads(content.lstrip("\ufeff"))
    except Exception as exc:
        raise BibliographyParseError("invalid_ris", "RIS syntax is invalid.") from exc
    if len(parsed) != len(source_records):
        raise BibliographyParseError("invalid_ris", "RIS parser did not retain every record.")
    occurrences: dict[str, int] = defaultdict(int)
    candidates: list[BibliographyCandidate] = []
    for record, (authors, raw_tags) in zip(parsed, source_records, strict=True):
        if not isinstance(record, dict):
            raise BibliographyParseError("invalid_ris", "RIS record is invalid.")
        data = cast(dict[str, object], record)
        errors: list[str] = []
        url = _text(data.get("urls") or data.get("url"))
        candidates.append(
            _finish(
                format="ris",
                key=_text(data.get("id")),
                title=_text(data.get("title") or data.get("primary_title")),
                authors=authors,
                year=_year(data.get("year") or data.get("publication_year"), errors),
                venue=_text(
                    data.get("journal_name")
                    or data.get("secondary_title")
                    or data.get("alternate_title3")
                ),
                doi=_doi(data.get("doi")),
                arxiv_id=_arxiv(data.get("accession_number"), url),
                abstract=_text(data.get("abstract") or data.get("notes_abstract")),
                url=url,
                entry_type=(_text(data.get("type_of_reference")) or "GEN").lower(),
                raw={"data": data, "authors": authors, "tags": raw_tags},
                errors=errors,
                occurrences=occurrences,
            )
        )
    return candidates


def parse_bibliography(content: str, format: BibliographyFormat) -> list[BibliographyCandidate]:
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise BibliographyParseError("unsupported_encoding", "Use UTF-8 text for import.") from exc
    if "\ufffd" in content:
        raise BibliographyParseError(
            "unsupported_encoding", "Text contains replacement characters; save the file as UTF-8."
        )
    if len(encoded) > MAX_BYTES:
        raise BibliographyParseError("too_large", "Bibliography files are limited to 1 MiB.")
    if not content.strip():
        raise BibliographyParseError("empty_file", "Bibliography file is empty.")
    if format == "bibtex":
        candidates = _parse_bibtex(content)
    elif format == "ris":
        candidates = _parse_ris(content)
    else:
        raise BibliographyParseError("unsupported_format", "Use bibtex or ris.")
    if not candidates:
        raise BibliographyParseError("no_records", "No bibliography records were found.")
    return candidates


class BibliographyFileAdapter:
    def parse(self, content: str, format: BibliographyFormat) -> list[BibliographyCandidate]:
        return parse_bibliography(content, format)
