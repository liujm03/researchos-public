"""Versioned dataset/model, repository and hypothesis owner routes."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.domain import experiments as schema
from app.models import (
    CodeRepository,
    Dataset,
    DatasetVersion,
    Hypothesis,
    Modality,
    Model,
    ModelVersion,
)
from app.services import experiment_registries as service

router = APIRouter(tags=["experiment-registries"])


@router.get("/modalities", response_model=schema.ModalityPage)
def modalities(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ModalityPage:
    return schema.ModalityPage.model_validate(
        service.page(db, context.user.id, Modality, limit, offset)
    )


@router.get("/datasets", response_model=schema.DatasetPage)
def datasets(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_archived: bool = False,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.DatasetPage:
    result = service.page(
        db,
        context.user.id,
        Dataset,
        limit,
        offset,
        *([] if include_archived else [Dataset.archived_at.is_(None)]),
    )
    result["items"] = [service.registry_out(db, context.user.id, row) for row in result["items"]]
    return schema.DatasetPage.model_validate(result)


@router.post("/datasets", response_model=schema.DatasetOut, status_code=201)
def create_dataset(
    body: schema.DatasetCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.DatasetOut:
    return schema.DatasetOut.model_validate(
        service.registry_out(
            db, context.user.id, service.create_registry(db, context.user.id, body)
        )
    )


@router.get("/datasets/{dataset_id}", response_model=schema.DatasetOut)
def dataset(
    dataset_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.DatasetOut:
    return schema.DatasetOut.model_validate(
        service.registry_out(
            db, context.user.id, service.owned(db, context.user.id, Dataset, dataset_id)
        )
    )


@router.patch("/datasets/{dataset_id}", response_model=schema.DatasetOut)
def patch_dataset(
    dataset_id: uuid.UUID,
    body: schema.DatasetPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.DatasetOut:
    row = service.patch_registry(
        db, context.user.id, service.owned(db, context.user.id, Dataset, dataset_id), body
    )
    return schema.DatasetOut.model_validate(service.registry_out(db, context.user.id, row))


@router.delete("/datasets/{dataset_id}", response_model=schema.DatasetOut)
def archive_dataset(
    dataset_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.DatasetOut:
    return patch_dataset(dataset_id, schema.DatasetPatch(archived=True), context, db)


@router.get("/datasets/{dataset_id}/versions", response_model=schema.DatasetVersionPage)
def dataset_versions(
    dataset_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.DatasetVersionPage:
    service.owned(db, context.user.id, Dataset, dataset_id)
    result = service.page(
        db, context.user.id, DatasetVersion, limit, offset, DatasetVersion.dataset_id == dataset_id
    )
    result["items"] = [
        service.dataset_version_out(db, context.user.id, row) for row in result["items"]
    ]
    return schema.DatasetVersionPage.model_validate(result)


@router.post(
    "/datasets/{dataset_id}/versions", response_model=schema.DatasetVersionOut, status_code=201
)
def create_dataset_version(
    dataset_id: uuid.UUID,
    body: schema.DatasetVersionCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.DatasetVersionOut:
    return service.dataset_version_out(
        db, context.user.id, service.create_dataset_version(db, context.user.id, dataset_id, body)
    )


@router.get("/dataset-versions/{version_id}", response_model=schema.DatasetVersionOut)
def dataset_version(
    version_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.DatasetVersionOut:
    return service.dataset_version_out(
        db, context.user.id, service.owned(db, context.user.id, DatasetVersion, version_id)
    )


@router.get("/models", response_model=schema.ModelPage)
def models(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_archived: bool = False,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ModelPage:
    result = service.page(
        db,
        context.user.id,
        Model,
        limit,
        offset,
        *([] if include_archived else [Model.archived_at.is_(None)]),
    )
    result["items"] = [service.registry_out(db, context.user.id, row) for row in result["items"]]
    return schema.ModelPage.model_validate(result)


@router.post("/models", response_model=schema.ModelOut, status_code=201)
def create_model(
    body: schema.ModelCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ModelOut:
    return schema.ModelOut.model_validate(
        service.registry_out(
            db, context.user.id, service.create_registry(db, context.user.id, body)
        )
    )


@router.get("/models/{model_id}", response_model=schema.ModelOut)
def model(
    model_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ModelOut:
    return schema.ModelOut.model_validate(
        service.registry_out(
            db, context.user.id, service.owned(db, context.user.id, Model, model_id)
        )
    )


@router.patch("/models/{model_id}", response_model=schema.ModelOut)
def patch_model(
    model_id: uuid.UUID,
    body: schema.ModelPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ModelOut:
    row = service.patch_registry(
        db, context.user.id, service.owned(db, context.user.id, Model, model_id), body
    )
    return schema.ModelOut.model_validate(service.registry_out(db, context.user.id, row))


@router.delete("/models/{model_id}", response_model=schema.ModelOut)
def archive_model(
    model_id: uuid.UUID, context: AuthContext = Depends(csrf_context), db: Session = Depends(get_db)
) -> schema.ModelOut:
    return patch_model(model_id, schema.ModelPatch(archived=True), context, db)


@router.get("/models/{model_id}/versions", response_model=schema.ModelVersionPage)
def model_versions(
    model_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ModelVersionPage:
    service.owned(db, context.user.id, Model, model_id)
    result = service.page(
        db, context.user.id, ModelVersion, limit, offset, ModelVersion.model_id == model_id
    )
    result["items"] = [
        service.model_version_out(db, context.user.id, row) for row in result["items"]
    ]
    return schema.ModelVersionPage.model_validate(result)


@router.post("/models/{model_id}/versions", response_model=schema.ModelVersionOut, status_code=201)
def create_model_version(
    model_id: uuid.UUID,
    body: schema.ModelVersionCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.ModelVersionOut:
    return service.model_version_out(
        db, context.user.id, service.create_model_version(db, context.user.id, model_id, body)
    )


@router.get("/model-versions/{version_id}", response_model=schema.ModelVersionOut)
def model_version(
    version_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.ModelVersionOut:
    return service.model_version_out(
        db, context.user.id, service.owned(db, context.user.id, ModelVersion, version_id)
    )


@router.get("/code-repositories", response_model=schema.CodeRepositoryPage)
def repositories(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.CodeRepositoryPage:
    return schema.CodeRepositoryPage.model_validate(
        service.page(db, context.user.id, CodeRepository, limit, offset)
    )


@router.post("/code-repositories", response_model=schema.CodeRepositoryOut, status_code=201)
def create_repository(
    body: schema.CodeRepositoryCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.CodeRepositoryOut:
    return schema.CodeRepositoryOut.model_validate(
        service.create_repository(db, context.user.id, body)
    )


@router.get("/code-repositories/{repository_id}", response_model=schema.CodeRepositoryOut)
def repository(
    repository_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.CodeRepositoryOut:
    return schema.CodeRepositoryOut.model_validate(
        service.owned(db, context.user.id, CodeRepository, repository_id)
    )


@router.patch("/code-repositories/{repository_id}", response_model=schema.CodeRepositoryOut)
def patch_repository(
    repository_id: uuid.UUID,
    body: schema.CodeRepositoryPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.CodeRepositoryOut:
    return schema.CodeRepositoryOut.model_validate(
        service.patch_repository(db, context.user.id, repository_id, body)
    )


@router.delete("/code-repositories/{repository_id}", response_model=schema.CodeRepositoryOut)
def archive_repository(
    repository_id: uuid.UUID,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.CodeRepositoryOut:
    return patch_repository(repository_id, schema.CodeRepositoryPatch(archived=True), context, db)


@router.get("/hypotheses", response_model=schema.HypothesisPage)
def hypotheses(
    project_id: uuid.UUID | None = None,
    question_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.HypothesisPage:
    filters = []
    if project_id is not None:
        filters.append(Hypothesis.project_id == project_id)
    if question_id is not None:
        filters.append(Hypothesis.question_id == question_id)
    return schema.HypothesisPage.model_validate(
        service.page(db, context.user.id, Hypothesis, limit, offset, *filters)
    )


@router.post("/hypotheses", response_model=schema.HypothesisOut, status_code=201)
def create_hypothesis(
    body: schema.HypothesisCreate,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.HypothesisOut:
    return schema.HypothesisOut.model_validate(service.create_hypothesis(db, context.user.id, body))


@router.get("/hypotheses/{hypothesis_id}", response_model=schema.HypothesisOut)
def hypothesis(
    hypothesis_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.HypothesisOut:
    return schema.HypothesisOut.model_validate(
        service.owned(db, context.user.id, Hypothesis, hypothesis_id)
    )


@router.patch("/hypotheses/{hypothesis_id}", response_model=schema.HypothesisOut)
def patch_hypothesis(
    hypothesis_id: uuid.UUID,
    body: schema.HypothesisPatch,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.HypothesisOut:
    return schema.HypothesisOut.model_validate(
        service.patch_hypothesis(db, context.user.id, hypothesis_id, body)
    )
