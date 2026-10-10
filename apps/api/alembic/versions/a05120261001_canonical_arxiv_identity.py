"""Preserve raw arXiv values and add unique canonical owner identity.

Revision ID: a05120261001
Revises: a05020260930
"""

import re
from urllib.parse import unquote, urlsplit

import sqlalchemy as sa

from alembic import context, op

revision = "a05120261001"
down_revision = "a05020260930"
branch_labels = None
depends_on = None

# Frozen migration normalizer; future application changes must not change history.
_PATTERN = re.compile(r"^(?P<base>(?P<modern>\d{4})\.(?P<serial>\d{4,5})|(?P<archive>[a-z][a-z-]*(?:\.[a-z][a-z-]*)?)/(?P<legacy>\d{7}))(?:v(?P<version>[1-9]\d{0,9}))?$", re.I)
_LEGACY_ARCHIVES = frozenset({"acc-phys", "adap-org", "alg-geom", "ao-sci", "astro-ph", "atom-ph", "chao-dyn", "chem-ph", "cmp-lg", "comp-gas", "cond-mat", "cs", "dg-ga", "funct-an", "gr-qc", "hep-ex", "hep-lat", "hep-ph", "hep-th", "math", "math-ph", "mtrl-th", "nlin", "nucl-ex", "nucl-th", "patt-sol", "physics", "plasm-ph", "q-alg", "q-bio", "quant-ph", "solv-int", "supr-con"})
_OPTIONAL_SUBJECT_ARCHIVES = frozenset({"math", "cs", "nlin", "q-bio"})


def _canonical(value: str | None) -> str | None:
    if not value:
        return None
    identifier = value.strip()
    if len(identifier) > 512 or any(ord(char) < 33 or ord(char) > 126 for char in identifier):
        return None
    if identifier.lower().startswith(("https://", "http://")):
        try:
            parsed = urlsplit(identifier)
        except ValueError:
            return None
        if parsed.netloc.lower() not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"} or "?" in identifier or "#" in identifier or not parsed.path.startswith(("/abs/", "/pdf/")):
            return None
        identifier = parsed.path[5:]
        if parsed.path.startswith("/pdf/") and identifier.endswith(".pdf"):
            identifier = identifier[:-4]
    else:
        identifier = re.sub(r"^arxiv:", "", identifier, flags=re.I)
    match = _PATTERN.fullmatch(identifier)
    if match is None or (match["version"] and int(match["version"]) > 2_147_483_647):
        return None
    if match["modern"]:
        date = int(match["modern"])
        if not 1 <= date % 100 <= 12 or date < 704 or len(match["serial"]) != (4 if date <= 1412 else 5) or int(match["serial"]) == 0:
            return None
        return match["base"]
    legacy = match["legacy"]
    date = int(legacy[:4])
    year = date // 100
    full_year = 1900 + year if year >= 91 else 2000 + year
    if not 1 <= date % 100 <= 12 or not 199107 <= full_year * 100 + date % 100 <= 200703 or int(legacy[4:]) == 0:
        return None
    archive_with_subject = match["archive"].lower()
    archive = archive_with_subject.split(".", 1)[0]
    if archive not in _LEGACY_ARCHIVES or ("." in archive_with_subject and archive not in _OPTIONAL_SUBJECT_ARCHIVES):
        return None
    return archive + "/" + legacy


def _canonical_doi(value: str | None) -> str | None:
    if not value:
        return None
    token = value.strip()
    if token.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(token)
            if parsed.netloc.lower() not in {"doi.org", "dx.doi.org"} or "?" in token or "#" in token or re.search(r"%(?![0-9a-fA-F]{2})", parsed.path):
                return None
            token = unquote(parsed.path.removeprefix("/"), errors="strict")
            if any(ord(char) < 32 or ord(char) == 127 for char in token):
                return None
        except (ValueError, UnicodeDecodeError):
            return None
    else:
        token = re.sub(r"^doi\s*:\s*", "", token, flags=re.I)
    return token.strip().lower() or None


_PG_ARXIV_CTE = r"""
WITH raw AS (
    SELECT id, regexp_replace(arxiv_id, '^[[:space:]]+|[[:space:]]+$', '', 'g') AS raw_id
    FROM papers WHERE arxiv_id IS NOT NULL
), tokens AS (
    SELECT id, CASE
        WHEN raw_id ~* '^https?://(www\.|export\.)?arxiv\.org/(abs|pdf)/[^?#]+$'
            AND regexp_replace(raw_id, '^https?://[^/]+', '', 'i') ~ '^/(abs|pdf)/[^?#]+$'
        THEN regexp_replace(
            regexp_replace(raw_id, '^https?://(www\.|export\.)?arxiv\.org/(abs|pdf)/', '', 'i'),
            CASE WHEN regexp_replace(raw_id, '^https?://[^/]+', '', 'i') ~ '^/pdf/' THEN '\.pdf$' ELSE '$a' END, '', 'g'
        )
        ELSE regexp_replace(raw_id, '^arxiv:', '', 'i')
    END AS token FROM raw
), identities AS (
    SELECT id, token, regexp_replace(token, 'v[1-9][0-9]{0,9}$', '', 'i') AS base_id,
        substring(token FROM '(?i)v([1-9][0-9]{0,9})$') AS version
    FROM tokens
), valid AS (
    SELECT id, base_id FROM identities
    WHERE (version IS NULL OR version::bigint <= 2147483647) AND CASE
        WHEN base_id ~ '^[0-9]{4}\.[0-9]{4,5}$' THEN
            substring(base_id, 1, 4)::integer >= 704
            AND substring(base_id, 3, 2)::integer BETWEEN 1 AND 12
            AND substring(base_id, 6)::integer > 0
            AND length(substring(base_id, 6)) = CASE WHEN substring(base_id, 1, 4)::integer <= 1412 THEN 4 ELSE 5 END
        WHEN base_id ~* '^[a-z][a-z-]*(\.[a-z][a-z-]*)?/[0-9]{7}$' THEN
            lower(split_part(split_part(base_id, '/', 1), '.', 1)) IN (
                'acc-phys','adap-org','alg-geom','ao-sci','astro-ph','atom-ph','chao-dyn',
                'chem-ph','cmp-lg','comp-gas','cond-mat','cs','dg-ga','funct-an','gr-qc',
                'hep-ex','hep-lat','hep-ph','hep-th','math','math-ph','mtrl-th','nlin',
                'nucl-ex','nucl-th','patt-sol','physics','plasm-ph','q-alg','q-bio',
                'quant-ph','solv-int','supr-con'
            )
            AND (position('.' IN split_part(base_id, '/', 1)) = 0 OR
                lower(split_part(split_part(base_id, '/', 1), '.', 1)) IN ('math','cs','nlin','q-bio'))
            AND substring(split_part(base_id, '/', 2), 3, 2)::integer BETWEEN 1 AND 12
            AND substring(split_part(base_id, '/', 2), 5, 3)::integer > 0
            AND (CASE WHEN substring(split_part(base_id, '/', 2), 1, 2)::integer >= 91 THEN 190000 ELSE 200000 END
                + substring(split_part(base_id, '/', 2), 1, 4)::integer) BETWEEN 199107 AND 200703
        ELSE false END
), canonical AS (
    SELECT id, CASE WHEN base_id ~* '^(math|cs|nlin|q-bio)\.' THEN
        lower(split_part(base_id, '.', 1)) || '/' || split_part(base_id, '/', 2)
        ELSE lower(base_id) END AS canonical_id FROM valid
)
"""
_PG_BACKFILL = _PG_ARXIV_CTE + "UPDATE papers AS paper SET normalized_arxiv_id = canonical.canonical_id FROM canonical WHERE paper.id = canonical.id;"

_PG_ARXIV_PREFLIGHT = "DO $arxiv_preflight$ DECLARE conflicting_ids text; BEGIN " + _PG_ARXIV_CTE + r"""
SELECT string_agg(paper.id::text, ', ') INTO conflicting_ids FROM canonical
JOIN papers AS paper ON paper.id = canonical.id
GROUP BY paper.user_id, canonical.canonical_id HAVING COUNT(*) > 1 LIMIT 1;
IF conflicting_ids IS NOT NULL THEN
    RAISE EXCEPTION USING MESSAGE = 'Canonical arXiv identity conflict for papers: ' || conflicting_ids || '. Resolve records before upgrading; no records were merged.';
END IF; END $arxiv_preflight$;
"""

_PG_DOI_PREPARE = r"""
CREATE TEMP TABLE researchos_doi_identity_map (id uuid PRIMARY KEY, user_id uuid, canonical_doi text) ON COMMIT DROP;
CREATE FUNCTION pg_temp.researchos_canonical_doi(raw_doi text) RETURNS text LANGUAGE plpgsql AS $doi_normalizer$
DECLARE token text; decoded bytea := ''::bytea; index_ integer := 1; char_ text;
BEGIN
    IF raw_doi IS NULL THEN RETURN NULL; END IF;
    token := regexp_replace(raw_doi, '^[[:space:]]+|[[:space:]]+$', '', 'g');
    IF token ~* '^https?://' THEN
        IF token !~* '^https?://(dx\.)?doi\.org/[^?#]*$' THEN RETURN NULL; END IF;
        token := regexp_replace(token, '^https?://(dx\.)?doi\.org/', '', 'i');
        WHILE index_ <= char_length(token) LOOP
            char_ := substring(token, index_, 1);
            IF char_ = chr(37) THEN
                IF substring(token, index_, 3) !~ ('^' || chr(37) || '[0-9A-Fa-f]{2}$') THEN RETURN NULL; END IF;
                decoded := decoded || decode(substring(token, index_ + 1, 2), 'hex');
                index_ := index_ + 3;
            ELSE
                decoded := decoded || convert_to(char_, 'UTF8');
                index_ := index_ + 1;
            END IF;
        END LOOP;
        BEGIN token := convert_from(decoded, 'UTF8');
        EXCEPTION WHEN character_not_in_repertoire OR untranslatable_character THEN RETURN NULL; END;
        IF token ~ '[[:cntrl:]]' THEN RETURN NULL; END IF;
    ELSE
        token := regexp_replace(token, '^doi[[:space:]]*:[[:space:]]*', '', 'i');
    END IF;
    RETURN NULLIF(lower(regexp_replace(token, '^[[:space:]]+|[[:space:]]+$', '', 'g')), '');
END $doi_normalizer$;
INSERT INTO researchos_doi_identity_map (id, user_id, canonical_doi)
SELECT id, user_id, CASE WHEN doi IS NULL THEN normalized_doi ELSE pg_temp.researchos_canonical_doi(doi) END FROM papers;
DO $doi_preflight$ DECLARE conflicting_ids text; BEGIN
    SELECT string_agg(id::text, ', ') INTO conflicting_ids FROM researchos_doi_identity_map
    WHERE canonical_doi IS NOT NULL GROUP BY user_id, canonical_doi HAVING COUNT(*) > 1 LIMIT 1;
    IF conflicting_ids IS NOT NULL THEN
        RAISE EXCEPTION USING MESSAGE = 'Canonical DOI identity conflict for papers: ' || conflicting_ids || '. Resolve records before upgrading; no records were merged.';
    END IF;
END $doi_preflight$;
"""
_PG_DOI_BACKFILL = """
UPDATE papers SET normalized_doi = NULL;
UPDATE papers AS paper SET normalized_doi = identities.canonical_doi FROM researchos_doi_identity_map AS identities WHERE paper.id = identities.id;
DROP FUNCTION pg_temp.researchos_canonical_doi(text);
"""


def upgrade() -> None:
    rows: list[tuple[object, str]] = []
    doi_rows: list[tuple[object, str | None]] = []
    if not context.is_offline_mode():
        # Validate before DDL, including non-transactional SQLite migrations.
        seen: dict[tuple[object, str], object] = {}
        seen_doi: dict[tuple[object, str], object] = {}
        for paper_id, user_id, raw_id, raw_doi, old_doi in op.get_bind().execute(sa.text("SELECT id, user_id, arxiv_id, doi, normalized_doi FROM papers")):
            canonical_doi = _canonical_doi(raw_doi) if raw_doi is not None else old_doi
            if canonical_doi is not None:
                doi_key = (user_id, canonical_doi)
                if doi_key in seen_doi:
                    raise RuntimeError(f"Canonical DOI identity conflict: paper {seen_doi[doi_key]} and {paper_id}. Resolve owner records before upgrading; no records were merged.")
                seen_doi[doi_key] = paper_id
            doi_rows.append((paper_id, canonical_doi))
            canonical = _canonical(raw_id)
            if canonical is None:
                continue
            key = (user_id, canonical)
            if key in seen:
                raise RuntimeError(f"Canonical arXiv identity conflict: paper {seen[key]} and {paper_id}. Resolve owner records before upgrading; no records were merged.")
            seen[key] = paper_id
            rows.append((paper_id, canonical))
    elif op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Canonical arXiv backfill requires online SQLite or PostgreSQL SQL mode")
    else:
        op.execute(_PG_ARXIV_PREFLIGHT)
        op.execute(_PG_DOI_PREPARE)
    op.add_column("papers", sa.Column("normalized_arxiv_id", sa.String(length=100), nullable=True))
    if context.is_offline_mode():
        op.execute(_PG_BACKFILL)
        op.execute(_PG_DOI_BACKFILL)
    else:
        for paper_id, canonical in rows:
            op.get_bind().execute(sa.text("UPDATE papers SET normalized_arxiv_id = :canonical WHERE id = :paper_id"), {"canonical": canonical, "paper_id": paper_id})
        # Apply the preflighted final mapping without transient unique-index collisions.
        op.get_bind().execute(sa.text("UPDATE papers SET normalized_doi = NULL"))
        for paper_id, canonical_doi in doi_rows:
            op.get_bind().execute(sa.text("UPDATE papers SET normalized_doi = :canonical WHERE id = :paper_id"), {"canonical": canonical_doi, "paper_id": paper_id})
    op.create_index("ix_papers_user_normalized_arxiv", "papers", ["user_id", "normalized_arxiv_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_papers_user_normalized_arxiv", table_name="papers")
    op.drop_column("papers", "normalized_arxiv_id")
