"""Owner registries; all scientific version fields are create-only."""

import math
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import experiments as schema
from app.errors import DomainError
from app.models import (
    Attachment,
    CodeRepository,
    Dataset,
    DatasetClass,
    DatasetLocation,
    DatasetModality,
    DatasetSplit,
    DatasetVersion,
    Experiment,
    ExperimentRun,
    Hypothesis,
    Modality,
    Model,
    ModelComponent,
    ModelModality,
    ModelVersion,
    RepositoryBinding,
    ResearchEvent,
    ResearchProject,
    ResearchQuestion,
)
from app.services.common import register_entity
from app.services.papers import get_paper


def owned[T](
    db: Session, user_id: uuid.UUID, model: type[T], record_id: uuid.UUID, *, lock: bool = False
) -> T:
    query = select(model).where(model.id == record_id, model.user_id == user_id)  # type: ignore[attr-defined]
    if lock:
        query = query.with_for_update()
    record = db.scalar(query)
    if record is None:
        raise DomainError("NOT_FOUND", "Owned scientific record not found", 404)
    return record


def page(
    db: Session, user_id: uuid.UUID, model: Any, limit: int, offset: int, *filters: Any
) -> dict[str, Any]:
    conditions = (model.user_id == user_id, *filters)
    total = db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    ordering = (
        [model.changed_at.desc(), model.id.desc()] if hasattr(model, "changed_at") else [model.id]
    )
    rows: list[Any] = list(
        db.scalars(select(model).where(*conditions).order_by(*ordering).limit(limit).offset(offset))
    )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def commit[T](db: Session, record: T) -> T:
    try:
        db.commit()
        db.refresh(record)
        return record
    except IntegrityError as error:
        db.rollback()
        raise DomainError(
            "CONFLICT", "Scientific identity already exists or a referenced record changed", 409
        ) from error


def _finish_write[T](db: Session, record: T, persist: bool) -> T:
    """Allow a larger application transaction to own the final commit."""
    if persist:
        return commit(db, record)
    db.flush()
    return record


def nonempty(value: str) -> str:
    if not value.strip():
        raise DomainError("VALIDATION_ERROR", "Scientific labels cannot be empty", 422)
    return value.strip()


def project_question(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID, question_id: uuid.UUID | None
) -> None:
    owned(db, user_id, ResearchProject, project_id)
    if question_id is not None:
        question = db.scalar(
            select(ResearchQuestion).where(
                ResearchQuestion.id == question_id, ResearchQuestion.project_id == project_id
            )
        )
        if question is None:
            raise DomainError("NOT_FOUND", "Research question does not belong to this project", 404)


def attachment(db: Session, user_id: uuid.UUID, attachment_id: uuid.UUID) -> Attachment:
    record = owned(db, user_id, Attachment, attachment_id)
    if record.deleted_at is not None:
        raise DomainError("NOT_FOUND", "Attachment is deleted", 404)
    return record


def _modality_ids(db: Session, user_id: uuid.UUID, codes: list[str]) -> list[uuid.UUID]:
    normalized = [value.strip().upper() for value in codes]
    if len(set(normalized)) != len(normalized) or any(
        not re.fullmatch(r"[A-Z0-9_-]{1,40}", code) for code in normalized
    ):
        raise DomainError(
            "VALIDATION_ERROR", "Modality codes must be distinct uppercase words", 422
        )
    result: list[uuid.UUID] = []
    for code in normalized:
        item = db.scalar(select(Modality).where(Modality.user_id == user_id, Modality.code == code))
        if item is None:
            item = Modality(user_id=user_id, code=code, display_name=code)
            db.add(item)
            db.flush()
        result.append(item.id)
    return result


def _set_modalities(
    db: Session, user_id: uuid.UUID, record: Dataset | Model, codes: list[str]
) -> None:
    ids = _modality_ids(db, user_id, codes)
    link = DatasetModality if isinstance(record, Dataset) else ModelModality
    key = "dataset_id" if isinstance(record, Dataset) else "model_id"
    db.execute(delete(link).where(getattr(link, key) == record.id, link.user_id == user_id))
    for modality_id in ids:
        db.add(link(user_id=user_id, modality_id=modality_id, **{key: record.id}))


def registry_out(
    db: Session, user_id: uuid.UUID, record: Dataset | Model
) -> schema.DatasetOut | schema.ModelOut:
    link = DatasetModality if isinstance(record, Dataset) else ModelModality
    key = DatasetModality.dataset_id if isinstance(record, Dataset) else ModelModality.model_id
    modalities = list(
        db.scalars(
            select(Modality.code)
            .join(link, link.modality_id == Modality.id)
            .where(
                key == record.id,
                link.user_id == user_id,
                Modality.user_id == user_id,
            )
            .order_by(Modality.code)
        )
    )
    cls = schema.DatasetOut if isinstance(record, Dataset) else schema.ModelOut
    values = {name: getattr(record, name) for name in cls.model_fields if name != "modalities"}
    return cls.model_validate({**values, "modalities": modalities})


def create_registry(
    db: Session,
    user_id: uuid.UUID,
    body: schema.DatasetCreate | schema.ModelCreate,
    *,
    commit: bool = True,
) -> Dataset | Model:
    is_dataset = isinstance(body, schema.DatasetCreate)
    if not is_dataset and body.paper_id is not None:  # type: ignore[union-attr]
        get_paper(db, user_id, body.paper_id)  # type: ignore[union-attr]
    values = body.model_dump(exclude={"modalities"})
    values["name"], values["task"] = nonempty(values["name"]), nonempty(values["task"])
    try:
        record = (Dataset if is_dataset else Model)(
            id=register_entity(db, user_id, "dataset" if is_dataset else "model"),
            user_id=user_id,
            **values,
        )
        db.add(record)
        db.flush()
        _set_modalities(db, user_id, record, body.modalities)
        return _finish_write(db, record, commit)
    except Exception:
        db.rollback()
        raise


def patch_registry(
    db: Session,
    user_id: uuid.UUID,
    record: Dataset | Model,
    body: schema.DatasetPatch | schema.ModelPatch,
) -> Dataset | Model:
    values = body.model_dump(exclude_unset=True)
    if any(
        values.get(key, "present") is None for key in ("name", "task", "modalities", "archived")
    ):
        raise DomainError("VALIDATION_ERROR", "Required registry metadata cannot be null", 422)
    if isinstance(record, Model) and values.get("paper_id") is not None:
        get_paper(db, user_id, values["paper_id"])
    try:
        if "modalities" in values:
            _set_modalities(db, user_id, record, values.pop("modalities"))
        if "archived" in values:
            record.archived_at = datetime.now(UTC) if values.pop("archived") else None
        for key, value in values.items():
            setattr(record, key, nonempty(value) if key in {"name", "task"} else value)
        return commit(db, record)
    except Exception:
        db.rollback()
        raise


def dataset_version_out(
    db: Session, user_id: uuid.UUID, version: DatasetVersion
) -> schema.DatasetVersionOut:
    values = {
        name: getattr(version, name)
        for name in schema.DatasetVersionOut.model_fields
        if name not in {"classes", "splits", "locations"}
    }
    values.update(
        {
            "classes": list(
                db.scalars(
                    select(DatasetClass)
                    .where(
                        DatasetClass.user_id == user_id,
                        DatasetClass.dataset_version_id == version.id,
                    )
                    .order_by(DatasetClass.class_index)
                )
            ),
            "splits": list(
                db.scalars(
                    select(DatasetSplit)
                    .where(
                        DatasetSplit.user_id == user_id,
                        DatasetSplit.dataset_version_id == version.id,
                    )
                    .order_by(DatasetSplit.split_name)
                )
            ),
            "locations": list(
                db.scalars(
                    select(DatasetLocation)
                    .where(
                        DatasetLocation.user_id == user_id,
                        DatasetLocation.dataset_version_id == version.id,
                    )
                    .order_by(DatasetLocation.id)
                )
            ),
        }
    )
    return schema.DatasetVersionOut.model_validate(values)


def create_dataset_version(
    db: Session,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID,
    body: schema.DatasetVersionCreate,
    *,
    commit: bool = True,
) -> DatasetVersion:
    dataset = owned(db, user_id, Dataset, dataset_id)
    if dataset.archived_at is not None:
        raise DomainError("REGISTRY_ARCHIVED", "Unarchive the dataset before adding a version", 409)
    if len({row.class_index for row in body.classes}) != len(body.classes) or len(
        {row.split_name for row in body.splits}
    ) != len(body.splits):
        raise DomainError(
            "VALIDATION_ERROR", "Dataset class indices and split names must be unique", 422
        )
    try:
        version = DatasetVersion(
            id=register_entity(db, user_id, "dataset_version"),
            user_id=user_id,
            dataset_id=dataset_id,
            **body.model_dump(exclude={"classes", "splits", "locations"}),
        )
        version.version = nonempty(version.version)
        db.add(version)
        db.flush()
        for class_spec in body.classes:
            db.add(
                DatasetClass(
                    user_id=user_id, dataset_version_id=version.id, **class_spec.model_dump()
                )
            )
        for split_spec in body.splits:
            db.add(
                DatasetSplit(
                    user_id=user_id, dataset_version_id=version.id, **split_spec.model_dump()
                )
            )
        for location_spec in body.locations:
            db.add(
                DatasetLocation(
                    user_id=user_id, dataset_version_id=version.id, **location_spec.model_dump()
                )
            )
        return _finish_write(db, version, commit)
    except Exception:
        db.rollback()
        raise


def model_version_out(
    db: Session, user_id: uuid.UUID, version: ModelVersion
) -> schema.ModelVersionOut:
    values = {
        name: getattr(version, name)
        for name in schema.ModelVersionOut.model_fields
        if name != "components"
    }
    values["components"] = list(
        db.scalars(
            select(ModelComponent)
            .where(ModelComponent.user_id == user_id, ModelComponent.model_version_id == version.id)
            .order_by(ModelComponent.sort_order, ModelComponent.id)
        )
    )
    return schema.ModelVersionOut.model_validate(values)


def create_model_version(
    db: Session,
    user_id: uuid.UUID,
    model_id: uuid.UUID,
    body: schema.ModelVersionCreate,
    *,
    commit: bool = True,
) -> ModelVersion:
    model = owned(db, user_id, Model, model_id)
    if model.archived_at is not None:
        raise DomainError("REGISTRY_ARCHIVED", "Unarchive the model before adding a version", 409)
    if body.code_repository_id is not None:
        owned(db, user_id, CodeRepository, body.code_repository_id)
    if body.checkpoint_attachment_id is not None:
        attachment(db, user_id, body.checkpoint_attachment_id)
    values = body.model_dump(exclude={"components"})
    for key in ("flops", "fps"):
        if values[key] is not None:
            if not math.isfinite(values[key]):
                raise DomainError("VALIDATION_ERROR", "Model numeric metadata must be finite", 422)
            values[key] = Decimal(str(values[key]))
    try:
        version = ModelVersion(
            id=register_entity(db, user_id, "model_version"),
            user_id=user_id,
            model_id=model_id,
            **values,
        )
        version.version = nonempty(version.version)
        db.add(version)
        db.flush()
        for row in body.components:
            db.add(ModelComponent(user_id=user_id, model_version_id=version.id, **row.model_dump()))
        return _finish_write(db, version, commit)
    except Exception:
        db.rollback()
        raise


def create_repository(
    db: Session,
    user_id: uuid.UUID,
    body: schema.CodeRepositoryCreate,
    *,
    commit: bool = True,
) -> CodeRepository:
    record = CodeRepository(
        id=register_entity(db, user_id, "code_repository"), user_id=user_id, **body.model_dump()
    )
    record.name = nonempty(record.name)
    db.add(record)
    return _finish_write(db, record, commit)


def create_hypothesis(db: Session, user_id: uuid.UUID, body: schema.HypothesisCreate) -> Hypothesis:
    project_question(db, user_id, body.project_id, body.question_id)
    record = Hypothesis(
        id=register_entity(db, user_id, "hypothesis"), user_id=user_id, **body.model_dump()
    )
    record.statement = nonempty(record.statement)
    db.add(record)
    return commit(db, record)


def patch_repository(
    db: Session, user_id: uuid.UUID, repository_id: uuid.UUID, body: schema.CodeRepositoryPatch
) -> CodeRepository:
    record = owned(db, user_id, CodeRepository, repository_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    provenance = {"provider_key", "external_id", "url", "local_uri"}
    changed_source = any(
        getattr(record, key) != changes[key] for key in provenance & changes.keys()
    )
    referenced = (
        db.scalar(
            select(ExperimentRun.id)
            .where(
                ExperimentRun.user_id == user_id, ExperimentRun.code_repository_id == repository_id
            )
            .limit(1)
        )
        is not None
    )
    referenced |= (
        db.scalar(
            select(ModelVersion.id)
            .where(
                ModelVersion.user_id == user_id, ModelVersion.code_repository_id == repository_id
            )
            .limit(1)
        )
        is not None
    )
    referenced |= (
        db.scalar(
            select(RepositoryBinding.id)
            .where(
                RepositoryBinding.user_id == user_id,
                RepositoryBinding.code_repository_id == repository_id,
            )
            .limit(1)
        )
        is not None
    )
    if changed_source and referenced:
        raise DomainError(
            "REPOSITORY_PROVENANCE_FROZEN",
            "Referenced repository identities require a new repository record",
            409,
        )
    if changes.get("name", "valid") is None or changes.get("archived", False) is None:
        raise DomainError("VALIDATION_ERROR", "Repository name/archive flag cannot be null", 422)
    if "archived" in changes:
        record.archived_at = datetime.now(UTC) if changes.pop("archived") else None
    for key, value in changes.items():
        setattr(record, key, nonempty(value) if key == "name" else value)
    return commit(db, record)


def patch_hypothesis(
    db: Session, user_id: uuid.UUID, hypothesis_id: uuid.UUID, body: schema.HypothesisPatch
) -> Hypothesis:
    record = owned(db, user_id, Hypothesis, hypothesis_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    if {"statement", "test_plan"} & changes.keys() and db.scalar(
        select(Experiment.id)
        .where(
            Experiment.user_id == user_id,
            Experiment.hypothesis_id == hypothesis_id,
        )
        .limit(1)
    ) is not None:
        raise DomainError(
            "HYPOTHESIS_PROVENANCE_FROZEN",
            "A referenced hypothesis must be corrected as a new hypothesis",
            409,
        )
    if changes.get("status") in {"SUPPORTED", "REFUTED", "INCONCLUSIVE"} and not changes.get(
        "result_notes"
    ):
        raise DomainError(
            "JUDGEMENT_REQUIRED",
            "Record the owner's evidence judgement separately from run completion",
            422,
        )
    previous = record.status
    if changes.get("statement", "valid") is None or changes.get("status", "valid") is None:
        raise DomainError("VALIDATION_ERROR", "Hypothesis statement/status cannot be null", 422)
    for key, value in changes.items():
        setattr(record, key, value)
    if record.status != previous:
        db.add(
            ResearchEvent(
                event_id=uuid.uuid4(),
                user_id=user_id,
                event_type="hypothesis.assessed",
                schema_version="1.0",
                occurred_at=datetime.now(UTC),
                source="owner",
                payload={
                    "hypothesis_id": str(record.id),
                    "from_status": previous,
                    "to_status": record.status,
                    "result_notes": record.result_notes,
                    "project_id": str(record.project_id),
                },
            )
        )
    return commit(db, record)
