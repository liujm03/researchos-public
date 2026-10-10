"""Source-independent DOI and arXiv identities; URLs never become fetch targets."""

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from app.errors import DomainError

_DOI_LABEL = re.compile(r"^doi\s*:\s*", re.I)
_DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
_ARXIV = re.compile(
    r"^(?P<base>(?P<modern>\d{4})\.(?P<serial>\d{4,5})|"
    r"(?P<archive>[a-z][a-z-]*(?:\.[a-z][a-z-]*)?)/(?P<legacy>\d{7}))"
    r"(?:v(?P<version>[1-9]\d{0,9}))?$",
    re.I,
)
# Historic archives are fixed identifiers. New archives use the numeric scheme.
_LEGACY_ARCHIVES = frozenset(
    {
        "acc-phys",
        "adap-org",
        "alg-geom",
        "ao-sci",
        "astro-ph",
        "atom-ph",
        "chao-dyn",
        "chem-ph",
        "cmp-lg",
        "comp-gas",
        "cond-mat",
        "cs",
        "dg-ga",
        "funct-an",
        "gr-qc",
        "hep-ex",
        "hep-lat",
        "hep-ph",
        "hep-th",
        "math",
        "math-ph",
        "mtrl-th",
        "nlin",
        "nucl-ex",
        "nucl-th",
        "patt-sol",
        "physics",
        "plasm-ph",
        "q-alg",
        "q-bio",
        "quant-ph",
        "solv-int",
        "supr-con",
    }
)
_OPTIONAL_SUBJECT_ARCHIVES = frozenset({"math", "cs", "nlin", "q-bio"})


def extract_doi_name(value: str | None) -> str | None:
    if not value:
        return None
    token = value.strip()
    if token.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(token)
            if (
                parsed.netloc.lower() not in {"doi.org", "dx.doi.org"}
                or "?" in token
                or "#" in token
                or re.search(r"%(?![0-9a-fA-F]{2})", parsed.path)
            ):
                return None
            # Only a URL path carries percent encoding; a raw DOI name does not.
            token = unquote(parsed.path.removeprefix("/"), errors="strict")
            if any(ord(char) < 32 or ord(char) == 127 for char in token):
                return None
        except (ValueError, UnicodeDecodeError):
            return None
    else:
        # Common bibliographic label, conservatively not an encoded DOI URI.
        token = _DOI_LABEL.sub("", token)
    return token.strip() or None


def normalize_doi(value: str | None) -> str | None:
    name = extract_doi_name(value)
    return name.lower() if name is not None else None


def validate_doi(value: str) -> str:
    normalized = normalize_doi(value)
    return validate_doi_name(normalized or "")


def validate_doi_name(value: str) -> str:
    """A provider's DOI-name field is raw metadata, never a URL-encoded name."""
    normalized = value.strip().lower()
    if (
        not normalized
        or len(normalized) > 300
        or not _DOI.fullmatch(normalized)
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise DomainError("VALIDATION_ERROR", "Invalid DOI", 422)
    return normalized


@dataclass(frozen=True)
class ArxivIdentity:
    canonical_id: str
    version: int | None

    @property
    def query_id(self) -> str:
        return self.canonical_id + (f"v{self.version}" if self.version is not None else "")


def parse_arxiv_identity(value: str) -> ArxivIdentity:
    identifier = value.strip()
    if len(identifier) > 512 or any(ord(char) < 33 or ord(char) > 126 for char in identifier):
        raise DomainError("VALIDATION_ERROR", "Invalid arXiv ID", 422)
    if identifier.lower().startswith(("https://", "http://")):
        try:
            parsed = urlsplit(identifier)
        except ValueError as exc:
            raise DomainError("VALIDATION_ERROR", "Invalid arXiv article URL", 422) from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.netloc.lower() not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}
            or "?" in identifier
            or "#" in identifier
            or not parsed.path.startswith(("/abs/", "/pdf/"))
        ):
            raise DomainError("VALIDATION_ERROR", "Use an arXiv ID or official article URL", 422)
        identifier = parsed.path[5:]
        if parsed.path.startswith("/pdf/") and identifier.endswith(".pdf"):
            identifier = identifier[:-4]
    else:
        identifier = re.sub(r"^arxiv:", "", identifier, flags=re.I)
    match = _ARXIV.fullmatch(identifier)
    if match is None:
        raise DomainError("VALIDATION_ERROR", "Invalid arXiv ID", 422)
    version = int(match["version"]) if match["version"] else None
    if version is not None and version > 2_147_483_647:
        raise DomainError("VALIDATION_ERROR", "Invalid arXiv version", 422)
    if match["modern"]:
        date = int(match["modern"])
        month = date % 100
        if (
            not 1 <= month <= 12
            or date < 704
            or len(match["serial"]) != (4 if date <= 1412 else 5)
            or int(match["serial"]) == 0
        ):
            raise DomainError("VALIDATION_ERROR", "Invalid arXiv ID", 422)
        base = match["base"]
    else:
        legacy = match["legacy"]
        date = int(legacy[:4])
        year = date // 100
        full_year = 1900 + year if year >= 91 else 2000 + year
        if (
            not 1 <= date % 100 <= 12
            or not 199107 <= full_year * 100 + date % 100 <= 200703
            or int(legacy[4:]) == 0
        ):
            raise DomainError("VALIDATION_ERROR", "Invalid legacy arXiv ID", 422)
        archive_with_subject = match["archive"].lower()
        archive = archive_with_subject.split(".", 1)[0]
        if archive not in _LEGACY_ARCHIVES or (
            "." in archive_with_subject and archive not in _OPTIONAL_SUBJECT_ARCHIVES
        ):
            raise DomainError("VALIDATION_ERROR", "Invalid legacy arXiv archive", 422)
        # arXiv's preferred external ID omits old optional .SC classification.
        base = archive + "/" + legacy
    return ArxivIdentity(canonical_id=base, version=version)


def normalized_arxiv_id(value: str | None) -> str | None:
    """Tolerant legacy projection, preserving invalid raw values separately."""
    if not value:
        return None
    try:
        return parse_arxiv_identity(value).canonical_id
    except DomainError:
        return None
