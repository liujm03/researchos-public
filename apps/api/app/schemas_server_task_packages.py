"""Owner-reviewed data packages; no local or remote research execution authority."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import PageMeta, TaskCategory, TaskPriority


class ServerPackageMaterialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100000)
    role: Literal["DEPENDENCIES", "CONFIG", "ENVIRONMENT", "DOCUMENTATION"]

    @field_validator("path")
    @classmethod
    def nonblank_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Material path must contain text")
        return value


class ServerPackageAssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["DATASET", "MODEL", "OTHER"]
    label: str = Field(min_length=1, max_length=240)
    location: str = Field(min_length=1, max_length=2000)
    version: str | None = Field(default=None, max_length=240)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    license_note: str | None = Field(default=None, max_length=2000)

    @field_validator("label", "location")
    @classmethod
    def nonblank_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Asset identity and location must contain text")
        return value


class ServerPackageExpectedArtifactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=2000)

    @field_validator("path", "description")
    @classmethod
    def nonblank_artifact(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Expected artifact must contain text")
        return value


class ServerPackageTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=320)
    description: str | None = Field(default=None, max_length=10000)
    category: TaskCategory = "research"
    priority: TaskPriority = "medium"

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Task title must contain text")
        return value


class ServerTaskPackageSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief_id: uuid.UUID
    archive_version_id: uuid.UUID | None = None
    label: str = Field(min_length=1, max_length=240)
    run_instructions: str | None = Field(default=None, max_length=50000)
    resource_limits: str | None = Field(default=None, max_length=10000)
    materials: list[ServerPackageMaterialCreate] = Field(default_factory=list, max_length=20)
    assets: list[ServerPackageAssetCreate] = Field(default_factory=list, max_length=30)
    expected_artifacts: list[ServerPackageExpectedArtifactCreate] = Field(
        default_factory=list, max_length=30
    )
    tasks: list[ServerPackageTaskCreate] = Field(default_factory=list, max_length=20)

    @field_validator("run_instructions", "resource_limits")
    @classmethod
    def unknown_if_blank(cls, value: str | None) -> str | None:
        return None if value is not None and not value.strip() else value

    @model_validator(mode="after")
    def unique_inputs(self) -> "ServerTaskPackageSelection":
        for values in (
            [item.path.casefold() for item in self.materials],
            [item.path.casefold() for item in self.expected_artifacts],
        ):
            if len(set(values)) != len(values):
                raise ValueError("Package paths must be unique")
        if not self.label.strip():
            raise ValueError("Package label must contain text")
        return self


class ServerPackageBriefOption(BaseModel):
    id: uuid.UUID
    revision: int
    idea: str
    sha256: str
    status: str
    context_current: bool
    eligible: bool


class ServerPackageArchiveOption(BaseModel):
    id: uuid.UUID
    tag: str
    commit_sha: str
    repository: str
    remote_verified_at: datetime | None


class ServerTaskPackageOptions(BaseModel):
    owner_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    briefs: list[ServerPackageBriefOption]
    archive_versions: list[ServerPackageArchiveOption]
    brief_page: PageMeta
    archive_page: PageMeta
    scope_note: str


class ServerPackageFileOut(BaseModel):
    path: str
    content: str
    role: str
    sha256: str
    size_bytes: int


class ServerTaskPackagePreviewOut(BaseModel):
    project_id: uuid.UUID
    project_name: str
    selection: ServerTaskPackageSelection
    source_sha256: str
    preview_sha256: str
    readiness: Literal["INCOMPLETE", "READY_FOR_SERVER_REVIEW"]
    gaps: list[str]
    files: list[ServerPackageFileOut]
    bundle_sha256: str
    bundle_size_bytes: int
    scope_note: str
    execution_authorized: Literal[False] = False
    delivery_status: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"


class ServerTaskPackageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: ServerTaskPackageSelection
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_package: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class ServerTaskPackageTaskOut(ServerPackageTaskCreate):
    task_id: uuid.UUID | None


class ServerTaskPackageRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_unknown_save: bool = False


class ServerPackageSaveAttemptOut(BaseModel):
    id: uuid.UUID
    attempt_number: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    owner_acknowledged_unknown: bool


class ServerTaskPackageSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    status: Literal["SAVING", "READY", "FAILED", "NEEDS_ATTENTION"]
    readiness: Literal["INCOMPLETE", "READY_FOR_SERVER_REVIEW"]
    preview_sha256: str
    bundle_sha256: str
    created_at: datetime
    completed_at: datetime | None
    attachment_id: uuid.UUID | None
    error_code: str | None
    error_message: str | None
    execution_authorized: Literal[False] = False
    delivery_status: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"


class ServerTaskPackageOut(ServerTaskPackageSummary):
    brief_id: uuid.UUID
    archive_version_id: uuid.UUID | None
    source_sha256: str
    bundle_size_bytes: int
    gaps: list[str]
    files: list[ServerPackageFileOut]
    assets: list[ServerPackageAssetCreate]
    expected_artifacts: list[ServerPackageExpectedArtifactCreate]
    tasks: list[ServerTaskPackageTaskOut]
    save_attempts: list[ServerPackageSaveAttemptOut]
    scope_note: str


class ServerTaskPackagePage(BaseModel):
    items: list[ServerTaskPackageSummary]
    page: PageMeta
