"""Workspace policy and provider ports; no Codex vendor RPC in business logic."""

import json
import os
from pathlib import Path

from app.core.config import get_settings
from app.domain.skill_discovery import (
    SkillDiscoveryCapabilityOut,
    SkillDiscoveryOut,
    SkillDiscoveryRequest,
)
from app.errors import DomainError
from app.providers.registry import skill_discovery_capability, skill_discovery_provider
from app.services.codex_tasks import load_workspaces, workspace_by_id


def allowed_roots() -> tuple[Path, ...]:
    try:
        raw = json.loads(get_settings().skill_discovery_roots_json)
        if not isinstance(raw, list) or len(raw) > 32:
            raise ValueError("expected a bounded list")
        result = []
        for value in raw:
            if not isinstance(value, str) or not Path(value).is_absolute() or len(value) > 2000:
                raise ValueError("roots must be absolute paths")
            # Do not resolve through links here; the adapter rejects reparse components.
            path = Path(os.path.abspath(value))
            if path == Path(path.anchor):
                raise ValueError("whole-volume roots are not permitted")
            if path not in result:
                result.append(path)
        return tuple(result)
    except (ValueError, TypeError, OSError) as exc:
        raise DomainError(
            "SKILL_DISCOVERY_CONFIGURATION_INVALID",
            "Skill roots must be an explicit bounded JSON list of absolute directories",
            503,
        ) from exc


def capability() -> SkillDiscoveryCapabilityOut:
    settings = get_settings()
    sdk_version, installed, limitations = skill_discovery_capability()
    roots, workspaces = allowed_roots(), load_workspaces()
    if not settings.skill_discovery_enabled:
        status, reason = "NOT_CONFIGURED", "DISABLED"
    elif not workspaces:
        status, reason = "NOT_CONFIGURED", "NO_REGISTERED_WORKSPACE"
    elif not installed:
        status, reason = "UNAVAILABLE", "PINNED_RUNTIME_NOT_INSTALLED"
    else:
        status, reason = None, None
    return SkillDiscoveryCapabilityOut(
        enabled=settings.skill_discovery_enabled,
        runtime_installed=installed,
        sdk_version=sdk_version,
        configured_root_count=len(roots),
        workspace_ids=[workspace.id for workspace in workspaces],
        connection_status=status,
        reason=reason,
        limitations=limitations,
    )


async def discover(request: SkillDiscoveryRequest) -> SkillDiscoveryOut:
    if not get_settings().skill_discovery_enabled:
        raise DomainError(
            "SKILL_DISCOVERY_DISABLED", "Skill discovery is disabled in server configuration", 503
        )
    roots = allowed_roots()
    workspace = workspace_by_id(request.workspace_id)
    return await skill_discovery_provider().discover(workspace.id, workspace.path, roots)
