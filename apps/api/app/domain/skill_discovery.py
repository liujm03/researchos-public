"""Readonly skill candidates: discovery and hashes never imply an approved binding."""

from pathlib import Path
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ConnectionStatus = Literal["NOT_CONFIGURED", "READY", "DEGRADED", "UNAVAILABLE"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillDiscoveryRequest(Record):
    workspace_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")


class SkillDependencyOut(Record):
    type: str = Field(max_length=200)
    value: str = Field(max_length=2000)
    command: str | None = Field(default=None, max_length=2000)
    transport: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)


class SkillCandidateOut(Record):
    identity_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=320)
    path: str = Field(min_length=1, max_length=2000)
    scope: str = Field(max_length=80)
    plugin_id: str | None = Field(default=None, max_length=320)
    description: str = Field(max_length=20_000)
    enabled: bool
    discovered: Literal[True] = True
    file_verified: bool
    read_status: Literal[
        "FILE_VERIFIED",
        "OUTSIDE_ALLOWED_ROOT",
        "LINK_REJECTED",
        "NOT_FOUND",
        "TOO_LARGE",
        "INVALID_UTF8",
        "READ_ERROR",
    ]
    skill_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    skill_size_bytes: int | None = Field(default=None, ge=0, le=262144)
    declared_dependencies: list[SkillDependencyOut] = Field(default_factory=list, max_length=100)
    trust_review: Literal["UNREVIEWED"] = "UNREVIEWED"
    compatibility: Literal["UNREVIEWED"] = "UNREVIEWED"
    probe: Literal["NOT_RUN"] = "NOT_RUN"
    smoke_test: Literal["NOT_RUN"] = "NOT_RUN"
    ready_binding: Literal[False] = False


class SkillRuntimeErrorOut(Record):
    path: str = Field(max_length=2000)
    error_code: Literal["RUNTIME_SKILL_ERROR"] = "RUNTIME_SKILL_ERROR"


class SkillDiscoveryOut(Record):
    workspace_id: str
    provider_key: Literal["openai_codex_sdk"] = "openai_codex_sdk"
    sdk_version: str
    checked_at: AwareDatetime
    connection_checked_at: AwareDatetime
    connection_status: Literal["READY", "DEGRADED"]
    discovery_complete: bool
    discovery_scope: str
    roots_read_policy: Literal["EXPLICIT_ALLOWLIST"] = "EXPLICIT_ALLOWLIST"
    skills: list[SkillCandidateOut] = Field(max_length=2000)
    runtime_errors: list[SkillRuntimeErrorOut] = Field(default_factory=list, max_length=2000)
    limitations: list[str]
    ready_binding: Literal[False] = False


class SkillDiscoveryCapabilityOut(Record):
    implemented: Literal[True] = True
    enabled: bool
    runtime_installed: bool
    sdk_version: str | None
    supported_sdk_version: Literal["0.158.0"] = "0.158.0"
    configured_root_count: int
    workspace_ids: list[str]
    connection_status: ConnectionStatus | None
    connection_checked_at: AwareDatetime | None = None
    reason: str | None
    ready_binding: Literal[False] = False
    limitations: list[str]


class SkillDiscoveryProvider(Protocol):
    async def discover(
        self, workspace_id: str, cwd: Path, allowed_roots: tuple[Path, ...]
    ) -> SkillDiscoveryOut: ...
