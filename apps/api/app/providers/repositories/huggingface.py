"""Public HF model/dataset/Space metadata; only the frozen README is read."""

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
    ensure_public,
    source_hash,
    strings,
    text,
    timestamp,
)

_SHA = re.compile(r"^[a-fA-F0-9]{40}(?:[a-fA-F0-9]{24})?$")
_PLURALS = {"model": "models", "dataset": "datasets", "space": "spaces"}
_EXPAND = ("id", "private", "sha", "author", "likes", "tags", "cardData", "lastModified", "createdAt")
_CARD_FIELDS = ("license", "license_name", "task_categories", "task_ids", "language", "tags", "datasets", "base_model", "model_name", "pretty_name")


class HuggingFaceRepositoryAdapter:
    provider_key = "huggingface"

    def __init__(self, *, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = OfficialRepositoryHTTP("huggingface.co", token=token, transport=transport)

    async def get_repository(self, reference: RepositoryRef) -> RepositoryCandidate:
        reference = normalize_repository_ref(reference.repo_id, provider_key=reference.provider_key, repo_kind=reference.repo_kind, revision=reference.revision)
        if reference.provider_key != self.provider_key or reference.repo_kind not in _PLURALS:
            raise DomainError("REPOSITORY_PROVIDER_MISMATCH", "HF adapter requires a model, dataset or Space repository", 422)
        plural = _PLURALS[reference.repo_kind]
        fields = _EXPAND + (("downloads", "gated", "pipeline_tag", "library_name") if reference.repo_kind == "model" else ("downloads", "gated") if reference.repo_kind == "dataset" else ())
        path = f"/api/{plural}/{quote(reference.repo_id, safe='/')}"
        if reference.revision:
            path += f"/revision/{quote(reference.revision, safe='')}"
        # Fetch the documented repository-info shape. `id` is a response field,
        # not a valid expand selector; unsupported selectors yield HTTP 400.
        metadata = await self._http.json(path)
        ensure_public(metadata)
        identifier = text(metadata.get("id")) or text(metadata.get("modelId"))
        if not identifier:
            raise DomainError("REPOSITORY_INVALID_RESPONSE", "HF metadata has no canonical repository identity", 502)
        try:
            canonical_ref = normalize_repository_ref(identifier, provider_key=self.provider_key, repo_kind=reference.repo_kind)
        except DomainError:
            raise DomainError("REPOSITORY_INVALID_RESPONSE", "HF returned an invalid canonical identity", 502) from None
        canonical = canonical_ref.repo_id
        warnings: list[str] = []
        if canonical != reference.repo_id:
            warnings.append("REPOSITORY_ID_CHANGED: official API resolved a renamed or transferred repository")
        commit = text(metadata.get("sha"))
        if commit is not None and not _SHA.fullmatch(commit):
            raise DomainError("REPOSITORY_INVALID_RESPONSE", "HF returned an invalid repository commit SHA", 502)
        commit = commit.lower() if commit else None
        if reference.revision and _SHA.fullmatch(reference.revision) and commit != reference.revision.lower():
            raise DomainError("REPOSITORY_REVISION_MISMATCH", "HF response does not match the requested commit", 502)
        gated = metadata.get("gated")
        if gated is not None and not (
            isinstance(gated, bool) or isinstance(gated, str) and gated in {"auto", "manual"}
        ):
            raise DomainError("REPOSITORY_INVALID_RESPONSE", "HF returned an invalid access-gating value", 502)
        if gated is True or isinstance(gated, str):
            warnings.append("GATED_REPOSITORY: only public metadata/card is imported; gated weights/data are not downloaded")
        prefix = "" if reference.repo_kind == "model" else f"/{plural}"
        if commit:
            readme, readme_hash, readme_warnings = await self._http.readme(f"{prefix}/{quote(canonical, safe='/')}/raw/{commit}/README.md")
            warnings.extend(readme_warnings)
        else:
            readme, readme_hash = None, None
            warnings.extend(("COMMIT_UNAVAILABLE: upstream did not report a frozen commit", "README_UNAVAILABLE: mutable card was not fetched without an immutable commit"))
        card = metadata.get("cardData")
        card_fields: dict[str, object] = {key: card[key] for key in _CARD_FIELDS if key in card} if isinstance(card, dict) else {}
        license_id = text(card_fields.get("license"))
        if not license_id or license_id.lower() in {"other", "unknown", "none"}:
            license_id = None
            warnings.append("LICENSE_UNKNOWN: upstream does not report one specific license identifier")
        pipeline_tag = text(metadata.get("pipeline_tag"))
        task_hints = tuple(dict.fromkeys(([pipeline_tag] if pipeline_tag is not None else []) + list(strings(card_fields.get("task_categories"))) + list(strings(card_fields.get("task_ids")))))
        raw = {key: metadata[key] for key in (*fields, "_id", "defaultBranch", "default_branch") if key in metadata and key != "cardData"}
        raw["cardData"] = card_fields or None
        return RepositoryCandidate(
            provider_key=self.provider_key, repo_kind=reference.repo_kind, repo_id=canonical,
            provider_id=text(metadata.get("_id")) or canonical, canonical_url=f"https://huggingface.co{prefix}/{canonical}",
            name=canonical.rsplit("/", 1)[-1], description=text(card_fields.get("pretty_name")) or text(card_fields.get("model_name")),
            license_id=license_id, default_branch=text(metadata.get("defaultBranch")) or text(metadata.get("default_branch")),
            commit_sha=commit, stars=None, downloads=count(metadata.get("downloads")), topics=strings(metadata.get("tags")), task_hints=task_hints,
            readme_text=readme, readme_sha256=readme_hash, source_hash=source_hash(self.provider_key, reference.repo_kind, canonical, commit, raw, readme_hash),
            fetched_at=datetime.now(UTC), updated_at=timestamp(metadata.get("lastModified")), warnings=tuple(warnings), raw_metadata=raw,
        )
