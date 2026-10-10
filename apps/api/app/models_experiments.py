"""Normalized scientific registries and immutable run provenance (Phase3)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OwnerRecord:
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)


class Modality(OwnerRecord, Base):
    __tablename__ = "modalities"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_modality_owner_code"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(120))


class Dataset(OwnerRecord, Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_dataset_owner_name"),)
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(240))
    task: Mapped[str] = mapped_column(String(120))
    source: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DatasetModality(OwnerRecord, Base):
    __tablename__ = "dataset_modalities"
    dataset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("datasets.id"), primary_key=True)
    modality_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("modalities.id"), primary_key=True
    )


class DatasetVersion(OwnerRecord, Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("id", "dataset_id", "user_id", name="uq_dataset_version_source_owner"),
        UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),
        CheckConstraint(
            "number_images IS NULL OR number_images >= 0", name="ck_dataset_number_images"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("datasets.id"), index=True)
    version: Mapped[str] = mapped_column(String(120))
    number_images: Mapped[int | None] = mapped_column(BigInteger)
    resolution: Mapped[str | None] = mapped_column(String(160))
    annotation_format: Mapped[str | None] = mapped_column(String(160))
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetClass(OwnerRecord, Base):
    __tablename__ = "dataset_classes"
    __table_args__ = (CheckConstraint("class_index >= 0", name="ck_dataset_class_index"),)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dataset_versions.id"), primary_key=True
    )
    class_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))


class DatasetSplit(OwnerRecord, Base):
    __tablename__ = "dataset_splits"
    __table_args__ = (
        CheckConstraint("sample_count IS NULL OR sample_count >= 0", name="ck_dataset_split_count"),
    )
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dataset_versions.id"), primary_key=True
    )
    split_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    sample_count: Mapped[int | None] = mapped_column(BigInteger)
    manifest_uri: Mapped[str | None] = mapped_column(Text)


class DatasetLocation(OwnerRecord, Base):
    __tablename__ = "dataset_locations"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "storage_provider", "uri", name="uq_dataset_location"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dataset_versions.id"), index=True
    )
    storage_provider: Mapped[str] = mapped_column(String(80))
    uri: Mapped[str] = mapped_column(String(2000))
    mount_hint: Mapped[str | None] = mapped_column(String(1000))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Model(OwnerRecord, Base):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_model_owner_name"),)
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(240))
    task: Mapped[str] = mapped_column(String(120))
    family: Mapped[str | None] = mapped_column(String(160))
    architecture: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("papers.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelModality(OwnerRecord, Base):
    __tablename__ = "model_modalities"
    model_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("models.id"), primary_key=True)
    modality_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("modalities.id"), primary_key=True
    )


class CodeRepository(OwnerRecord, Base):
    __tablename__ = "code_repositories"
    __table_args__ = (UniqueConstraint("id", "user_id", name="uq_code_repository_owner"),)
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(240))
    provider_key: Mapped[str | None] = mapped_column(String(80))
    external_id: Mapped[str | None] = mapped_column(String(320))
    url: Mapped[str | None] = mapped_column(Text)
    local_uri: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelVersion(OwnerRecord, Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("id", "model_id", "user_id", name="uq_model_version_source_owner"),
        UniqueConstraint("model_id", "version", name="uq_model_version"),
        CheckConstraint("parameters IS NULL OR parameters >= 0", name="ck_model_parameters"),
        CheckConstraint("flops IS NULL OR flops >= 0", name="ck_model_flops"),
        CheckConstraint("fps IS NULL OR fps >= 0", name="ck_model_fps"),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    model_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("models.id"), index=True)
    version: Mapped[str] = mapped_column(String(120))
    code_repository_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("code_repositories.id")
    )
    git_commit: Mapped[str | None] = mapped_column(String(64))
    input_size: Mapped[str | None] = mapped_column(String(160))
    parameters: Mapped[int | None] = mapped_column(BigInteger)
    flops: Mapped[Decimal | None] = mapped_column(Numeric())
    fps: Mapped[Decimal | None] = mapped_column(Numeric())
    checkpoint_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("attachments.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelComponent(OwnerRecord, Base):
    __tablename__ = "model_components"
    __table_args__ = (CheckConstraint("sort_order >= 0", name="ck_model_component_order"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("model_versions.id"), index=True
    )
    component_type: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)


class Hypothesis(OwnerRecord, Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('UNTESTED','SUPPORTED','REFUTED','INCONCLUSIVE','ARCHIVED')",
            name="ck_hypothesis_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_projects.id"), index=True
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("research_questions.id"))
    statement: Mapped[str] = mapped_column(Text)
    test_plan: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="UNTESTED", server_default="UNTESTED")
    result_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Experiment(OwnerRecord, Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("user_id", "experiment_code", name="uq_experiment_owner_code"),
        CheckConstraint(
            "status IN ('PLANNED','RUNNING','COMPLETED','FAILED','STOPPED','ARCHIVED')",
            name="ck_experiment_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_entities.id"), primary_key=True
    )
    experiment_code: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(240))
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_projects.id"), index=True
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("research_questions.id"))
    hypothesis_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("hypotheses.id"))
    objective: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="PLANNED", server_default="PLANNED")
    conclusion: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExperimentRun(OwnerRecord, Base):
    __tablename__ = "experiment_runs"
    __table_args__ = (
        UniqueConstraint("experiment_id", "run_number", name="uq_experiment_run_number"),
        CheckConstraint("run_number > 0", name="ck_experiment_run_number"),
        CheckConstraint("random_seed IS NULL OR random_seed >= 0", name="ck_experiment_seed"),
        CheckConstraint(
            "status IN ('PLANNED','RUNNING','COMPLETED','FAILED','STOPPED','ARCHIVED')",
            name="ck_experiment_run_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("experiments.id"), index=True)
    run_number: Mapped[int] = mapped_column(Integer)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("model_versions.id")
    )
    code_repository_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("code_repositories.id")
    )
    git_commit: Mapped[str | None] = mapped_column(String(64))
    code_version: Mapped[str | None] = mapped_column(String(160))
    config_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("attachments.id")
    )
    config_sha256: Mapped[str | None] = mapped_column(String(64))
    random_seed: Mapped[int | None] = mapped_column(BigInteger)
    gpu: Mapped[str | None] = mapped_column(String(240))
    python_version: Mapped[str | None] = mapped_column(String(80))
    pytorch_version: Mapped[str | None] = mapped_column(String(80))
    cuda_version: Mapped[str | None] = mapped_column(String(80))
    reproduction_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("codex_tasks.id")
    )
    status: Mapped[str] = mapped_column(String(24), default="PLANNED", server_default="PLANNED")
    notes: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentRunDataset(OwnerRecord, Base):
    __tablename__ = "experiment_run_datasets"
    __table_args__ = (
        CheckConstraint(
            "role IN ('train','validation','test','auxiliary')", name="ck_run_dataset_role"
        ),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("experiment_runs.id"), primary_key=True
    )
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dataset_versions.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(24), primary_key=True)


class ExperimentParameter(OwnerRecord, Base):
    __tablename__ = "experiment_parameters"
    __table_args__ = (
        CheckConstraint(
            "value_type IN ('STRING','INTEGER','FLOAT','BOOLEAN')",
            name="ck_experiment_parameter_type",
        ),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("experiment_runs.id"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(160), primary_key=True)
    value_text: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(24))
    unit: Mapped[str | None] = mapped_column(String(80))


class MetricDefinition(OwnerRecord, Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "name", "evaluation_protocol", name="uq_metric_owner_semantics"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str | None] = mapped_column(String(80))
    higher_is_better: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str | None] = mapped_column(Text)
    evaluation_protocol: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentMetric(OwnerRecord, Base):
    __tablename__ = "experiment_metrics"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "metric_definition_id",
            "split_name",
            "location_key",
            name="uq_run_metric_location",
        ),
        CheckConstraint("step IS NULL OR step >= 0", name="ck_metric_step"),
        CheckConstraint("epoch IS NULL OR epoch >= 0", name="ck_metric_epoch"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("experiment_runs.id"), index=True)
    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("metric_definitions.id"), index=True
    )
    split_name: Mapped[str] = mapped_column(String(80))
    location_key: Mapped[str] = mapped_column(String(80))
    step: Mapped[int | None] = mapped_column(BigInteger)
    epoch: Mapped[int | None] = mapped_column(BigInteger)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    value: Mapped[Decimal] = mapped_column(Numeric())
    value_text: Mapped[str] = mapped_column(String(80))
    is_best: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentArtifact(OwnerRecord, Base):
    __tablename__ = "experiment_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "attachment_id", "artifact_type", name="uq_run_artifact"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("experiment_runs.id"), index=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attachments.id"))
    artifact_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentStatusEvent(OwnerRecord, Base):
    __tablename__ = "experiment_status_events"
    __table_args__ = (
        CheckConstraint(
            "(experiment_id IS NOT NULL AND run_id IS NULL) OR (experiment_id IS NULL AND run_id IS NOT NULL)",
            name="ck_experiment_event_target",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("experiments.id"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("experiment_runs.id"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
