"""Immutable baseline declarations and readonly material evidence, never execution grants."""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import PageMeta

AssetRole = Literal[
    "CODE", "CONFIG", "ENVIRONMENT_LOCK", "EVALUATOR", "WEIGHTS", "DATA", "SPLIT_MANIFEST"
]


class BaselineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=240)
    purpose: str | None = Field(default=None, max_length=20000)


class BaselineAssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: AssetRole
    source_file_id: uuid.UUID
    dataset_version_id: uuid.UUID | None = None


class BaselineDatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_version_id: uuid.UUID
    license_confirmation: str = Field(min_length=1, max_length=4000)
    usage_scope: str = Field(min_length=1, max_length=4000)


class BaselineVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=120)
    parent_version_id: uuid.UUID | None = None
    expected_parent_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    model_version_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None
    weight_mode: Literal["PRETRAINED", "FROM_SCRATCH"]
    purpose: str | None = Field(default=None, max_length=20000)
    notes: str | None = Field(default=None, max_length=40000)
    assets: list[BaselineAssetCreate] = Field(default_factory=list, max_length=1000)
    datasets: list[BaselineDatasetCreate] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def parent_pair(self) -> Self:
        if (self.parent_version_id is None) != (self.expected_parent_sha256 is None):
            raise ValueError("parent version and expected hash are required together")
        if len(
            {(item.role, item.source_file_id, item.dataset_version_id) for item in self.assets}
        ) != len(self.assets):
            raise ValueError("duplicate asset declaration")
        if len({item.dataset_version_id for item in self.datasets}) != len(self.datasets):
            raise ValueError("duplicate dataset version")
        return self


class BaselineMaterialCheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class BaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    purpose: str | None
    created_at: datetime


class BaselineAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: AssetRole
    dataset_version_id: uuid.UUID | None
    source_file_id: uuid.UUID
    source_job_id: uuid.UUID
    source_plan_id: uuid.UUID
    file_key_sha256: str
    attachment_id: uuid.UUID
    path: str
    sha256: str
    size_bytes: int
    commit_sha: str
    source_plan_sha256: str
    source_receipt_sha256: str
    source_status: Literal["MATERIALIZED", "PARTIAL"]
    source_gaps: list[str]


class BaselineDatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dataset_id: uuid.UUID
    dataset_version_id: uuid.UUID
    dataset_name: str
    dataset_version: str
    snapshot_sha256: str
    license_confirmation: str
    usage_scope: str


class BaselineAssetObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    asset_id: uuid.UUID
    status: Literal["VERIFIED", "MISSING", "CHANGED", "UNSAFE", "UNAVAILABLE"]
    actual_sha256: str | None
    actual_size_bytes: int | None
    issue: str | None
    checked_at: datetime


class BaselineMaterialCheckSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version_id: uuid.UUID
    version_sha256: str
    outcome: Literal["MATERIALIZED", "INCOMPLETE", "FAILED"]
    checker_version: str
    checker_sha256: str
    checked_at: datetime
    gaps: list[str]


class BaselineMaterialCheckOut(BaselineMaterialCheckSummary):
    observations: list[BaselineAssetObservationOut]
    execution_authorized: Literal[False] = False


class BaselineVersionOut(BaseModel):
    id: uuid.UUID
    baseline_id: uuid.UUID
    project_id: uuid.UUID
    version: str
    parent_version_id: uuid.UUID | None
    parent_sha256: str | None
    model_id: uuid.UUID | None
    model_version_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    weight_mode: Literal["PRETRAINED", "FROM_SCRATCH"]
    purpose: str | None
    notes: str | None
    sha256: str
    created_at: datetime
    qualification: Literal["CATALOGED", "MATERIALIZED"]
    scope_current: bool
    can_check_materials: bool
    gaps: list[str]
    assets: list[BaselineAssetOut]
    datasets: list[BaselineDatasetOut]
    latest_check: BaselineMaterialCheckSummary | None
    execution_authorized: Literal[False] = False
    smoke_verified: Literal[False] = False
    protocol_verified: Literal[False] = False


class BaselinePage(BaseModel):
    items: list[BaselineOut]
    page: PageMeta


class BaselineVersionPage(BaseModel):
    items: list[BaselineVersionOut]
    page: PageMeta


class BaselineMaterialCheckPage(BaseModel):
    items: list[BaselineMaterialCheckSummary]
    page: PageMeta


class BaselineSourceJobChoice(BaseModel):
    id: uuid.UUID
    source_plan_id: uuid.UUID
    repo_id: str
    commit_sha: str
    source_status: Literal["MATERIALIZED", "PARTIAL"]
    copied_files: int
    copied_bytes: int
    receipt_sha256: str
    verified_at: datetime


class BaselineSourceFileChoice(BaseModel):
    source_file_id: uuid.UUID
    source_job_id: uuid.UUID
    source_plan_id: uuid.UUID
    file_key_sha256: str
    path: str
    sha256: str
    size_bytes: int


class BaselineSourceJobPage(BaseModel):
    items: list[BaselineSourceJobChoice]
    page: PageMeta


class BaselineSourceFilePage(BaseModel):
    items: list[BaselineSourceFileChoice]
    page: PageMeta


class BaselineCapabilityOut(BaseModel):
    catalog_available: Literal[True] = True
    materials_check_available: bool
    smoke_supported: Literal[False] = False
    protocol_supported: Literal[False] = False
    execution_authorized: Literal[False] = False
    detail: str
