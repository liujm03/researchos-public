"""Public GitHub metadata and frozen README through official REST GET endpoints."""

import re
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from app.domain.repositories import RepositoryCandidate, RepositoryRef
from app.domain.repository_identity import normalize_repository_ref
from app.errors import DomainError
from app.providers.repositories.http import (
    OfficialRepositoryHTTP,
    count,
    decode_json,
    ensure_public,
    source_hash,
    strings,
    text,
    timestamp,
)

_SHA = re.compile(r"^[a-fA-F0-9]{40}(?:[a-fA-F0-9]{24})?$")
_PUBLIC_FIELDS = ("id", "node_id", "name", "full_name", "description", "private", "visibility", "fork", "default_branch", "stargazers_count", "forks_count", "archived", "disabled", "topics", "language", "created_at", "updated_at", "pushed_at")


class GitHubRepositoryAdapter:
    provider_key = "github"

    def __init__(self, *, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = OfficialRepositoryHTTP("api.github.com", token=token, transport=transport, headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"})

    async def get_repository(self, reference: RepositoryRef) -> RepositoryCandidate:
        reference = normalize_repository_ref(reference.repo_id, provider_key=reference.provider_key, repo_kind=reference.repo_kind, revision=reference.revision)
        if reference.provider_key != self.provider_key:
            raise DomainError("REPOSITORY_PROVIDER_MISMATCH", "GitHub adapter requires a GitHub repository", 422)
        metadata = await self._http.json(f"/repos/{reference.repo_id}")
        ensure_public(metadata)
        canonical = text(metadata.get("full_name"))
        identifier = count(metadata.get("id"))
        if not canonical or identifier is None or identifier == 0:
            raise DomainError("REPOSITORY_INVALID_RESPONSE", "GitHub metadata has no valid repository identity", 502)
        try:
            canonical_ref = normalize_repository_ref(canonical, provider_key="github", repo_kind="code")
        except DomainError:
            raise DomainError("REPOSITORY_INVALID_RESPONSE", "GitHub returned an invalid canonical identity", 502) from None
        canonical = canonical_ref.repo_id
        warnings: list[str] = []
        if canonical != reference.repo_id:
            warnings.append("REPOSITORY_ID_CHANGED: official API resolved a renamed or transferred repository")
        branch = text(metadata.get("default_branch"))
        revision = reference.revision or branch
        commit: str | None = None
        if revision:
            try:
                body = await self._http.get(f"/repos/{canonical}/commits/{quote(revision, safe='')}", limit=16 * 1024, accept="application/vnd.github.sha")
                commit = text(decode_json(body).get("sha")) if body.lstrip().startswith(b"{") else body.decode("ascii").strip()
            except UnicodeError:
                raise DomainError("REPOSITORY_INVALID_RESPONSE", "GitHub returned an invalid commit", 502) from None
            except DomainError as error:
                if error.code != "REPOSITORY_NOT_FOUND" or reference.revision:
                    raise
                warnings.append("COMMIT_UNAVAILABLE: no default commit was found")
            if commit is not None and not _SHA.fullmatch(commit):
                raise DomainError("REPOSITORY_INVALID_RESPONSE", "GitHub returned an invalid commit SHA", 502)
        if commit:
            commit = commit.lower()
            if reference.revision and _SHA.fullmatch(reference.revision) and commit != reference.revision.lower():
                raise DomainError("REPOSITORY_REVISION_MISMATCH", "GitHub response does not match the requested commit", 502)
            readme, readme_hash, readme_warnings = await self._http.readme(f"/repos/{canonical}/readme?ref={commit}", accept="application/vnd.github.raw+json")
            warnings.extend(readme_warnings)
        else:
            readme, readme_hash = None, None
            warnings.append("README_UNAVAILABLE: no immutable commit is available; mutable README was not fetched")
            if not any(item.startswith("COMMIT_UNAVAILABLE") for item in warnings):
                warnings.append("COMMIT_UNAVAILABLE: no default branch or revision was reported")
        license_value = metadata.get("license")
        license_fields: dict[str, object] = {}
        if isinstance(license_value, dict):
            license_fields = {key: license_value[key] for key in ("key", "name", "spdx_id") if key in license_value}
        license_id = text(license_fields.get("spdx_id"))
        if license_id in {None, "NOASSERTION", "NONE"}:
            license_id = None
            warnings.append("LICENSE_UNKNOWN: upstream does not report a recognized license identifier")
        raw = {key: metadata[key] for key in _PUBLIC_FIELDS if key in metadata}
        raw["license"] = license_fields or None
        raw["resolved_commit_sha"] = commit
        return RepositoryCandidate(
            provider_key=self.provider_key, repo_kind="code", repo_id=canonical, provider_id=str(identifier),
            canonical_url=f"https://github.com/{canonical}", name=text(metadata.get("name")) or canonical.split("/")[-1],
            description=text(metadata.get("description")), license_id=license_id, default_branch=branch, commit_sha=commit,
            stars=count(metadata.get("stargazers_count")), downloads=None, topics=strings(metadata.get("topics")), task_hints=(),
            readme_text=readme, readme_sha256=readme_hash,
            source_hash=source_hash(self.provider_key, "code", canonical, commit, raw, readme_hash),
            fetched_at=datetime.now(UTC), updated_at=timestamp(metadata.get("updated_at")), warnings=tuple(warnings), raw_metadata=raw,
        )
