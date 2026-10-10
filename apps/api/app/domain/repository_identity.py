"""Normalize public repository identifiers; user URLs never become fetch targets."""

import re
from urllib.parse import unquote, urlsplit

from app.domain.repositories import RepositoryKind, RepositoryProviderKey, RepositoryRef
from app.errors import DomainError

_GITHUB_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_HF_PART = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}$")
_REVISION = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,199}$")


def _invalid(message: str = "Use a public GitHub or Hugging Face repository URL/ID") -> DomainError:
    return DomainError("REPOSITORY_INVALID_ID", message, 422)


def normalize_repository_ref(
    value: str,
    *,
    provider_key: RepositoryProviderKey | None = None,
    repo_kind: RepositoryKind | None = None,
    revision: str | None = None,
) -> RepositoryRef:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise _invalid()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _invalid()
    identifier = value.strip()
    if "\\" in identifier or "?" in identifier or "#" in identifier:
        raise _invalid("Repository inputs cannot contain credentials, queries or fragments")
    if provider_key not in {None, "github", "huggingface"}:
        raise DomainError("REPOSITORY_PROVIDER_UNSUPPORTED", "Repository provider is unsupported", 422)
    if repo_kind not in {None, "code", "model", "dataset", "space"}:
        raise DomainError("REPOSITORY_KIND_UNSUPPORTED", "Repository kind is unsupported", 422)
    if ":" in identifier or identifier.startswith("//"):
        try:
            parsed = urlsplit(identifier)
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            raise _invalid() from None
        if (
            parsed.scheme.lower() != "https"
            or host not in {"github.com", "huggingface.co"}
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or re.search(r"%(?![0-9a-fA-F]{2})", parsed.path)
        ):
            raise _invalid("Only credential-free official HTTPS repository URLs are accepted")
        try:
            path = unquote(parsed.path, errors="strict").strip("/")
        except UnicodeError:
            raise _invalid() from None
        inferred_provider: RepositoryProviderKey = "github" if host == "github.com" else "huggingface"
        inferred_kind: RepositoryKind = "code" if inferred_provider == "github" else "model"
        if inferred_provider == "github" and path.endswith(".git"):
            path = path[:-4]
        if inferred_provider == "huggingface":
            if path.startswith("datasets/"):
                inferred_kind, path = "dataset", path.removeprefix("datasets/")
            elif path.startswith("spaces/"):
                inferred_kind, path = "space", path.removeprefix("spaces/")
        if provider_key is not None and provider_key != inferred_provider:
            raise _invalid("Repository URL does not match the selected provider")
        if repo_kind is not None and repo_kind != inferred_kind:
            raise _invalid("Repository URL does not match the selected repository kind")
        provider_key, repo_kind, identifier = inferred_provider, inferred_kind, path
    if provider_key is None:
        raise DomainError("REPOSITORY_PROVIDER_REQUIRED", "Select a provider for a plain repository ID", 422)
    if provider_key == "github":
        if repo_kind not in {None, "code"}:
            raise DomainError("REPOSITORY_KIND_UNSUPPORTED", "GitHub imports support code repositories", 422)
        parts = identifier.split("/")
        if len(parts) != 2 or not _GITHUB_OWNER.fullmatch(parts[0]) or not _GITHUB_NAME.fullmatch(parts[1]) or parts[1] in {".", ".."}:
            raise _invalid("GitHub ID must identify one owner/repository")
        repo_kind, identifier = "code", identifier.casefold()
    else:
        if repo_kind == "code":
            raise DomainError("REPOSITORY_KIND_UNSUPPORTED", "Hugging Face imports support models, datasets and Spaces", 422)
        repo_kind = repo_kind or "model"
        parts = identifier.split("/")
        if len(parts) not in {1, 2} or (repo_kind == "space" and len(parts) != 2) or any(
            not _HF_PART.fullmatch(part) or ".." in part or "--" in part or part.endswith((".", "-", ".git")) for part in parts
        ):
            raise _invalid("Hugging Face ID must identify one repository, not a file or revision URL")
    if revision is not None:
        if not isinstance(revision, str) or not _REVISION.fullmatch(revision) or any(part in {"", ".", ".."} for part in revision.split("/")):
            raise _invalid("Use a branch, tag or commit as a separate revision without URL syntax")
    return RepositoryRef(provider_key, repo_kind, identifier, revision)

