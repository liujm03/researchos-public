"""Typed registry and externally recorded experiment contracts."""

import math
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from app.errors import DomainError

RunStatus = Literal["PLANNED", "RUNNING", "COMPLETED", "FAILED", "STOPPED", "ARCHIVED"]
DatasetRole = Literal["train", "validation", "test", "auxiliary"]
ArtifactType = Literal[
    "CHECKPOINT",
    "LOG",
    "TRAINING_CURVE",
    "PR_CURVE",
    "CONFUSION_MATRIX",
    "FIGURE",
    "REPORT",
    "CONFIG",
    "OTHER",
]
HypothesisStatus = Literal["UNTESTED", "SUPPORTED", "REFUTED", "INCONCLUSIVE", "ARCHIVED"]


class Record(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def reject_nonfinite(cls, value: object) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            raise DomainError(
                "NON_FINITE_SCIENTIFIC_VALUE", "Scientific numeric values must be finite", 422
            )
        return value


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ModalityOut(Record):
    id: uuid.UUID
    code: str
    display_name: str


class ModalityPage(Page[ModalityOut]):
    pass


class DatasetCreate(Record):
    name: str = Field(min_length=1, max_length=240)
    task: str = Field(min_length=1, max_length=120)
    source: str | None = Field(default=None, max_length=2000)
    license: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    modalities: list[str] = Field(default_factory=list, max_length=16)


class DatasetPatch(Record):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    task: str | None = Field(default=None, min_length=1, max_length=120)
    source: str | None = Field(default=None, max_length=2000)
    license: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    modalities: list[str] | None = Field(default=None, max_length=16)
    archived: bool | None = None


class DatasetOut(DatasetCreate):
    id: uuid.UUID
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DatasetPage(Page[DatasetOut]):
    pass


class DatasetClass(Record):
    class_index: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=160)


class DatasetSplit(Record):
    split_name: str = Field(min_length=1, max_length=80)
    sample_count: int | None = Field(default=None, ge=0)
    manifest_uri: str | None = Field(default=None, max_length=2000)


class DatasetLocationCreate(Record):
    storage_provider: str = Field(min_length=1, max_length=80)
    uri: str = Field(min_length=1, max_length=2000)
    mount_hint: str | None = Field(default=None, max_length=1000)
    verified_at: datetime | None = None


class DatasetLocationOut(DatasetLocationCreate):
    id: uuid.UUID


class DatasetVersionCreate(Record):
    version: str = Field(min_length=1, max_length=120)
    number_images: int | None = Field(default=None, ge=0)
    resolution: str | None = Field(default=None, max_length=160)
    annotation_format: str | None = Field(default=None, max_length=160)
    manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    classes: list[DatasetClass] = Field(default_factory=list, max_length=1000)
    splits: list[DatasetSplit] = Field(default_factory=list, max_length=100)
    locations: Sequence[DatasetLocationCreate] = Field(default_factory=list, max_length=100)


class DatasetVersionOut(DatasetVersionCreate):
    id: uuid.UUID
    dataset_id: uuid.UUID
    locations: list[DatasetLocationOut]
    created_at: datetime


class DatasetVersionPage(Page[DatasetVersionOut]):
    pass


class ModelCreate(Record):
    name: str = Field(min_length=1, max_length=240)
    task: str = Field(min_length=1, max_length=120)
    family: str | None = Field(default=None, max_length=160)
    architecture: str | None = Field(default=None, max_length=10_000)
    source: str | None = Field(default=None, max_length=2000)
    paper_id: uuid.UUID | None = None
    modalities: list[str] = Field(default_factory=list, max_length=16)


class ModelPatch(Record):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    task: str | None = Field(default=None, min_length=1, max_length=120)
    family: str | None = Field(default=None, max_length=160)
    architecture: str | None = Field(default=None, max_length=10_000)
    source: str | None = Field(default=None, max_length=2000)
    paper_id: uuid.UUID | None = None
    modalities: list[str] | None = Field(default=None, max_length=16)
    archived: bool | None = None


class ModelOut(ModelCreate):
    id: uuid.UUID
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ModelPage(Page[ModelOut]):
    pass


class ModelComponentCreate(Record):
    component_type: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    sort_order: int = Field(default=0, ge=0)


class ModelComponentOut(ModelComponentCreate):
    id: uuid.UUID


class ModelVersionCreate(Record):
    version: str = Field(min_length=1, max_length=120)
    code_repository_id: uuid.UUID | None = None
    git_commit: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{7,64}$")
    input_size: str | None = Field(default=None, max_length=160)
    parameters: int | None = Field(default=None, ge=0)
    flops: FiniteFloat | None = Field(default=None, ge=0)
    fps: FiniteFloat | None = Field(default=None, ge=0)
    checkpoint_attachment_id: uuid.UUID | None = None
    components: Sequence[ModelComponentCreate] = Field(default_factory=list, max_length=100)


class ModelVersionOut(ModelVersionCreate):
    id: uuid.UUID
    model_id: uuid.UUID
    components: list[ModelComponentOut]
    created_at: datetime


class ModelVersionPage(Page[ModelVersionOut]):
    pass


class CodeRepositoryCreate(Record):
    name: str = Field(min_length=1, max_length=240)
    provider_key: str | None = Field(default=None, max_length=80)
    external_id: str | None = Field(default=None, max_length=320)
    url: str | None = Field(default=None, max_length=2000)
    local_uri: str | None = Field(default=None, max_length=2000)


class CodeRepositoryOut(CodeRepositoryCreate):
    id: uuid.UUID
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CodeRepositoryPage(Page[CodeRepositoryOut]):
    pass


class CodeRepositoryPatch(Record):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    provider_key: str | None = Field(default=None, max_length=80)
    external_id: str | None = Field(default=None, max_length=320)
    url: str | None = Field(default=None, max_length=2000)
    local_uri: str | None = Field(default=None, max_length=2000)
    archived: bool | None = None


class HypothesisCreate(Record):
    project_id: uuid.UUID
    question_id: uuid.UUID | None = None
    statement: str = Field(min_length=1, max_length=10_000)
    test_plan: str | None = Field(default=None, max_length=20_000)


class HypothesisPatch(Record):
    statement: str | None = Field(default=None, min_length=1, max_length=10_000)
    test_plan: str | None = Field(default=None, max_length=20_000)
    status: HypothesisStatus | None = None
    result_notes: str | None = Field(default=None, max_length=20_000)


class HypothesisOut(HypothesisCreate):
    id: uuid.UUID
    status: HypothesisStatus
    result_notes: str | None
    created_at: datetime
    updated_at: datetime


class HypothesisPage(Page[HypothesisOut]):
    pass


class ExperimentCreate(Record):
    experiment_code: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    project_id: uuid.UUID
    question_id: uuid.UUID | None = None
    hypothesis_id: uuid.UUID | None = None
    objective: str | None = Field(default=None, max_length=20_000)


class ExperimentPatch(Record):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    objective: str | None = Field(default=None, max_length=20_000)
    status: RunStatus | None = None
    conclusion: str | None = Field(default=None, max_length=20_000)
    reason: str | None = Field(default=None, max_length=2000)


class ExperimentOut(ExperimentCreate):
    id: uuid.UUID
    status: RunStatus
    conclusion: str | None
    created_at: datetime
    updated_at: datetime


class ExperimentPage(Page[ExperimentOut]):
    pass


class RunDataset(Record):
    dataset_version_id: uuid.UUID
    role: DatasetRole


class ExperimentParameter(Record):
    name: str = Field(min_length=1, max_length=160)
    value_text: str = Field(max_length=4000)
    value_type: Literal["STRING", "INTEGER", "FLOAT", "BOOLEAN"] = "STRING"
    unit: str | None = Field(default=None, max_length=80)


class ExperimentRunCreate(Record):
    run_number: int | None = Field(default=None, ge=1)
    model_version_id: uuid.UUID | None = None
    code_repository_id: uuid.UUID | None = None
    git_commit: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{7,64}$")
    code_version: str | None = Field(default=None, max_length=160)
    config_attachment_id: uuid.UUID | None = None
    config_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    random_seed: int | None = Field(default=None, ge=0)
    gpu: str | None = Field(default=None, max_length=240)
    python_version: str | None = Field(default=None, max_length=80)
    pytorch_version: str | None = Field(default=None, max_length=80)
    cuda_version: str | None = Field(default=None, max_length=80)
    reproduction_task_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    datasets: list[RunDataset] = Field(default_factory=list, max_length=100)
    parameters: list[ExperimentParameter] = Field(default_factory=list, max_length=200)


class ExperimentRunPatch(Record):
    status: RunStatus | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    conclusion: str | None = Field(default=None, max_length=20_000)
    reason: str | None = Field(default=None, max_length=2000)


class ExperimentRunOut(ExperimentRunCreate):
    id: uuid.UUID
    experiment_id: uuid.UUID
    run_number: int
    status: RunStatus
    conclusion: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class ExperimentRunPage(Page[ExperimentRunOut]):
    pass


class MetricDefinitionCreate(Record):
    name: str = Field(min_length=1, max_length=120)
    unit: str | None = Field(default=None, max_length=80)
    higher_is_better: bool
    description: str | None = Field(default=None, max_length=5000)
    evaluation_protocol: str = Field(min_length=1, max_length=2000)


class MetricDefinitionOut(MetricDefinitionCreate):
    id: uuid.UUID
    created_at: datetime


class MetricDefinitionPage(Page[MetricDefinitionOut]):
    pass


class MetricCreate(Record):
    metric_definition_id: uuid.UUID
    split_name: str = Field(default="all", min_length=1, max_length=80)
    step: int | None = Field(default=None, ge=0)
    epoch: int | None = Field(default=None, ge=0)
    measured_at: datetime | None = None
    value: FiniteFloat = Field(strict=True)
    is_best: bool = False


class ExperimentMetricOut(MetricCreate):
    id: uuid.UUID
    run_id: uuid.UUID
    created_at: datetime


class MetricBatchCreate(Record):
    metrics: list[MetricCreate] = Field(min_length=1, max_length=1000)


class MetricBatchOut(BaseModel):
    items: list[ExperimentMetricOut]
    created: int
    reused: int


class ExperimentMetricPage(Page[ExperimentMetricOut]):
    pass


class ExperimentArtifactCreate(Record):
    attachment_id: uuid.UUID
    artifact_type: ArtifactType
    description: str | None = Field(default=None, max_length=5000)


class ExperimentArtifactOut(ExperimentArtifactCreate):
    id: uuid.UUID
    run_id: uuid.UUID
    original_filename: str
    sha256: str
    mime_type: str
    size_bytes: int
    created_at: datetime


class ExperimentArtifactPage(Page[ExperimentArtifactOut]):
    pass


class ExperimentStatusEventOut(Record):
    id: uuid.UUID
    experiment_id: uuid.UUID | None
    run_id: uuid.UUID | None
    from_status: RunStatus | None
    to_status: RunStatus
    reason: str | None
    changed_at: datetime


class ExperimentStatusEventPage(Page[ExperimentStatusEventOut]):
    pass


class RunComparisonRequest(Record):
    run_ids: list[uuid.UUID] = Field(min_length=2, max_length=20)
    metric_definition_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)


class ComparisonValue(BaseModel):
    run_id: uuid.UUID
    value: float | None


class ComparisonPoint(BaseModel):
    step: int | None
    epoch: int | None
    value: float


class ComparisonSeries(BaseModel):
    run_id: uuid.UUID
    points: list[ComparisonPoint]


class ComparisonMetric(BaseModel):
    metric_definition: MetricDefinitionOut
    split_name: str
    values: list[ComparisonValue]
    series: list[ComparisonSeries]


class RunComparisonOut(BaseModel):
    runs: list[ExperimentRunOut]
    warnings: list[str]
    metrics: list[ComparisonMetric]
