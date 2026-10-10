"""Readonly baseline material observations; never execution or scientific approval."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.domain.project_sources import ProjectSourceFile, ProjectSourceScope

BaselineAssetStatus = Literal["VERIFIED", "MISSING", "CHANGED", "UNSAFE", "UNAVAILABLE"]


class DatasetSplitSampleV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sample_id: str = Field(min_length=1, max_length=256)
    group_id: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=2000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0, le=1024 * 1024 * 1024)


class DatasetSplitV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Literal["TRAIN", "VALIDATION", "TEST"]
    samples: tuple[DatasetSplitSampleV1, ...] = Field(min_length=1, max_length=10000)


class DatasetSplitManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    dataset_version_id: uuid.UUID
    splits: tuple[DatasetSplitV1, ...] = Field(min_length=3, max_length=3)


@dataclass(frozen=True)
class BaselineProbeAsset:
    asset_id: uuid.UUID
    role: str
    dataset_version_id: uuid.UUID | None
    source_scope: ProjectSourceScope
    source_file: ProjectSourceFile
    attachment_id: uuid.UUID | None = None


@dataclass(frozen=True)
class BaselineProbeRequest:
    version_id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID
    version_sha256: str
    assets: tuple[BaselineProbeAsset, ...]
    dataset_version_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class BaselineAssetObservation:
    asset_id: uuid.UUID
    status: BaselineAssetStatus
    actual_sha256: str | None
    actual_size_bytes: int | None
    issue: str | None
    checked_at: datetime


@dataclass(frozen=True)
class BaselineProbeResult:
    checker_version: str
    checker_sha256: str
    observations: tuple[BaselineAssetObservation, ...]
    gaps: tuple[str, ...]
    split_valid: bool


class BaselineAssetProbeProvider(Protocol):
    async def probe(self, request: BaselineProbeRequest) -> BaselineProbeResult: ...
