"""Owner-scoped search across current ResearchOS entities.

PostgreSQL uses the fixed expressions indexed by ADR 0006. SQLite preview uses
literal substring matching against the same fields.
"""

import base64
import binascii
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.schemas import PageMeta, SearchHit, SearchPage

SearchKind = Literal["paper", "project", "task", "note", "codex_task", "idea", "claim"]
MAX_OFFSET = 10_000


@dataclass(frozen=True)
class _Source:
    kind: SearchKind
    table: str
    title_sql: str
    body_sql: str
    vector_sql: str | None
    parent_sql: str = "NULL"
    identifiers_sql: tuple[str, str] | None = None


SOURCES = (
    _Source(
        "claim",
        "research_claims",
        "research_claims.title",
        "research_claims.text || ' ' || coalesce((SELECT cr.conditions || ' ' || cr.limitations || ' ' || cr.evaluation_criteria FROM claim_revisions cr WHERE cr.claim_id=research_claims.id AND cr.user_id=research_claims.user_id AND cr.revision=research_claims.revision),'')",
        None,
        "research_claims.project_id",
    ),
    _Source(
        "idea",
        "research_ideas",
        "research_ideas.title",
        "research_ideas.content || ' ' || coalesce((SELECT coalesce(ir.problem,'') || ' ' || coalesce(ir.hypothesis,'') || ' ' || coalesce(ir.method,'') || ' ' || coalesce(ir.contribution,'') || ' ' || coalesce(ir.difficulty,'') || ' ' || coalesce(ir.novelty,'') || ' ' || coalesce(ir.feasibility,'') || ' ' || coalesce(ir.required_dataset,'') || ' ' || coalesce(ir.required_hardware,'') || ' ' || coalesce(ir.next_experiment,'') || ' ' || coalesce(ir.review_note,'') FROM idea_revisions ir WHERE ir.idea_id=research_ideas.id AND ir.user_id=research_ideas.user_id AND ir.revision=research_ideas.revision), '')",
        None,
    ),
    _Source(
        "paper",
        "papers",
        "papers.title",
        "coalesce(papers.abstract, '')",
        "to_tsvector('simple'::regconfig, coalesce(papers.title, '') || ' ' || coalesce(papers.abstract, ''))",
        identifiers_sql=("coalesce(papers.doi, '')", "coalesce(papers.arxiv_id, '')"),
    ),
    _Source(
        "project",
        "research_projects",
        "research_projects.name",
        "coalesce(research_projects.summary, '') || ' ' || coalesce(research_projects.problem, '') || ' ' || coalesce(research_projects.motivation, '') || ' ' || coalesce(research_projects.research_gap, '')",
        "to_tsvector('simple'::regconfig, coalesce(research_projects.name, '') || ' ' || coalesce(research_projects.summary, '') || ' ' || coalesce(research_projects.problem, '') || ' ' || coalesce(research_projects.motivation, '') || ' ' || coalesce(research_projects.research_gap, ''))",
    ),
    _Source(
        "task",
        "tasks",
        "tasks.title",
        "coalesce(tasks.description, '')",
        "to_tsvector('simple'::regconfig, coalesce(tasks.title, '') || ' ' || coalesce(tasks.description, ''))",
    ),
    _Source(
        "note",
        "paper_notes",
        "coalesce(paper_notes.title, '阅读笔记')",
        "paper_notes.body_markdown",
        "to_tsvector('simple'::regconfig, coalesce(paper_notes.title, '') || ' ' || coalesce(paper_notes.body_markdown, ''))",
        "paper_notes.paper_id",
    ),
    _Source(
        "codex_task",
        "codex_tasks",
        "codex_tasks.title",
        "codex_tasks.prompt",
        None,
    ),
)
SOURCE_BY_KIND = {source.kind: source for source in SOURCES}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fingerprint(query: str, kinds: tuple[SearchKind, ...]) -> str:
    material = json.dumps([query.casefold(), kinds], ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def _offset(cursor: str | None, fingerprint: str) -> int:
    if cursor is None:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        offset = payload["o"]
        if (
            payload.get("v") != 1
            or payload.get("f") != fingerprint
            or isinstance(offset, bool)
            or not isinstance(offset, int)
            or not 0 <= offset <= MAX_OFFSET
        ):
            raise ValueError("cursor mismatch")
        return int(offset)
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise DomainError("VALIDATION_ERROR", "Invalid search cursor", 422) from exc


def _cursor(offset: int, fingerprint: str) -> str:
    data = json.dumps({"v": 1, "f": fingerprint, "o": offset}, separators=(",", ":"))
    return base64.urlsafe_b64encode(data.encode("utf-8")).decode("ascii").rstrip("=")


def _snippet(body: str, query: str, tokens: list[str]) -> str | None:
    if not body.strip():
        return None
    lowered = body.lower()
    positions = [lowered.find(term.lower()) for term in [query, *tokens]]
    found = min((position for position in positions if position >= 0), default=0)
    start = max(0, found - 36)
    fragment = body[start : start + 180].strip()
    return ("…" if start else "") + fragment + ("…" if start + 180 < len(body) else "")


def _href(kind: SearchKind, row_id: uuid.UUID, parent_id: uuid.UUID | None) -> str:
    if kind == "claim":
        return f"/projects/{parent_id}/evidence?claim={row_id}"
    if kind == "idea":
        return f"/ideas/{row_id}"
    if kind == "paper":
        return f"/papers/{row_id}"
    if kind == "project":
        return f"/projects/{row_id}"
    if kind == "note":
        return f"/papers/{parent_id}"
    if kind == "codex_task":
        return f"/ai-tasks/{row_id}"
    return f"/tasks/{row_id}"


def _source_sql(
    source: _Source, *, postgresql: bool, token_count: int, literal_fallback: bool
) -> str:
    title = source.title_sql
    body = source.body_sql
    match_fields = (title, body, *(source.identifiers_sql or ()))
    literal_match = " AND ".join(
        "("
        + " OR ".join(
            f"lower({field}) LIKE lower(:token_{index}) ESCAPE '\\'" for field in match_fields
        )
        + ")"
        for index in range(token_count)
    )
    tsquery = "websearch_to_tsquery('simple'::regconfig, :query)"
    fts_match = f"{source.vector_sql} @@ {tsquery}" if postgresql and source.vector_sql else None
    predicate = (
        f"({fts_match} OR ({literal_match}))"
        if fts_match and literal_fallback
        else fts_match or literal_match
    )
    rank = f"ts_rank_cd({source.vector_sql}, {tsquery})" if fts_match else "0"
    score = (
        f"(CASE WHEN lower({title}) = lower(:query) THEN 100 ELSE 0 END + "
        f"CASE WHEN lower({title}) LIKE lower(:whole_like) ESCAPE '\\' THEN 20 ELSE 0 END + "
        f"CASE WHEN lower({body}) LIKE lower(:whole_like) ESCAPE '\\' THEN 3 ELSE 0 END + "
        f"({rank}) * 10)"
    )
    if source.identifiers_sql:
        doi, arxiv_id = source.identifiers_sql
        score = (
            f"({score} + CASE WHEN lower({doi}) = lower(:query) OR "
            f"lower({arxiv_id}) = lower(:query) THEN 90 ELSE 0 END + "
            f"CASE WHEN lower({doi}) LIKE lower(:whole_like) ESCAPE '\\' OR "
            f"lower({arxiv_id}) LIKE lower(:whole_like) ESCAPE '\\' THEN 30 ELSE 0 END)"
        )
        identifier_select = f"{doi} AS doi, {arxiv_id} AS arxiv_id"
    else:
        identifier_select = "NULL AS doi, NULL AS arxiv_id"
    return (
        f"SELECT {source.table}.id AS id, {title} AS title, {body} AS body, "
        f"{source.parent_sql} AS parent_id, {identifier_select}, {score} AS score "
        f"FROM {source.table} WHERE {source.table}.user_id = :owner_id AND ({predicate}) "
        "ORDER BY score DESC, id ASC LIMIT :candidate_limit"
    )


def search_all(
    db: Session,
    owner_id: uuid.UUID,
    query: str,
    *,
    types: str | None,
    limit: int,
    cursor: str | None,
) -> SearchPage:
    normalized = " ".join(query.strip().split())
    if len(normalized) < 2:
        raise DomainError("VALIDATION_ERROR", "Search query needs at least two characters", 422)
    if types is None:
        kinds = tuple(source.kind for source in SOURCES)
    else:
        requested = {part.strip() for part in types.split(",")}
        if not requested or "" in requested or requested - SOURCE_BY_KIND.keys():
            raise DomainError("VALIDATION_ERROR", "Unknown search type", 422)
        kinds = tuple(source.kind for source in SOURCES if source.kind in requested)
    fingerprint = _fingerprint(normalized, kinds)
    offset = _offset(cursor, fingerprint)
    if offset + limit > MAX_OFFSET:
        raise DomainError("VALIDATION_ERROR", "Search cursor exceeds result window", 422)
    tokens = normalized.split()
    params: dict[str, object] = {
        "owner_id": owner_id,
        "query": normalized,
        "whole_like": f"%{_escape_like(normalized)}%",
        "candidate_limit": offset + limit + 1,
    }
    params.update(
        {f"token_{index}": f"%{_escape_like(token)}%" for index, token in enumerate(tokens)}
    )
    postgresql = db.get_bind().dialect.name == "postgresql"
    literal_fallback = any(
        ord(char) > 127 or char in {"-", "_", "/", "+", ":", ".", "%", "\\"} for char in normalized
    )
    found: list[tuple[float, int, uuid.UUID, SearchHit]] = []
    for type_order, kind in enumerate(kinds):
        source = SOURCE_BY_KIND[kind]
        statement = text(
            _source_sql(
                source,
                postgresql=postgresql,
                token_count=len(tokens),
                literal_fallback=literal_fallback,
            )
        ).bindparams(bindparam("owner_id", type_=Uuid()))
        for row in db.execute(statement, params).mappings():
            row_id = uuid.UUID(str(row["id"]))
            parent_id = uuid.UUID(str(row["parent_id"])) if row["parent_id"] else None
            title = str(row["title"] or "")
            body = str(row["body"] or "")
            doi = str(row["doi"] or "")
            arxiv_id = str(row["arxiv_id"] or "")
            matched = [
                field
                for field, value in (
                    ("title", title),
                    ("body", body),
                    ("doi", doi),
                    ("arxiv_id", arxiv_id),
                )
                if value
                if any(token.casefold() in value.casefold() for token in tokens)
            ]
            identifier_snippet = (
                doi if "doi" in matched else arxiv_id if "arxiv_id" in matched else None
            )
            hit = SearchHit(
                type=kind,
                entity_id=row_id,
                title=title,
                href=_href(kind, row_id, parent_id),
                snippet=identifier_snippet or _snippet(body, normalized, tokens),
                matched_fields=matched or ["full_text"],
            )
            found.append((float(row["score"] or 0), type_order, row_id, hit))
    found.sort(key=lambda item: (-item[0], item[1], str(item[2])))
    selected = [item[3] for item in found[offset : offset + limit]]
    next_offset = offset + len(selected)
    return SearchPage(
        items=selected,
        page=PageMeta(
            limit=limit,
            next_cursor=_cursor(next_offset, fingerprint)
            if len(found) > next_offset and next_offset < MAX_OFFSET
            else None,
        ),
    )
