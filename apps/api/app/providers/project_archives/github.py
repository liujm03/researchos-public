"""Fail-closed authenticated GitHub private repository identity and creation.

This adapter does not upload files, push Git refs, alter visibility, or grant permissions.
Only the official REST authority is used; redirects and upstream error text are discarded.
"""

import json
import re
from typing import Literal
from urllib.parse import quote

import httpx

from app.domain.github_archive import (
    CreatePrivateRepositoryResult,
    GitHubAccount,
    GitHubPrivateRepository,
    GitHubRefState,
)
from app.errors import DomainError

_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SHA = re.compile(r"^[a-fA-F0-9]{40}$")
_LIMIT = 256 * 1024


def _invalid() -> DomainError:
    return DomainError("PROJECT_ARCHIVE_INVALID_RESPONSE", "GitHub returned invalid archive identity evidence", 502)


def _positive_id(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise _invalid()
    return value


def _identity(owner: str, name: str | None = None) -> None:
    if not _LOGIN.fullmatch(owner) or "--" in owner:
        raise DomainError("PROJECT_ARCHIVE_IDENTITY_INVALID", "Invalid GitHub account identity", 422)
    if name is not None and (not _NAME.fullmatch(name) or name in {".", ".."}):
        raise DomainError("PROJECT_ARCHIVE_IDENTITY_INVALID", "Invalid GitHub repository name", 422)


def _decode(body: bytes) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(value: str) -> object:
        raise ValueError("nonfinite")

    try:
        result: object = json.loads(body, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _invalid() from None
    if not isinstance(result, dict):
        raise _invalid()
    return result


class GitHubProjectArchiveAdapter:
    provider_key = "github"

    def __init__(self, *, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if token is not None and (not token or len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            raise DomainError("PROJECT_ARCHIVE_CONFIGURATION_INVALID", "Invalid GitHub authentication configuration", 503)
        self._token = token
        self._transport = transport

    async def _request(self, method: Literal["GET", "POST"], path: str, *, payload: dict[str, object] | None = None) -> dict[str, object]:
        if not self._token:
            raise DomainError("PROJECT_ARCHIVE_AUTH_NOT_CONFIGURED", "Execution host GitHub authentication is not configured", 503)
        # All paths originate from validated local identities, never upstream URLs.
        if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
            raise DomainError("PROJECT_ARCHIVE_IDENTITY_INVALID", "Invalid GitHub API path", 422)
        headers = {
            "Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "ResearchOS/0.1",
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, read=30.0), follow_redirects=False,
                trust_env=False, transport=self._transport,
            ) as client:
                async with client.stream(method, f"https://api.github.com{path}", headers=headers, json=payload) as response:
                    status = response.status_code
                    if status in {301, 302, 303, 307, 308}:
                        raise DomainError("PROJECT_ARCHIVE_REDIRECT_REJECTED", "GitHub identity redirects require an explicit new binding", 502)
                    if status == 404:
                        raise DomainError("PROJECT_ARCHIVE_NOT_FOUND", "Private repository or ref was not found or is inaccessible", 404)
                    if status == 401:
                        raise DomainError("PROJECT_ARCHIVE_AUTH_FAILED", "GitHub execution host authentication failed", 403)
                    if status in {403, 429}:
                        raise DomainError("PROJECT_ARCHIVE_ACCESS_DENIED", "GitHub denied access or rate limited the operation", 403)
                    if status == 422:
                        raise DomainError("PROJECT_ARCHIVE_CREATE_REJECTED", "GitHub rejected repository creation; inspect the destination before retrying", 409)
                    empty_ref_candidate = status == 409 and method == "GET" and "/git/ref/" in path
                    if status != (201 if method == "POST" else 200) and not empty_ref_candidate:
                        raise DomainError("PROJECT_ARCHIVE_PROVIDER_UNAVAILABLE", "GitHub archive operation returned an unavailable response", 503)
                    declared = response.headers.get("content-length")
                    if declared is not None:
                        try:
                            size = int(declared)
                        except ValueError:
                            raise _invalid() from None
                        if size < 0 or size > _LIMIT:
                            raise DomainError("PROJECT_ARCHIVE_RESPONSE_TOO_LARGE", "GitHub response exceeds the archive byte limit", 502)
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > _LIMIT:
                            raise DomainError("PROJECT_ARCHIVE_RESPONSE_TOO_LARGE", "GitHub response exceeds the archive byte limit", 502)
                        content.extend(chunk)
                    decoded = _decode(bytes(content))
                    if empty_ref_candidate:
                        # Official empty Git repository response; an arbitrary 409
                        # must never be treated as permission to overwrite a ref.
                        if decoded.get("message") in {"Git Repository is empty.", "Git repository is empty."}:
                            raise DomainError("PROJECT_ARCHIVE_EMPTY_REPOSITORY", "Verified repository has no Git refs yet", 409)
                        raise DomainError("PROJECT_ARCHIVE_REF_CONFLICT", "GitHub ref inspection reported a conflict; no push authorized", 409)
                    return decoded
        except httpx.RequestError:
            raise DomainError("PROJECT_ARCHIVE_PROVIDER_UNAVAILABLE", "GitHub archive operation could not be confirmed", 503) from None

    async def inspect_authenticated_account(self, expected_login: str, expected_user_id: int) -> GitHubAccount:
        _identity(expected_login)
        _positive_id(expected_user_id)
        data = await self._request("GET", "/user")
        login, user_id = data.get("login"), _positive_id(data.get("id"))
        if not isinstance(login, str) or data.get("type") != "User":
            raise _invalid()
        _identity(login)
        if login.casefold() != expected_login.casefold() or user_id != expected_user_id:
            raise DomainError("PROJECT_ARCHIVE_ACCOUNT_CHANGED", "Execution host GitHub account differs from the approved account", 409)
        return GitHubAccount(login, user_id)

    def _repository(self, data: dict[str, object], owner: str, name: str, owner_id: int, repository_id: int | None) -> GitHubPrivateRepository:
        identifier = _positive_id(data.get("id"))
        upstream_owner = data.get("owner")
        permissions = data.get("permissions")
        if not isinstance(upstream_owner, dict) or not isinstance(permissions, dict):
            raise _invalid()
        login, actual_name = upstream_owner.get("login"), data.get("name")
        actual_owner_id = _positive_id(upstream_owner.get("id"))
        branch = data.get("default_branch")
        if not isinstance(login, str) or not isinstance(actual_name, str) or not isinstance(branch, str) or not branch or len(branch) > 255:
            raise _invalid()
        _identity(login, actual_name)
        if (
            login.casefold() != owner.casefold() or actual_owner_id != owner_id
            or actual_name.casefold() != name.casefold()
            or data.get("full_name") != f"{login}/{actual_name}"
            or upstream_owner.get("type") != "User"
            or (repository_id is not None and identifier != repository_id)
        ):
            raise DomainError("PROJECT_ARCHIVE_DESTINATION_CHANGED", "GitHub repository identity differs from the approved destination", 409)
        if data.get("private") is not True or data.get("visibility") != "private":
            raise DomainError("PROJECT_ARCHIVE_NOT_PRIVATE", "GitHub did not confirm private repository visibility", 409)
        if data.get("archived") is not False or data.get("disabled") is not False or permissions.get("push") is not True:
            raise DomainError("PROJECT_ARCHIVE_NOT_WRITABLE", "GitHub repository is archived, disabled, or lacks push permission", 403)
        return GitHubPrivateRepository(identifier, login, actual_owner_id, actual_name, branch, True)

    async def get_private_owned_repository(self, owner: str, name: str, *, expected_owner_id: int, expected_repository_id: int | None = None) -> GitHubPrivateRepository:
        _identity(owner, name)
        _positive_id(expected_owner_id)
        if expected_repository_id is not None:
            _positive_id(expected_repository_id)
        await self.inspect_authenticated_account(owner, expected_owner_id)
        data = await self._request("GET", f"/repos/{owner}/{name}")
        return self._repository(data, owner, name, expected_owner_id, expected_repository_id)

    async def create_private_repository(self, owner: str, name: str, *, expected_owner_id: int, description: str | None = None) -> CreatePrivateRepositoryResult:
        _identity(owner, name)
        if description is not None and (len(description) > 350 or any(ord(c) < 32 for c in description)):
            raise DomainError("PROJECT_ARCHIVE_DESCRIPTION_INVALID", "Repository description must be bounded plain text", 422)
        await self.inspect_authenticated_account(owner, expected_owner_id)
        path = f"/repos/{owner}/{name}"
        try:
            await self._request("GET", path)
        except DomainError as error:
            if error.code != "PROJECT_ARCHIVE_NOT_FOUND":
                raise
        else:
            raise DomainError("PROJECT_ARCHIVE_REPOSITORY_EXISTS", "Repository already exists; explicitly inspect and bind its ID", 409)
        payload: dict[str, object] = {
            "name": name, "private": True, "auto_init": False,
            "has_projects": False, "has_wiki": False,
        }
        if description is not None:
            payload["description"] = description
        unknown = False
        expected_id: int | None = None
        try:
            data = await self._request("POST", "/user/repos", payload=payload)
            expected_id = self._repository(data, owner, name, expected_owner_id, None).repository_id
        except DomainError as error:
            if error.code not in {
                "PROJECT_ARCHIVE_PROVIDER_UNAVAILABLE", "PROJECT_ARCHIVE_INVALID_RESPONSE",
                "PROJECT_ARCHIVE_RESPONSE_TOO_LARGE", "PROJECT_ARCHIVE_REDIRECT_REJECTED",
            }:
                raise
            unknown = True
        try:
            result = await self.get_private_owned_repository(owner, name, expected_owner_id=expected_owner_id, expected_repository_id=expected_id)
        except DomainError:
            # POST has happened: never describe a failed observation as proof of no creation.
            raise DomainError("PROJECT_ARCHIVE_CREATE_UNKNOWN", "Repository creation cannot be confirmed; inspect this exact destination before another create attempt", 409) from None
        return CreatePrivateRepositoryResult(result, unknown)

    async def inspect_ref(self, repository: GitHubPrivateRepository, ref: str) -> GitHubRefState | None:
        if (
            not ref.startswith(("heads/", "tags/")) or len(ref) > 255
            or any(ord(c) < 33 or ord(c) == 127 or c in "~^:?*[\\" for c in ref)
            or ".." in ref or "@{" in ref or "//" in ref
            or any(not part or part.startswith(".") or part.endswith((".", ".lock")) for part in ref.split("/"))
        ):
            raise DomainError("PROJECT_ARCHIVE_REF_INVALID", "Invalid exact Git branch or tag ref", 422)
        current = await self.get_private_owned_repository(
            repository.owner_login, repository.name, expected_owner_id=repository.owner_id,
            expected_repository_id=repository.repository_id,
        )
        try:
            data = await self._request("GET", f"/repos/{current.full_name}/git/ref/{quote(ref, safe='/')}")
        except DomainError as error:
            if error.code in {"PROJECT_ARCHIVE_NOT_FOUND", "PROJECT_ARCHIVE_EMPTY_REPOSITORY"}:
                return None
            raise
        obj = data.get("object")
        if not isinstance(obj, dict) or data.get("ref") != f"refs/{ref}":
            raise _invalid()
        sha, kind = obj.get("sha"), obj.get("type")
        if not isinstance(sha, str) or not _SHA.fullmatch(sha) or kind not in {"commit", "tag"}:
            raise _invalid()
        if ref.startswith("heads/") and kind != "commit":
            raise _invalid()
        return GitHubRefState(ref, sha.lower(), "tag" if kind == "tag" else "commit")
