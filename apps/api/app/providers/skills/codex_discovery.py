"""Pinned native skills/list metadata RPC, never thread/turn or config writes."""

import asyncio
import hashlib
import json
import os
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from app.domain.skill_discovery import (
    SkillCandidateOut,
    SkillDependencyOut,
    SkillDiscoveryOut,
    SkillRuntimeErrorOut,
)
from app.errors import DomainError
from app.providers.ai.codex_runtime import BASE_OVERRIDES, mcp_overrides, verify_config
from app.providers.codex.openai_codex_sdk import _runtime_executable

SUPPORTED_SDK = "0.158.0"
MAX_SKILL_BYTES = 262_144
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 2000
DISCOVERY_OVERRIDES = tuple(
    row for row in BASE_OVERRIDES if not row.startswith("features.skip_host_skill_discovery=")
) + ("features.skip_host_skill_discovery=false",)
LIMITATIONS = [
    "Only the registered workspace's native skills/list discovery scope is queried; no whole-machine scan.",
    "Plugins, remote plugins, apps, hooks, MCP and execution features are disabled in this discovery session. Plugin skill discovery may be incomplete; absence does not prove a plugin is uninstalled.",
    "Only explicitly allowlisted SKILL.md files are hashed. Referenced scripts, templates and dependencies are not read or executed.",
    "Discovery, enabled state and a main-file hash do not establish trust, compatibility, available tools or a READY binding.",
]
ReadStatus = Literal[
    "FILE_VERIFIED",
    "OUTSIDE_ALLOWED_ROOT",
    "LINK_REJECTED",
    "NOT_FOUND",
    "TOO_LARGE",
    "INVALID_UTF8",
    "READ_ERROR",
]


def installed_sdk_version() -> str | None:
    try:
        return version("openai-codex")
    except PackageNotFoundError:
        return None


def runtime_installed() -> bool:
    executable = _runtime_executable()
    return (
        installed_sdk_version() == SUPPORTED_SDK
        and executable is not None
        and Path(executable).is_file()
    )


def _linked_component(path: Path) -> bool:
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return True
    return False


def verify_skill_file(
    path_text: str, roots: tuple[Path, ...]
) -> tuple[ReadStatus, str | None, int | None]:
    """Bounded main-file-only read, preserving raw byte hash and rejecting links."""
    path = Path(path_text)
    if not path.is_absolute() or path.name != "SKILL.md":
        return "OUTSIDE_ALLOWED_ROOT", None, None
    path = Path(os.path.abspath(path))
    if not any(path.is_relative_to(root) for root in roots):
        return "OUTSIDE_ALLOWED_ROOT", None, None
    try:
        if _linked_component(path):
            return "LINK_REJECTED", None, None
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            return "READ_ERROR", None, None
        if before.st_size > MAX_SKILL_BYTES:
            return "TOO_LARGE", None, None
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        )
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                return "READ_ERROR", None, None
            content = handle.read(MAX_SKILL_BYTES + 1)
            after = os.fstat(handle.fileno())
        if len(content) > MAX_SKILL_BYTES:
            return "TOO_LARGE", None, None
        if _linked_component(path) or (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            return "READ_ERROR", None, None
        content.decode("utf-8")
        return "FILE_VERIFIED", hashlib.sha256(content).hexdigest(), len(content)
    except FileNotFoundError:
        return "NOT_FOUND", None, None
    except UnicodeError:
        return "INVALID_UTF8", None, None
    except OSError:
        return "READ_ERROR", None, None


def _verified_discovery_config(config: dict[str, object]) -> None:
    verify_config(config)
    features = config.get("features")
    if not isinstance(features, dict) or features.get("skip_host_skill_discovery") is not False:
        raise DomainError(
            "SKILL_DISCOVERY_ISOLATION_UNVERIFIED", "Discovery restrictions were not verified", 503
        )


def map_response(
    raw: object, workspace_id: str, cwd: Path, roots: tuple[Path, ...], sdk_version: str
) -> SkillDiscoveryOut:
    """Reject malformed/oversized metadata before reading any candidate file."""
    from openai_codex.generated.v2_all import SkillsListResponse

    try:
        response = (
            raw if isinstance(raw, SkillsListResponse) else SkillsListResponse.model_validate(raw)
        )
        if len(response.data) != 1 or os.path.normcase(
            os.path.abspath(response.data[0].cwd)
        ) != os.path.normcase(os.path.abspath(cwd)):
            raise ValueError("unexpected cwd scope")
        entry = response.data[0]
        if (
            len(entry.skills) + len(entry.errors) > MAX_RECORDS
            or len(response.model_dump_json().encode()) > MAX_RESPONSE_BYTES
        ):
            raise ValueError("response too large")
        rows: list[SkillCandidateOut] = []
        # Validate all metadata lengths before any filesystem access.
        for skill in entry.skills:
            identity = {
                "name": skill.name,
                "path": str(skill.path.root),
                "scope": skill.scope.value,
                "plugin_id": skill.plugin_id,
            }
            dependencies = (
                []
                if skill.dependencies is None
                else [
                    SkillDependencyOut.model_validate(tool.model_dump(mode="json"))
                    for tool in skill.dependencies.tools
                ]
            )
            rows.append(
                SkillCandidateOut(
                    identity_sha256=hashlib.sha256(
                        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest(),
                    **identity,
                    description=skill.description,
                    enabled=skill.enabled,
                    file_verified=False,
                    read_status="OUTSIDE_ALLOWED_ROOT",
                    declared_dependencies=dependencies,
                )
            )
        errors = [SkillRuntimeErrorOut(path=error.path) for error in entry.errors]
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        raise DomainError(
            "SKILL_DISCOVERY_RESPONSE_INVALID",
            "Codex returned malformed, oversized or unexpected skill metadata",
            503,
        ) from exc
    for row in rows:
        status, digest, size = verify_skill_file(row.path, roots)
        row.read_status = status
        row.file_verified = status == "FILE_VERIFIED"
        row.skill_sha256 = digest
        row.skill_size_bytes = size
    now = datetime.now(UTC)
    return SkillDiscoveryOut(
        workspace_id=workspace_id,
        sdk_version=sdk_version,
        checked_at=now,
        connection_checked_at=now,
        connection_status="DEGRADED" if errors else "READY",
        discovery_complete=not errors,
        discovery_scope="Native skills/list for one registered cwd with host skill discovery enabled and plugins disabled",
        skills=rows,
        runtime_errors=errors,
        limitations=LIMITATIONS,
    )


class CodexSkillDiscoveryProvider:
    def __init__(self, timeout_seconds: float = 30) -> None:
        self.timeout_seconds = timeout_seconds

    async def discover(
        self, workspace_id: str, cwd: Path, allowed_roots: tuple[Path, ...]
    ) -> SkillDiscoveryOut:
        sdk_version = installed_sdk_version()
        if sdk_version != SUPPORTED_SDK or _runtime_executable() is None:
            raise DomainError(
                "SKILL_DISCOVERY_RUNTIME_UNAVAILABLE",
                "Pinned Codex SDK/runtime is unavailable",
                503,
            )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._query(workspace_id, cwd, allowed_roots, sdk_version)
        except TimeoutError as exc:
            raise DomainError(
                "SKILL_DISCOVERY_TIMEOUT",
                "Codex skill discovery timed out; no inference was started",
                503,
            ) from exc
        except DomainError:
            raise
        except Exception as exc:
            # Raw SDK errors/config content may include sensitive host details.
            raise DomainError(
                "SKILL_DISCOVERY_RPC_FAILED",
                "Codex skill discovery failed; no inference was started",
                503,
            ) from exc

    async def _query(
        self, workspace_id: str, cwd: Path, roots: tuple[Path, ...], sdk_version: str
    ) -> SkillDiscoveryOut:
        from openai_codex import CodexConfig
        from openai_codex.generated.v2_all import (
            ConfigReadResponse,
            SkillsListParams,
            SkillsListResponse,
        )
        from openai_codex.models import JsonObject

        executable = _runtime_executable()
        async with _metadata_session(
            CodexConfig(codex_bin=executable, cwd=str(cwd), config_overrides=DISCOVERY_OVERRIDES)
        ) as inspection:
            observed = await inspection._client.request(
                "config/read",
                {"includeLayers": False, "cwd": str(cwd)},
                response_model=ConfigReadResponse,
            )
            overrides = DISCOVERY_OVERRIDES + mcp_overrides(
                cast(dict[str, object], observed.config.model_dump(mode="json"))
            )
        async with _metadata_session(
            CodexConfig(codex_bin=executable, cwd=str(cwd), config_overrides=overrides)
        ) as runtime:
            observed = await runtime._client.request(
                "config/read",
                {"includeLayers": False, "cwd": str(cwd)},
                response_model=ConfigReadResponse,
            )
            try:
                _verified_discovery_config(
                    cast(dict[str, object], observed.config.model_dump(mode="json"))
                )
            except DomainError as exc:
                raise DomainError(
                    "SKILL_DISCOVERY_ISOLATION_UNVERIFIED",
                    "Discovery restrictions were not verified",
                    503,
                ) from exc
            params = SkillsListParams(cwds=[str(cwd)], force_reload=True)
            response = await runtime._client.request(
                "skills/list",
                cast(JsonObject, params.model_dump(mode="json", by_alias=True, exclude_none=True)),
                response_model=SkillsListResponse,
            )
        return map_response(response, workspace_id, cwd, roots, sdk_version)


@asynccontextmanager
async def _metadata_session(config: Any) -> AsyncIterator[Any]:
    from openai_codex import AsyncCodex

    manager = AsyncCodex(config)
    try:
        runtime = await manager.__aenter__()
        yield runtime
    finally:
        # Ordinary async-with does not call __aexit__ when initialization fails.
        # Close the already-created SDK process on initialization timeout/error too.
        await manager.__aexit__(None, None, None)
