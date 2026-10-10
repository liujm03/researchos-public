"""Experiment designs/runs, immutable metrics, artifacts and comparisons."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.domain import experiments as schema
from app.models import (
    Experiment,
    ExperimentArtifact,
    ExperimentMetric,
    ExperimentRun,
    ExperimentStatusEvent,
    MetricDefinition,
)
from app.services import experiments as service
from app.services.experiment_comparison import compare_runs
from app.services.experiment_registries import page

router = APIRouter(tags=["experiments"])


@router.get("/experiments", response_model=schema.ExperimentPage)
def experiments(
    project_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentPage:
    return schema.ExperimentPage.model_validate(
        page(
            db,
            context.user.id,
            Experiment,
            limit,
            offset,
            *([] if project_id is None else [Experiment.project_id == project_id]),
        )
    )


@router.post("/experiments", response_model=schema.ExperimentOut, status_code=201)
def create_experiment(
    body: schema.ExperimentCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentOut:
    return schema.ExperimentOut.model_validate(service.create_experiment(db, context.user.id, body))


@router.post("/experiments/compare", response_model=schema.RunComparisonOut)
def compare(
    body: schema.RunComparisonRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.RunComparisonOut:
    return compare_runs(db, context.user.id, body)


@router.get("/experiments/{experiment_id}", response_model=schema.ExperimentOut)
def experiment(
    experiment_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentOut:
    return schema.ExperimentOut.model_validate(
        service.get_experiment(db, context.user.id, experiment_id)
    )


@router.patch("/experiments/{experiment_id}", response_model=schema.ExperimentOut)
def patch_experiment(
    experiment_id: uuid.UUID,
    body: schema.ExperimentPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentOut:
    return schema.ExperimentOut.model_validate(
        service.patch_experiment(db, context.user.id, experiment_id, body)
    )


@router.delete("/experiments/{experiment_id}", response_model=schema.ExperimentOut)
def archive_experiment(
    experiment_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentOut:
    return patch_experiment(
        experiment_id,
        schema.ExperimentPatch(status="ARCHIVED", reason="Owner archived experiment"),
        context,
        db,
    )


@router.get("/experiments/{experiment_id}/runs", response_model=schema.ExperimentRunPage)
def experiment_runs(
    experiment_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentRunPage:
    service.get_experiment(db, context.user.id, experiment_id)
    return runs(experiment_id, limit, offset, context, db)


@router.post(
    "/experiments/{experiment_id}/runs", response_model=schema.ExperimentRunOut, status_code=201
)
def create_run(
    experiment_id: uuid.UUID,
    body: schema.ExperimentRunCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentRunOut:
    return service.run_out(
        db, context.user.id, service.create_run(db, context.user.id, experiment_id, body)
    )


@router.get("/experiment-runs", response_model=schema.ExperimentRunPage)
def runs(
    experiment_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentRunPage:
    result = page(
        db,
        context.user.id,
        ExperimentRun,
        limit,
        offset,
        *([] if experiment_id is None else [ExperimentRun.experiment_id == experiment_id]),
    )
    result["items"] = [service.run_out(db, context.user.id, row) for row in result["items"]]
    return schema.ExperimentRunPage.model_validate(result)


@router.get("/experiment-runs/{run_id}", response_model=schema.ExperimentRunOut)
def run(
    run_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentRunOut:
    return service.run_out(db, context.user.id, service.get_run(db, context.user.id, run_id))


@router.patch("/experiment-runs/{run_id}", response_model=schema.ExperimentRunOut)
def patch_run(
    run_id: uuid.UUID,
    body: schema.ExperimentRunPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentRunOut:
    return service.run_out(
        db, context.user.id, service.patch_run(db, context.user.id, run_id, body)
    )


@router.get("/metric-definitions", response_model=schema.MetricDefinitionPage)
def metric_definitions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.MetricDefinitionPage:
    return schema.MetricDefinitionPage.model_validate(
        page(db, context.user.id, MetricDefinition, limit, offset)
    )


@router.post("/metric-definitions", response_model=schema.MetricDefinitionOut, status_code=201)
def create_metric_definition(
    body: schema.MetricDefinitionCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.MetricDefinitionOut:
    return schema.MetricDefinitionOut.model_validate(
        service.create_metric_definition(db, context.user.id, body)
    )


@router.get("/experiment-runs/{run_id}/metrics", response_model=schema.ExperimentMetricPage)
def metrics(
    run_id: uuid.UUID,
    metric_definition_id: uuid.UUID | None = None,
    split_name: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentMetricPage:
    service.get_run(db, context.user.id, run_id)
    filters = [ExperimentMetric.run_id == run_id]
    if metric_definition_id is not None:
        filters.append(ExperimentMetric.metric_definition_id == metric_definition_id)
    if split_name is not None:
        filters.append(ExperimentMetric.split_name == split_name)
    result = page(db, context.user.id, ExperimentMetric, limit, offset, *filters)
    result["items"] = [service.metric_out(row) for row in result["items"]]
    return schema.ExperimentMetricPage.model_validate(result)


@router.post("/experiment-runs/{run_id}/metrics", response_model=schema.MetricBatchOut)
def record_metrics(
    run_id: uuid.UUID,
    body: schema.MetricBatchCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.MetricBatchOut:
    return service.record_metrics(db, context.user.id, run_id, body)


@router.get("/experiment-runs/{run_id}/artifacts", response_model=schema.ExperimentArtifactPage)
def artifacts(
    run_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentArtifactPage:
    service.get_run(db, context.user.id, run_id)
    result = page(
        db, context.user.id, ExperimentArtifact, limit, offset, ExperimentArtifact.run_id == run_id
    )
    result["items"] = [service.artifact_out(db, context.user.id, row) for row in result["items"]]
    return schema.ExperimentArtifactPage.model_validate(result)


@router.post(
    "/experiment-runs/{run_id}/artifacts",
    response_model=schema.ExperimentArtifactOut,
    status_code=201,
)
def attach_artifact(
    run_id: uuid.UUID,
    body: schema.ExperimentArtifactCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentArtifactOut:
    return service.artifact_out(
        db,
        context.user.id,
        service.attach_artifact(
            db, context.user.id, run_id, body.attachment_id, body.artifact_type, body.description
        ),
    )


@router.get(
    "/experiment-runs/{run_id}/status-history", response_model=schema.ExperimentStatusEventPage
)
def run_history(
    run_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentStatusEventPage:
    service.get_run(db, context.user.id, run_id)
    return schema.ExperimentStatusEventPage.model_validate(
        page(
            db,
            context.user.id,
            ExperimentStatusEvent,
            limit,
            offset,
            ExperimentStatusEvent.run_id == run_id,
        )
    )


@router.get(
    "/experiments/{experiment_id}/status-history", response_model=schema.ExperimentStatusEventPage
)
def experiment_history(
    experiment_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ExperimentStatusEventPage:
    service.get_experiment(db, context.user.id, experiment_id)
    return schema.ExperimentStatusEventPage.model_validate(
        page(
            db,
            context.user.id,
            ExperimentStatusEvent,
            limit,
            offset,
            ExperimentStatusEvent.experiment_id == experiment_id,
        )
    )
