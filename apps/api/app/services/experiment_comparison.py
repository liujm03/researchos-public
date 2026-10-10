"""Compare only recorded measurements with explicit semantic/provenance gaps."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import experiments as schema
from app.errors import DomainError
from app.models import ExperimentMetric, MetricDefinition
from app.services.experiment_registries import owned
from app.services.experiments import get_run, run_out


def compare_runs(
    db: Session, user_id: uuid.UUID, body: schema.RunComparisonRequest
) -> schema.RunComparisonOut:
    if len(set(body.run_ids)) != len(body.run_ids):
        raise DomainError("VALIDATION_ERROR", "Comparison run IDs must be distinct", 422)
    runs = [run_out(db, user_id, get_run(db, user_id, run_id)) for run_id in body.run_ids]
    warnings: list[str] = []
    dataset_signatures = [
        tuple(sorted((str(link.dataset_version_id), link.role) for link in row.datasets))
        for row in runs
    ]
    if len(set(dataset_signatures)) > 1:
        warnings.append(
            "DATASET_VERSION_MISMATCH: recorded dataset versions/roles differ; results may not be directly comparable."
        )
    if any(not value for value in dataset_signatures):
        warnings.append(
            "DATASET_PROVENANCE_MISSING: one or more runs have no recorded dataset version."
        )
    hardware = [(row.gpu, row.cuda_version, row.pytorch_version) for row in runs]
    if len(set(hardware)) > 1:
        warnings.append(
            "HARDWARE_ENVIRONMENT_MISMATCH: speed/resource measurements require matching hardware and runtime."
        )
    if any(row.gpu is None for row in runs):
        warnings.append(
            "HARDWARE_UNKNOWN: missing hardware stays unknown; no benchmark equivalence is assumed."
        )
    if any(row.status != "COMPLETED" for row in runs):
        warnings.append(
            "INCOMPLETE_RUNS: some runs are not completed; shown values are recorded observations."
        )
    if any(row.model_version_id is None for row in runs):
        warnings.append("MODEL_VERSION_MISSING: model provenance is incomplete.")
    if body.metric_definition_ids is not None:
        definitions = [
            owned(db, user_id, MetricDefinition, value)
            for value in dict.fromkeys(body.metric_definition_ids)
        ]
    else:
        definitions = list(
            db.scalars(
                select(MetricDefinition)
                .join(
                    ExperimentMetric, ExperimentMetric.metric_definition_id == MetricDefinition.id
                )
                .where(
                    MetricDefinition.user_id == user_id,
                    ExperimentMetric.user_id == user_id,
                    ExperimentMetric.run_id.in_(body.run_ids),
                )
                .distinct()
                .order_by(MetricDefinition.name, MetricDefinition.evaluation_protocol)
            )
        )
    metrics = list(
        db.scalars(
            select(ExperimentMetric).where(
                ExperimentMetric.user_id == user_id,
                ExperimentMetric.run_id.in_(body.run_ids),
                ExperimentMetric.metric_definition_id.in_([row.id for row in definitions]),
            )
        )
    )
    protocol_groups: dict[str, set[str]] = {}
    for definition in definitions:
        protocol_groups.setdefault(definition.name, set()).add(definition.evaluation_protocol)
    if any(len(values) > 1 for values in protocol_groups.values()):
        warnings.append(
            "METRIC_PROTOCOL_MISMATCH: same-name definitions with different protocols are separate comparison rows."
        )
    if not metrics:
        # Protocol identity remains separate even when numeric labels match.
        warnings.append("NO_RECORDED_METRICS: no values or curves are invented.")
    semantic_groups: dict[str, set[tuple[str | None, bool]]] = {}
    for definition in definitions:
        semantic_groups.setdefault(definition.name, set()).add(
            (definition.unit, definition.higher_is_better)
        )
    if any(len(values) > 1 for values in semantic_groups.values()):
        warnings.append(
            "METRIC_SEMANTICS_MISMATCH: same-name metrics have differing units or optimization directions and remain separate rows."
        )
    result: list[schema.ComparisonMetric] = []
    for definition in definitions:
        matching = [row for row in metrics if row.metric_definition_id == definition.id]
        splits = sorted({row.split_name for row in matching}) or ["all"]
        for split in splits:
            axes = {
                "STEP" if row.step is not None else "EPOCH"
                for row in matching
                if row.split_name == split and row.location_key != "SUMMARY"
            }
            if len(axes) > 1:
                warnings.append(
                    f"CURVE_AXIS_MIXED: metric {definition.id}, split {split} has step and epoch-only coordinates; they are not interchangeable."
                )
            values: list[schema.ComparisonValue] = []
            series: list[schema.ComparisonSeries] = []
            for run in runs:
                rows = [row for row in matching if row.run_id == run.id and row.split_name == split]
                summary = next((row for row in rows if row.location_key == "SUMMARY"), None)
                observed = [row for row in rows if row.is_best] or rows
                selected = summary or (
                    (
                        max(observed, key=lambda row: float(row.value_text))
                        if definition.higher_is_better
                        else min(observed, key=lambda row: float(row.value_text))
                    )
                    if observed
                    else None
                )
                if selected is None:
                    warnings.append(
                        f"METRIC_MISSING: run {run.id}, metric {definition.id}, split {split} has no recorded value."
                    )
                elif summary is None:
                    warnings.append(
                        f"CURVE_OBSERVED_VALUE: run {run.id}, metric {definition.id}, split {split} uses a recorded curve value because no summary was recorded."
                    )
                values.append(
                    schema.ComparisonValue(
                        run_id=run.id, value=float(selected.value_text) if selected else None
                    )
                )
                curve = sorted(
                    [row for row in rows if row.location_key != "SUMMARY"],
                    key=lambda row: (row.step if row.step is not None else row.epoch or 0, row.id),
                )
                series.append(
                    schema.ComparisonSeries(
                        run_id=run.id,
                        points=[
                            schema.ComparisonPoint(
                                step=row.step, epoch=row.epoch, value=float(row.value_text)
                            )
                            for row in curve
                        ],
                    )
                )
            result.append(
                schema.ComparisonMetric(
                    metric_definition=schema.MetricDefinitionOut.model_validate(definition),
                    split_name=split,
                    values=values,
                    series=series,
                )
            )
    return schema.RunComparisonOut(
        runs=runs, warnings=list(dict.fromkeys(warnings)), metrics=result
    )
