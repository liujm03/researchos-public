"""Recorded experiments/runs; these services never launch training or providers."""

import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import experiments as schema
from app.errors import DomainError
from app.models import (
    CodeRepository,
    CodexTask,
    DatasetVersion,
    Experiment,
    ExperimentArtifact,
    ExperimentMetric,
    ExperimentParameter,
    ExperimentRun,
    ExperimentRunDataset,
    ExperimentStatusEvent,
    Hypothesis,
    MetricDefinition,
    ModelVersion,
)
from app.services.common import register_entity
from app.services.experiment_registries import attachment, commit, nonempty, owned, project_question

TRANSITIONS = {
    "PLANNED": {"RUNNING", "COMPLETED", "FAILED", "STOPPED", "ARCHIVED"},
    "RUNNING": {"COMPLETED", "FAILED", "STOPPED", "ARCHIVED"},
    "COMPLETED": {"ARCHIVED"},
    "FAILED": {"ARCHIVED"},
    "STOPPED": {"ARCHIVED"},
    "ARCHIVED": set(),
}


def get_experiment(
    db: Session, user_id: uuid.UUID, experiment_id: uuid.UUID, *, lock: bool = False
) -> Experiment:
    return owned(db, user_id, Experiment, experiment_id, lock=lock)


def get_run(
    db: Session, user_id: uuid.UUID, run_id: uuid.UUID, *, lock: bool = False
) -> ExperimentRun:
    return owned(db, user_id, ExperimentRun, run_id, lock=lock)


def _event(
    db: Session,
    user_id: uuid.UUID,
    *,
    experiment_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    previous: str | None = None,
    status: str,
    reason: str | None = None,
) -> None:
    db.add(
        ExperimentStatusEvent(
            user_id=user_id,
            experiment_id=experiment_id,
            run_id=run_id,
            from_status=previous,
            to_status=status,
            reason=reason,
            changed_at=datetime.now(UTC),
        )
    )


def create_experiment(db: Session, user_id: uuid.UUID, body: schema.ExperimentCreate) -> Experiment:
    project_question(db, user_id, body.project_id, body.question_id)
    values = body.model_dump()
    if body.hypothesis_id is not None:
        hypothesis = owned(db, user_id, Hypothesis, body.hypothesis_id)
        if hypothesis.project_id != body.project_id or (
            body.question_id and hypothesis.question_id != body.question_id
        ):
            raise DomainError(
                "HYPOTHESIS_SCOPE_MISMATCH",
                "Hypothesis does not belong to the experiment's project/question",
                422,
            )
        if body.question_id is None:
            values["question_id"] = hypothesis.question_id
    try:
        row = Experiment(id=register_entity(db, user_id, "experiment"), user_id=user_id, **values)
        row.name, row.experiment_code = nonempty(row.name), nonempty(row.experiment_code)
        db.add(row)
        db.flush()
        _event(
            db,
            user_id,
            experiment_id=row.id,
            status="PLANNED",
            reason="Owner recorded an experiment design",
        )
        return commit(db, row)
    except Exception:
        db.rollback()
        raise


def _transition(current: str, next_status: str) -> None:
    if next_status != current and next_status not in TRANSITIONS[current]:
        raise DomainError(
            "INVALID_STATUS_TRANSITION",
            "Create a new run instead of reopening immutable provenance",
            409,
        )


def patch_experiment(
    db: Session, user_id: uuid.UUID, experiment_id: uuid.UUID, body: schema.ExperimentPatch
) -> Experiment:
    row = get_experiment(db, user_id, experiment_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    if changes.get("name", "valid") is None or changes.get("status", "valid") is None:
        raise DomainError("VALIDATION_ERROR", "Experiment name/status cannot be null", 422)
    if "status" in changes:
        _transition(row.status, changes["status"])
        if row.status != changes["status"]:
            _event(
                db,
                user_id,
                experiment_id=row.id,
                previous=row.status,
                status=changes["status"],
                reason=reason,
            )
    for key, value in changes.items():
        setattr(row, key, nonempty(value) if key == "name" else value)
    return commit(db, row)


def _validate_parameter(parameter: schema.ExperimentParameter) -> None:
    try:
        if parameter.value_type == "INTEGER":
            int(parameter.value_text)
        elif parameter.value_type == "FLOAT":
            if not Decimal(parameter.value_text).is_finite():
                raise ValueError
        elif parameter.value_type == "BOOLEAN" and parameter.value_text.lower() not in {
            "true",
            "false",
        }:
            raise ValueError
    except (ValueError, InvalidOperation) as error:
        raise DomainError(
            "PARAMETER_TYPE_MISMATCH", "Parameter text does not match its declared type", 422
        ) from error


def create_run(
    db: Session, user_id: uuid.UUID, experiment_id: uuid.UUID, body: schema.ExperimentRunCreate
) -> ExperimentRun:
    experiment = get_experiment(db, user_id, experiment_id, lock=True)
    if experiment.status == "ARCHIVED":
        raise DomainError("EXPERIMENT_ARCHIVED", "Archived designs cannot receive new runs", 409)
    if body.model_version_id is not None:
        owned(db, user_id, ModelVersion, body.model_version_id)
    if body.code_repository_id is not None:
        owned(db, user_id, CodeRepository, body.code_repository_id)
    if body.reproduction_task_id is not None:
        task = owned(db, user_id, CodexTask, body.reproduction_task_id)
        if task.kind != "paper_reproduction":
            raise DomainError(
                "REPRODUCTION_TASK_REQUIRED", "Link an owned paper reproduction task", 422
            )
    if body.config_attachment_id is not None:
        config = attachment(db, user_id, body.config_attachment_id)
        if body.config_sha256 is not None and body.config_sha256 != config.sha256:
            raise DomainError(
                "CONFIG_HASH_MISMATCH", "Configuration hash does not match the attachment", 422
            )
    if len({(row.dataset_version_id, row.role) for row in body.datasets}) != len(body.datasets):
        raise DomainError("VALIDATION_ERROR", "Run dataset/version/role links must be unique", 422)
    if len({row.name.strip() for row in body.parameters}) != len(body.parameters):
        raise DomainError("VALIDATION_ERROR", "Run parameter names must be unique", 422)
    for link in body.datasets:
        owned(db, user_id, DatasetVersion, link.dataset_version_id)
    for parameter in body.parameters:
        _validate_parameter(parameter)
    values = body.model_dump(exclude={"datasets", "parameters"})
    if values["run_number"] is None:
        values["run_number"] = (
            db.scalar(
                select(func.max(ExperimentRun.run_number)).where(
                    ExperimentRun.experiment_id == experiment.id, ExperimentRun.user_id == user_id
                )
            )
            or 0
        ) + 1
    if body.config_attachment_id is not None:
        values["config_sha256"] = config.sha256
    try:
        row = ExperimentRun(id=uuid.uuid4(), user_id=user_id, experiment_id=experiment_id, **values)
        db.add(row)
        db.flush()
        for link in body.datasets:
            db.add(ExperimentRunDataset(user_id=user_id, run_id=row.id, **link.model_dump()))
        for parameter in body.parameters:
            values_parameter = parameter.model_dump()
            values_parameter["name"] = nonempty(values_parameter["name"])
            db.add(ExperimentParameter(user_id=user_id, run_id=row.id, **values_parameter))
        _event(
            db,
            user_id,
            run_id=row.id,
            status="PLANNED",
            reason="Owner recorded immutable run provenance",
        )
        return commit(db, row)
    except Exception:
        db.rollback()
        raise


def run_out(db: Session, user_id: uuid.UUID, row: ExperimentRun) -> schema.ExperimentRunOut:
    values = {
        key: getattr(row, key)
        for key in schema.ExperimentRunOut.model_fields
        if key not in {"datasets", "parameters"}
    }
    values["datasets"] = list(
        db.scalars(
            select(ExperimentRunDataset)
            .where(ExperimentRunDataset.user_id == user_id, ExperimentRunDataset.run_id == row.id)
            .order_by(ExperimentRunDataset.role, ExperimentRunDataset.dataset_version_id)
        )
    )
    values["parameters"] = list(
        db.scalars(
            select(ExperimentParameter)
            .where(ExperimentParameter.user_id == user_id, ExperimentParameter.run_id == row.id)
            .order_by(ExperimentParameter.name)
        )
    )
    return schema.ExperimentRunOut.model_validate(values)


def patch_run(
    db: Session, user_id: uuid.UUID, run_id: uuid.UUID, body: schema.ExperimentRunPatch
) -> ExperimentRun:
    row = get_run(db, user_id, run_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    if "status" in changes:
        if changes["status"] is None:
            raise DomainError("VALIDATION_ERROR", "Run status cannot be null", 422)
        _transition(row.status, changes["status"])
        if changes["status"] != row.status:
            _event(
                db,
                user_id,
                run_id=row.id,
                previous=row.status,
                status=changes["status"],
                reason=reason,
            )
            if changes["status"] == "RUNNING" and row.started_at is None:
                row.started_at = datetime.now(UTC)
            if changes["status"] in {"COMPLETED", "FAILED", "STOPPED"} and row.ended_at is None:
                row.ended_at = datetime.now(UTC)
    for key, value in changes.items():
        setattr(row, key, value)
    return commit(db, row)


def create_metric_definition(
    db: Session, user_id: uuid.UUID, body: schema.MetricDefinitionCreate
) -> MetricDefinition:
    values = body.model_dump()
    values["name"], values["evaluation_protocol"] = (
        nonempty(values["name"]),
        nonempty(values["evaluation_protocol"]),
    )
    existing = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.user_id == user_id,
            MetricDefinition.name == values["name"],
            MetricDefinition.evaluation_protocol == values["evaluation_protocol"],
        )
    )
    if existing is not None:
        if any(getattr(existing, key) != value for key, value in values.items()):
            raise DomainError(
                "METRIC_DEFINITION_CONFLICT",
                "Metric meaning is immutable; use a distinct protocol/name",
                409,
            )
        return existing
    row = MetricDefinition(user_id=user_id, **values)
    db.add(row)
    return commit(db, row)


def metric_out(row: ExperimentMetric) -> schema.ExperimentMetricOut:
    values = {
        key: getattr(row, key) for key in schema.ExperimentMetricOut.model_fields if key != "value"
    }
    values["value"] = float(row.value_text)
    return schema.ExperimentMetricOut.model_validate(values)


def record_metrics(
    db: Session, user_id: uuid.UUID, run_id: uuid.UUID, body: schema.MetricBatchCreate
) -> schema.MetricBatchOut:
    run = get_run(db, user_id, run_id, lock=True)
    if run.status == "ARCHIVED":
        raise DomainError(
            "RUN_ARCHIVED", "Archived runs cannot receive new metric measurements", 409
        )
    rows: list[ExperimentMetric] = []
    created = reused = 0
    try:
        for item in body.metrics:
            owned(db, user_id, MetricDefinition, item.metric_definition_id)
            if not math.isfinite(item.value):
                raise DomainError("NON_FINITE_METRIC", "Metric value must be finite", 422)
            location = (
                f"STEP:{item.step}"
                if item.step is not None
                else f"EPOCH:{item.epoch}"
                if item.epoch is not None
                else "SUMMARY"
            )
            split_name = nonempty(item.split_name)
            existing = db.scalar(
                select(ExperimentMetric).where(
                    ExperimentMetric.user_id == user_id,
                    ExperimentMetric.run_id == run.id,
                    ExperimentMetric.metric_definition_id == item.metric_definition_id,
                    ExperimentMetric.split_name == split_name,
                    ExperimentMetric.location_key == location,
                )
            )
            value_text = str(item.value)
            if existing is not None:
                if (
                    float(existing.value_text) != item.value
                    or existing.step != item.step
                    or existing.epoch != item.epoch
                    or existing.is_best != item.is_best
                    or _timestamp(existing.measured_at) != _timestamp(item.measured_at)
                ):
                    raise DomainError(
                        "METRIC_CONFLICT",
                        "Contradictory measurement rejected; original evidence preserved",
                        409,
                        details={
                            "metric_id": str(existing.id),
                            "location": location,
                            "split_name": split_name,
                        },
                    )
                reused += 1
                rows.append(existing)
                continue
            values = item.model_dump(exclude={"value"})
            values["split_name"] = split_name
            row = ExperimentMetric(
                user_id=user_id,
                run_id=run.id,
                location_key=location,
                value=Decimal(value_text),
                value_text=value_text,
                **values,
            )
            db.add(row)
            db.flush()
            created += 1
            rows.append(row)
        db.commit()
        return schema.MetricBatchOut(
            items=[metric_out(row) for row in rows], created=created, reused=reused
        )
    except Exception:
        db.rollback()
        raise


def _timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def attach_artifact(
    db: Session,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    attachment_id: uuid.UUID,
    artifact_type: str,
    description: str | None = None,
    *,
    commit: bool = True,
) -> ExperimentArtifact:
    get_run(db, user_id, run_id, lock=True)
    attachment(db, user_id, attachment_id)
    schema.ExperimentArtifactCreate(
        attachment_id=attachment_id, artifact_type=artifact_type, description=description
    )
    existing = db.scalar(
        select(ExperimentArtifact).where(
            ExperimentArtifact.user_id == user_id,
            ExperimentArtifact.run_id == run_id,
            ExperimentArtifact.attachment_id == attachment_id,
            ExperimentArtifact.artifact_type == artifact_type,
        )
    )
    if existing is not None:
        if existing.description != description:
            raise DomainError(
                "ARTIFACT_CONFLICT",
                "An artifact association already has a different description",
                409,
            )
        return existing
    row = ExperimentArtifact(
        user_id=user_id,
        run_id=run_id,
        attachment_id=attachment_id,
        artifact_type=artifact_type,
        description=description,
    )
    db.add(row)
    if commit:
        from app.services.experiment_registries import commit as commit_record

        return commit_record(db, row)
    db.flush()
    return row


def artifact_out(
    db: Session, user_id: uuid.UUID, row: ExperimentArtifact
) -> schema.ExperimentArtifactOut:
    record = attachment(db, user_id, row.attachment_id)
    return schema.ExperimentArtifactOut(
        id=row.id,
        run_id=row.run_id,
        attachment_id=row.attachment_id,
        artifact_type=row.artifact_type,
        description=row.description,
        created_at=row.created_at,
        original_filename=record.original_filename,
        sha256=record.sha256,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
    )
