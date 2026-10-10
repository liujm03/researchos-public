"""Immutable baseline declarations; measured files are materials, never execution proof."""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas_baselines as dto
from app.core.config import get_settings
from app.domain.baselines import (
    BaselineAssetObservation as ProbeObservation,
)
from app.domain.baselines import (
    BaselineAssetProbeProvider,
    BaselineProbeAsset,
    BaselineProbeRequest,
    BaselineProbeResult,
)
from app.domain.project_sources import ProjectSourceFile as SourceFile
from app.errors import DomainError
from app.models import (
    Dataset,
    DatasetClass,
    DatasetModality,
    DatasetSplit,
    DatasetVersion,
    Modality,
    Model,
    ModelComponent,
    ModelModality,
    ModelVersion,
    Paper,
)
from app.models_baselines import (
    Baseline,
    BaselineAsset,
    BaselineAssetObservation,
    BaselineDatasetBinding,
    BaselineMaterialCheck,
    BaselineVersion,
)
from app.models_project_sources import (
    ProjectPathBinding,
    ProjectSourceFile,
    ProjectSourceJob,
    ProjectSourcePlan,
    ProjectSourcePlanFile,
)
from app.services import project_sources
from app.services.common import cursor_filter, encode_cursor
from app.services.projects import get_project
from app.services.research_briefs import digest

ROLES = {"CODE", "CONFIG", "ENVIRONMENT_LOCK", "EVALUATOR", "WEIGHTS", "DATA", "SPLIT_MANIFEST"}


def now() -> datetime:
    return datetime.now(UTC)


def capability() -> dto.BaselineCapabilityOut:
    root = get_settings().project_provision_managed_root
    return dto.BaselineCapabilityOut(
        materials_check_available=bool(root and Path(root).is_absolute()),
        detail="Catalog and readonly material verification are implemented. No controlled Runner, smoke verification or locked-protocol execution is implemented; environment installation and scientific validity are not established by material checks.",
    )


def _get(
    db: Session,
    model: Any,
    owner: uuid.UUID,
    identity: uuid.UUID,
    project: uuid.UUID | None = None,
    lock: bool = False,
) -> Any:
    query = select(model).where(model.id == identity, model.user_id == owner)
    if project is not None:
        query = query.where(model.project_id == project)
    row = db.scalar(
        (query.with_for_update() if lock else query).execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "Owned baseline input or record not found", 404)
    return row


def get_baseline(db: Session, owner: uuid.UUID, identity: uuid.UUID) -> Baseline:
    return cast(Baseline, _get(db, Baseline, owner, identity))


def get_version(db: Session, owner: uuid.UUID, identity: uuid.UUID) -> BaselineVersion:
    return cast(BaselineVersion, _get(db, BaselineVersion, owner, identity))


def get_check(
    db: Session, owner: uuid.UUID, version: uuid.UUID, identity: uuid.UUID
) -> BaselineMaterialCheck:
    row: BaselineMaterialCheck = _get(db, BaselineMaterialCheck, owner, identity)
    if row.version_id != version:
        raise DomainError("NOT_FOUND", "Owned version material check not found", 404)
    return row


def assets(db: Session, version: BaselineVersion) -> list[BaselineAsset]:
    return list(
        db.scalars(
            select(BaselineAsset)
            .where(
                BaselineAsset.version_id == version.id,
                BaselineAsset.project_id == version.project_id,
                BaselineAsset.user_id == version.user_id,
            )
            .order_by(BaselineAsset.role, BaselineAsset.source_file_id, BaselineAsset.id)
            .execution_options(populate_existing=True)
        )
    )


def datasets(db: Session, version: BaselineVersion) -> list[BaselineDatasetBinding]:
    return list(
        db.scalars(
            select(BaselineDatasetBinding)
            .where(
                BaselineDatasetBinding.version_id == version.id,
                BaselineDatasetBinding.project_id == version.project_id,
                BaselineDatasetBinding.user_id == version.user_id,
            )
            .order_by(BaselineDatasetBinding.dataset_version_id)
            .execution_options(populate_existing=True)
        )
    )


def _columns(row: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in exclude
    }


def _modalities(
    db: Session,
    owner: uuid.UUID,
    model: type[ModelModality] | type[DatasetModality],
    identity: uuid.UUID,
) -> list[str]:
    column = getattr(model, "model_id" if model is ModelModality else "dataset_id")
    return list(
        db.scalars(
            select(Modality.code)
            .join(model, model.modality_id == Modality.id)
            .where(column == identity, model.user_id == owner, Modality.user_id == owner)
            .order_by(Modality.code)
        )
    )


def model_hash(db: Session, owner: uuid.UUID, row: ModelVersion) -> str:
    parent: Model = _get(db, Model, owner, row.model_id)
    components = list(
        db.scalars(
            select(ModelComponent)
            .where(ModelComponent.model_version_id == row.id, ModelComponent.user_id == owner)
            .order_by(ModelComponent.sort_order, ModelComponent.id)
            .execution_options(populate_existing=True)
        )
    )
    return digest(
        {
            "version": _columns(row, ("created_at",)),
            "parent": {
                key: getattr(parent, key)
                for key in ("task", "family", "architecture", "source", "paper_id")
            },
            "components": [_columns(item) for item in components],
            "modalities": _modalities(db, owner, ModelModality, parent.id),
        }
    )


def dataset_snapshot(
    db: Session, owner: uuid.UUID, identity: uuid.UUID
) -> tuple[DatasetVersion, Dataset, str]:
    version: DatasetVersion = _get(db, DatasetVersion, owner, identity)
    parent: Dataset = _get(db, Dataset, owner, version.dataset_id)
    classes = list(
        db.scalars(
            select(DatasetClass)
            .where(DatasetClass.dataset_version_id == identity, DatasetClass.user_id == owner)
            .order_by(DatasetClass.class_index)
            .execution_options(populate_existing=True)
        )
    )
    splits = list(
        db.scalars(
            select(DatasetSplit)
            .where(DatasetSplit.dataset_version_id == identity, DatasetSplit.user_id == owner)
            .order_by(DatasetSplit.split_name)
            .execution_options(populate_existing=True)
        )
    )
    return (
        version,
        parent,
        digest(
            {
                "version": _columns(version, ("created_at",)),
                "license": parent.license,
                "task": parent.task,
                "source": parent.source,
                "modalities": _modalities(db, owner, DatasetModality, parent.id),
                "name": parent.name,
                "classes": [_columns(row) for row in classes],
                "splits": [_columns(row) for row in splits],
            }
        ),
    )


def version_hash(db: Session, row: BaselineVersion) -> str:
    return digest(
        {
            "schema": "baseline-version-v1",
            "version": _columns(row, ("sha256", "created_at")),
            "assets": [_columns(item) for item in assets(db, row)],
            "datasets": [_columns(item) for item in datasets(db, row)],
        }
    )


def _intact(db: Session, row: BaselineVersion) -> None:
    if row.sha256 != version_hash(db, row):
        raise DomainError(
            "BASELINE_VERSION_CHANGED", "Frozen baseline declaration hash is invalid", 409
        )

    if row.parent_version_id is not None:
        parent = get_version(db, row.user_id, row.parent_version_id)
        if (
            parent.baseline_id != row.baseline_id
            or parent.project_id != row.project_id
            or parent.sha256 != row.parent_sha256
            or parent.sha256 != version_hash(db, parent)
        ):
            raise DomainError(
                "BASELINE_PARENT_CHANGED",
                "Recorded parent version or its frozen declaration changed",
                409,
            )


def _source(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    file_id: uuid.UUID,
    cache: dict[uuid.UUID, tuple[ProjectSourceJob, ProjectSourcePlan, ProjectPathBinding]]
    | None = None,
) -> tuple[ProjectSourceFile, ProjectSourceJob, ProjectSourcePlan, ProjectSourcePlanFile]:
    checkpoint: ProjectSourceFile = _get(db, ProjectSourceFile, owner, file_id, project)
    if cache is not None and checkpoint.job_id in cache:
        job, plan, binding = cache[checkpoint.job_id]
    else:
        job = project_sources.get_job(db, owner, project, checkpoint.job_id)
        plan = project_sources.get_plan(db, owner, project, job.plan_id)
        binding = project_sources._validate(db, plan)
        if cache is not None:
            cache[checkpoint.job_id] = (job, plan, binding)
    file = db.scalar(
        select(ProjectSourcePlanFile)
        .where(
            ProjectSourcePlanFile.plan_id == checkpoint.plan_id,
            ProjectSourcePlanFile.file_key_sha256 == checkpoint.file_key_sha256,
            ProjectSourcePlanFile.project_id == project,
            ProjectSourcePlanFile.user_id == owner,
        )
        .execution_options(populate_existing=True)
    )
    if (
        job.status != "COMPLETED"
        or not job.receipt_sha256
        or not job.receipt_path
        or job.verified_at is None
        or binding.state != "ACTIVE"
        or binding.approved_by != owner
        or binding.approved_hash != binding.scope_sha256
        or plan.state != "APPROVED"
        or plan.approved_by != owner
        or plan.approved_hash != plan.plan_sha256
        or checkpoint.status not in {"COPIED", "REUSED"}
        or file is None
        or (checkpoint.actual_sha256, checkpoint.actual_size_bytes, checkpoint.relative_path)
        != (file.sha256, file.size_bytes, binding.relative_path + "/" + file.path)
    ):
        raise DomainError(
            "BASELINE_SOURCE_NOT_COMPLETE",
            "A completed exact approved source checkpoint is required",
            409,
        )
    return checkpoint, job, plan, file


def _asset_values(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    body: dto.BaselineAssetCreate,
    cache: dict[uuid.UUID, tuple[ProjectSourceJob, ProjectSourcePlan, ProjectPathBinding]]
    | None = None,
) -> dict[str, Any]:
    checkpoint, job, plan, file = _source(db, owner, project, body.source_file_id, cache)
    return dict(
        source_file_id=checkpoint.id,
        source_job_id=job.id,
        source_plan_id=plan.id,
        file_key_sha256=file.file_key_sha256,
        attachment_id=file.attachment_id,
        path=file.path,
        sha256=file.sha256,
        size_bytes=file.size_bytes,
        commit_sha=plan.commit_sha,
        source_plan_sha256=plan.plan_sha256,
        source_receipt_sha256=job.receipt_sha256,
        source_status=plan.source_status,
        source_gaps_text=plan.gaps_text,
    )


def _scope(db: Session, row: BaselineVersion) -> tuple[BaselineProbeAsset, ...]:
    _intact(db, row)
    if row.model_version_id is not None:
        model: ModelVersion = _get(db, ModelVersion, row.user_id, row.model_version_id)
        if (
            model.model_id != row.model_id
            or model_hash(db, row.user_id, model) != row.model_snapshot_sha256
        ):
            raise DomainError("BASELINE_MODEL_CHANGED", "Frozen model version changed", 409)
    for item in datasets(db, row):
        _, _, sha = dataset_snapshot(db, row.user_id, item.dataset_version_id)
        if sha != item.snapshot_sha256:
            raise DomainError(
                "BASELINE_DATASET_CHANGED",
                "Frozen dataset version or declared metadata changed",
                409,
            )
    frozen = []
    cache: dict[uuid.UUID, tuple[ProjectSourceJob, ProjectSourcePlan, ProjectPathBinding]] = {}
    for asset in assets(db, row):
        body = dto.BaselineAssetCreate.model_validate(
            dict(
                role=asset.role,
                source_file_id=asset.source_file_id,
                dataset_version_id=asset.dataset_version_id,
            )
        )
        actual = _asset_values(db, row.user_id, row.project_id, body, cache)
        if any(getattr(asset, key) != value for key, value in actual.items()):
            raise DomainError(
                "BASELINE_ASSET_CHANGED", "Frozen source checkpoint or source approval changed", 409
            )
        plan = project_sources.get_plan(db, row.user_id, row.project_id, asset.source_plan_id)
        frozen.append(
            BaselineProbeAsset(
                asset.id,
                asset.role,
                asset.dataset_version_id,
                project_sources.policy_scope(db, plan),
                SourceFile(asset.path, asset.sha256, asset.size_bytes),
                asset.attachment_id,
            )
        )
    return tuple(frozen)


def declaration_gaps(db: Session, row: BaselineVersion) -> list[str]:
    items = assets(db, row)
    bindings = datasets(db, row)
    roles = {item.role for item in items}
    gaps = []
    if row.model_version_id is None:
        gaps.append("MODEL_VERSION_MISSING")
    for role in ("CODE", "CONFIG", "ENVIRONMENT_LOCK", "EVALUATOR"):
        if role not in roles:
            gaps.append(role + "_MISSING")
    if row.weight_mode == "PRETRAINED" and "WEIGHTS" not in roles:
        gaps.append("PRETRAINED_WEIGHTS_MISSING")
    if row.weight_mode == "FROM_SCRATCH" and "WEIGHTS" in roles:
        gaps.append("FROM_SCRATCH_WEIGHTS_CONFLICT")
    if not bindings:
        gaps.append("DATASET_VERSION_MISSING")
    for binding in bindings:
        declared = {
            item.role for item in items if item.dataset_version_id == binding.dataset_version_id
        }
        for role in ("DATA", "SPLIT_MANIFEST"):
            if role not in declared:
                gaps.append(role + "_MISSING:" + str(binding.dataset_version_id))
    for item in items:
        for gap in json.loads(item.source_gaps_text):
            if any(
                token in gap.upper()
                for token in (
                    "LFS",
                    "SHARD",
                    "SUBMODULE",
                    "EXTERNAL",
                    "UNSUPPORTED",
                    "UNSAFE",
                    "CHANGED",
                    "UNVERIFIED",
                )
            ):
                gaps.append("SOURCE_UNRESOLVED:" + gap)
    return list(dict.fromkeys(gaps))


def create_baseline(
    db: Session, owner: uuid.UUID, project: uuid.UUID, body: dto.BaselineCreate
) -> Baseline:
    get_project(db, owner, project)
    name = body.name.strip()
    if not name:
        raise DomainError("VALIDATION_ERROR", "Baseline name cannot be blank", 422)
    row = Baseline(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project,
        name=name,
        purpose=body.purpose,
        created_at=now(),
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "BASELINE_NAME_CONFLICT", "This project already has a baseline with that name", 409
        ) from None
    return row


def create_version(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, body: dto.BaselineVersionCreate
) -> BaselineVersion:
    baseline: Baseline = _get(db, Baseline, owner, identity, lock=True)
    try:
        if not body.version.strip():
            raise DomainError("VALIDATION_ERROR", "Version name cannot be blank", 422)
        parent = None
        if body.parent_version_id:
            parent = get_version(db, owner, body.parent_version_id)
            _intact(db, parent)
            if (
                parent.baseline_id != baseline.id
                or parent.project_id != baseline.project_id
                or parent.sha256 != body.expected_parent_sha256
            ):
                raise DomainError(
                    "BASELINE_PARENT_CONFLICT",
                    "Parent identity or exact frozen hash does not match",
                    409,
                )
        model: ModelVersion | None = (
            _get(db, ModelVersion, owner, body.model_version_id) if body.model_version_id else None
        )
        if body.paper_id:
            _get(db, Paper, owner, body.paper_id)
        row = BaselineVersion(
            id=uuid.uuid4(),
            user_id=owner,
            project_id=baseline.project_id,
            baseline_id=baseline.id,
            version=body.version.strip(),
            parent_version_id=parent.id if parent else None,
            parent_sha256=parent.sha256 if parent else None,
            model_id=model.model_id if model else None,
            model_version_id=model.id if model else None,
            model_snapshot_sha256=model_hash(db, owner, model) if model else None,
            paper_id=body.paper_id,
            weight_mode=body.weight_mode,
            purpose=body.purpose,
            notes=body.notes,
            sha256="0" * 64,
            created_at=now(),
        )
        declared = []
        for item in body.datasets:
            version, dataset, sha = dataset_snapshot(db, owner, item.dataset_version_id)
            if not item.license_confirmation.strip() or not item.usage_scope.strip():
                raise DomainError(
                    "VALIDATION_ERROR",
                    "Dataset license confirmation and use scope cannot be blank",
                    422,
                )
            declared.append(
                BaselineDatasetBinding(
                    version_id=row.id,
                    user_id=owner,
                    project_id=row.project_id,
                    dataset_version_id=version.id,
                    dataset_id=dataset.id,
                    dataset_name=dataset.name,
                    dataset_version=version.version,
                    snapshot_sha256=sha,
                    license_confirmation=item.license_confirmation,
                    usage_scope=item.usage_scope,
                )
            )
        dsids = {item.dataset_version_id for item in declared}
        proposed = []
        cache: dict[uuid.UUID, tuple[ProjectSourceJob, ProjectSourcePlan, ProjectPathBinding]] = {}
        for asset_input in body.assets:
            if (asset_input.role in {"DATA", "SPLIT_MANIFEST"}) != (
                asset_input.dataset_version_id is not None
            ) or (
                asset_input.dataset_version_id is not None
                and asset_input.dataset_version_id not in dsids
            ):
                raise DomainError(
                    "BASELINE_DATASET_SCOPE_INVALID",
                    "DATA and split manifests must belong to a declared dataset version",
                    422,
                )
            proposed.append(
                BaselineAsset(
                    id=uuid.uuid4(),
                    version_id=row.id,
                    user_id=owner,
                    project_id=row.project_id,
                    role=asset_input.role,
                    dataset_version_id=asset_input.dataset_version_id,
                    **_asset_values(db, owner, row.project_id, asset_input, cache),
                )
            )
        db.add(row)
        db.flush()
        db.add_all(declared)
        db.flush()
        db.add_all(proposed)
        db.flush()
        row.sha256 = version_hash(db, row)
        db.commit()
        db.refresh(row)
        return row
    except DomainError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "BASELINE_VERSION_CONFLICT",
            "Version name or input identity conflicts with an existing declaration",
            409,
        ) from None


def check_summary(row: BaselineMaterialCheck) -> dto.BaselineMaterialCheckSummary:
    return dto.BaselineMaterialCheckSummary(
        **_columns(row, ("user_id", "project_id", "gaps_text", "created_at")),
        gaps=json.loads(row.gaps_text),
    )


def check_out(db: Session, row: BaselineMaterialCheck) -> dto.BaselineMaterialCheckOut:
    observations = list(
        db.scalars(
            select(BaselineAssetObservation)
            .where(
                BaselineAssetObservation.check_id == row.id,
                BaselineAssetObservation.version_id == row.version_id,
                BaselineAssetObservation.project_id == row.project_id,
                BaselineAssetObservation.user_id == row.user_id,
            )
            .order_by(BaselineAssetObservation.asset_id)
        )
    )

    return dto.BaselineMaterialCheckOut(
        **check_summary(row).model_dump(),
        observations=[
            dto.BaselineAssetObservationOut.model_validate(item) for item in observations
        ],
    )


def _receipt_valid(result: BaselineProbeResult, request: BaselineProbeRequest) -> bool:
    """Dataclass adapters are ports, not runtime validators: fail closed on malformed facts."""
    if (
        not isinstance(result, BaselineProbeResult)
        or not isinstance(result.checker_version, str)
        or not 1 <= len(result.checker_version) <= 80
        or not isinstance(result.checker_sha256, str)
        or re.fullmatch(r"[a-f0-9]{64}", result.checker_sha256) is None
        or type(result.split_valid) is not bool
    ):
        return False
    if (
        not isinstance(result.gaps, tuple)
        or len(result.gaps) > 3000
        or any(not isinstance(gap, str) or not 1 <= len(gap) <= 2400 for gap in result.gaps)
    ):
        return False
    if not isinstance(result.observations, tuple) or len(result.observations) > 1000:
        return False
    expected = {asset.asset_id for asset in request.assets}
    seen: set[uuid.UUID] = set()
    for observation in result.observations:
        if not isinstance(observation, ProbeObservation):
            return False
        if (
            not isinstance(observation.asset_id, uuid.UUID)
            or observation.asset_id not in expected
            or observation.asset_id in seen
            or not isinstance(observation.status, str)
            or observation.status not in {"VERIFIED", "MISSING", "CHANGED", "UNSAFE", "UNAVAILABLE"}
        ):
            return False
        seen.add(observation.asset_id)
        if observation.actual_sha256 is not None and (
            not isinstance(observation.actual_sha256, str)
            or re.fullmatch(r"[a-f0-9]{64}", observation.actual_sha256) is None
        ):
            return False
        if observation.actual_size_bytes is not None and (
            type(observation.actual_size_bytes) is not int
            or not 0 <= observation.actual_size_bytes <= 2**63 - 1
        ):
            return False
        if observation.issue is not None and (
            not isinstance(observation.issue, str) or len(observation.issue) > 160
        ):
            return False
        if (
            not isinstance(observation.checked_at, datetime)
            or observation.checked_at.utcoffset() is None
        ):
            return False
    return True


def version_out(db: Session, row: BaselineVersion) -> dto.BaselineVersionOut:
    current = True
    gaps = declaration_gaps(db, row)
    try:
        _scope(db, row)
    except DomainError as error:
        current = False
        gaps.append(error.code)
    latest = db.scalar(
        select(BaselineMaterialCheck)
        .where(
            BaselineMaterialCheck.version_id == row.id,
            BaselineMaterialCheck.project_id == row.project_id,
            BaselineMaterialCheck.user_id == row.user_id,
        )
        .order_by(BaselineMaterialCheck.created_at.desc(), BaselineMaterialCheck.id.desc())
        .limit(1)
    )
    qualified = (
        current
        and not gaps
        and latest is not None
        and latest.outcome == "MATERIALIZED"
        and latest.version_sha256 == row.sha256
    )
    public = _columns(row, ("user_id", "model_snapshot_sha256"))
    return dto.BaselineVersionOut(
        **public,
        qualification="MATERIALIZED" if qualified else "CATALOGED",
        scope_current=current,
        can_check_materials=current and capability().materials_check_available,
        gaps=list(
            dict.fromkeys(
                gaps
                + (
                    ["MATERIAL_CHECK_NOT_RECORDED"]
                    if latest is None
                    else json.loads(latest.gaps_text)
                )
            )
        )
        + [
            "RUNNER_NOT_IMPLEMENTED",
            "ENVIRONMENT_NOT_EXECUTION_VERIFIED",
            "SCIENTIFIC_PROTOCOL_NOT_VERIFIED",
        ],
        assets=[
            dto.BaselineAssetOut(
                **_columns(item, ("user_id", "project_id", "version_id", "source_gaps_text")),
                source_gaps=json.loads(item.source_gaps_text),
            )
            for item in assets(db, row)
        ],
        datasets=[dto.BaselineDatasetOut.model_validate(item) for item in datasets(db, row)],
        latest_check=check_summary(latest) if latest else None,
    )


async def check_materials(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    body: dto.BaselineMaterialCheckCreate,
    *,
    provider: BaselineAssetProbeProvider | None = None,
) -> BaselineMaterialCheck:
    row = get_version(db, owner, identity)
    if row.sha256 != body.expected_sha256:
        raise DomainError(
            "BASELINE_VERSION_CONFLICT",
            "Review the exact frozen version before checking materials",
            409,
        )
    requested = _scope(db, row)
    gaps = declaration_gaps(db, row)
    dataset_ids = tuple(item.dataset_version_id for item in datasets(db, row))
    request = BaselineProbeRequest(
        row.id, owner, row.project_id, row.sha256, requested, dataset_ids
    )
    if provider is None:
        from app.providers.registry import baseline_asset_probe_provider

        provider = baseline_asset_probe_provider()
    db.rollback()  # No SQL transaction or row lock is held during potentially slow readonly I/O.
    try:
        result = await provider.probe(request)
    except Exception:
        result = None
    invalid_receipt = result is not None and not _receipt_valid(result, request)
    if invalid_receipt:
        result = None
    observations: list[BaselineAssetObservation] = []
    actual = get_version(db, owner, identity)
    scope_valid = True
    try:
        fresh = _scope(db, actual)
        if actual.sha256 != request.version_sha256 or fresh != request.assets:
            scope_valid = False
    except DomainError:
        scope_valid = False
    if not scope_valid:
        gaps.append("BASELINE_SCOPE_CHANGED_DURING_PROBE")
    if result is None:
        outcome = "FAILED"
        checker_version = "baseline-service-failed-v1"
        checker_sha = digest({"checker": checker_version})
        gaps.append(
            "BASELINE_PROBE_RECEIPT_INVALID" if invalid_receipt else "BASELINE_PROBE_UNAVAILABLE"
        )
        observations = []
    else:
        checker_version = result.checker_version
        checker_sha = result.checker_sha256
        if (
            not checker_version
            or len(checker_version) > 80
            or not re.fullmatch(r"[a-f0-9]{64}", checker_sha)
        ):
            raise DomainError("BASELINE_PROBE_INVALID", "Material checker identity is invalid", 502)
        expected = {item.asset_id: item for item in requested}
        seen = set()
        observations = []
        for observation in result.observations:
            if (
                observation.asset_id not in expected
                or observation.asset_id in seen
                or observation.status
                not in {"VERIFIED", "MISSING", "CHANGED", "UNSAFE", "UNAVAILABLE"}
            ):
                raise DomainError(
                    "BASELINE_PROBE_INVALID", "Checker returned invalid observation identities", 502
                )
            seen.add(observation.asset_id)
            asset = expected[observation.asset_id]
            if observation.actual_sha256 is not None and not re.fullmatch(
                r"[a-f0-9]{64}", observation.actual_sha256
            ):
                raise DomainError(
                    "BASELINE_PROBE_INVALID", "Checker returned an invalid measured hash", 502
                )
            if observation.actual_size_bytes is not None and observation.actual_size_bytes < 0:
                raise DomainError(
                    "BASELINE_PROBE_INVALID", "Checker returned an invalid byte count", 502
                )
            if observation.status != "VERIFIED" or (
                observation.actual_sha256,
                observation.actual_size_bytes,
            ) != (asset.source_file.sha256, asset.source_file.size_bytes):
                gaps.append("ASSET_NOT_VERIFIED:" + str(observation.asset_id))
            status = observation.status
            issue = observation.issue
            if status == "VERIFIED" and (
                observation.actual_sha256,
                observation.actual_size_bytes,
            ) != (asset.source_file.sha256, asset.source_file.size_bytes):
                status = (
                    "UNAVAILABLE"
                    if observation.actual_sha256 is None or observation.actual_size_bytes is None
                    else "CHANGED"
                )
                issue = "CHECKER_RESULT_MISMATCH"
            observations.append(
                BaselineAssetObservation(
                    asset_id=observation.asset_id,
                    version_id=identity,
                    project_id=request.project_id,
                    user_id=owner,
                    status=status,
                    actual_sha256=observation.actual_sha256,
                    actual_size_bytes=observation.actual_size_bytes,
                    issue=issue,
                    checked_at=observation.checked_at.astimezone(UTC),
                )
            )
        if seen != set(expected):
            gaps.append("ASSET_OBSERVATIONS_INCOMPLETE")
        gaps.extend(result.gaps)
        if result.split_valid is not True:
            gaps.append("DATA_SPLIT_NOT_VERIFIED")
        outcome = "MATERIALIZED" if not gaps and scope_valid else "INCOMPLETE"
    check = BaselineMaterialCheck(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=request.project_id,
        version_id=identity,
        version_sha256=request.version_sha256,
        outcome=outcome,
        checker_version=checker_version,
        checker_sha256=checker_sha,
        gaps_text=json.dumps(list(dict.fromkeys(gaps)), ensure_ascii=False),
        checked_at=now(),
        created_at=now(),
    )
    try:
        db.add(check)
        db.flush()
        for recorded in observations:
            recorded.check_id = check.id
        db.add_all(observations)
        db.commit()
        db.refresh(check)
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "BASELINE_CHECK_CONFLICT",
            "Observed input identity changed before the receipt could be recorded",
            409,
        ) from None
    return check


def _page(
    db: Session, model: Any, scope: list[Any], limit: int, cursor: str | None
) -> tuple[list[Any], str | None]:
    rows: list[Any] = list(
        db.scalars(
            select(model)
            .where(*scope, cursor_filter(model, cursor))
            .order_by(model.created_at.desc(), model.id.desc())
            .limit(limit + 1)
        )
    )
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None


def list_baselines(
    db: Session, owner: uuid.UUID, project: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[Baseline], str | None]:
    get_project(db, owner, project)
    return _page(
        db, Baseline, [Baseline.user_id == owner, Baseline.project_id == project], limit, cursor
    )


def list_versions(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[BaselineVersion], str | None]:
    parent = get_baseline(db, owner, identity)
    return _page(
        db,
        BaselineVersion,
        [
            BaselineVersion.user_id == owner,
            BaselineVersion.project_id == parent.project_id,
            BaselineVersion.baseline_id == identity,
        ],
        limit,
        cursor,
    )


def list_checks(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[BaselineMaterialCheck], str | None]:
    parent = get_version(db, owner, identity)
    return _page(
        db,
        BaselineMaterialCheck,
        [
            BaselineMaterialCheck.user_id == owner,
            BaselineMaterialCheck.project_id == parent.project_id,
            BaselineMaterialCheck.version_id == identity,
        ],
        limit,
        cursor,
    )


def source_jobs(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    limit: int = 20,
    cursor: str | None = None,
    source_job_id: uuid.UUID | None = None,
) -> tuple[list[dto.BaselineSourceJobChoice], str | None]:
    get_project(db, owner, project)
    query = (
        select(ProjectSourceJob)
        .join(
            ProjectSourcePlan,
            (ProjectSourcePlan.id == ProjectSourceJob.plan_id)
            & (ProjectSourcePlan.project_id == ProjectSourceJob.project_id)
            & (ProjectSourcePlan.user_id == ProjectSourceJob.user_id),
        )
        .join(
            ProjectPathBinding,
            (ProjectPathBinding.id == ProjectSourcePlan.path_binding_id)
            & (ProjectPathBinding.project_id == ProjectSourcePlan.project_id)
            & (ProjectPathBinding.user_id == ProjectSourcePlan.user_id),
        )
        .where(
            ProjectSourceJob.user_id == owner,
            ProjectSourceJob.project_id == project,
            ProjectSourceJob.status == "COMPLETED",
            ProjectSourceJob.receipt_sha256.is_not(None),
            ProjectSourceJob.verified_at.is_not(None),
            ProjectSourcePlan.state == "APPROVED",
            ProjectPathBinding.state == "ACTIVE",
            cursor_filter(ProjectSourceJob, cursor),
        )
    )
    if source_job_id is not None:
        query = query.where(ProjectSourceJob.id == source_job_id)
    rows = list(
        db.scalars(
            query.order_by(ProjectSourceJob.created_at.desc(), ProjectSourceJob.id.desc()).limit(
                limit + 1
            )
        )
    )
    result = []
    for job in rows[:limit]:
        plan = project_sources.get_plan(db, owner, project, job.plan_id)
        result.append(
            dto.BaselineSourceJobChoice(
                id=job.id,
                source_plan_id=plan.id,
                repo_id=plan.repo_id,
                commit_sha=plan.commit_sha,
                source_status=plan.source_status,
                copied_files=job.copied_files,
                copied_bytes=job.copied_bytes,
                receipt_sha256=job.receipt_sha256,
                verified_at=job.verified_at,
            )
        )
    return result, encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None


def source_files(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    job_id: uuid.UUID,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[dto.BaselineSourceFileChoice], str | None]:
    job = project_sources.get_job(db, owner, project, job_id)
    plan = project_sources.get_plan(db, owner, project, job.plan_id)
    binding = project_sources._validate(db, plan)
    if job.status != "COMPLETED" or binding.state != "ACTIVE" or plan.state != "APPROVED":
        raise DomainError(
            "BASELINE_SOURCE_NOT_COMPLETE", "Choose a completed approved source job", 409
        )
    # A resumed job may have multiple success observations: return only its newest exact file checkpoint.
    ranked = (
        select(
            ProjectSourceFile.id,
            func.row_number()
            .over(
                partition_by=ProjectSourceFile.file_key_sha256,
                order_by=(ProjectSourceFile.created_at.desc(), ProjectSourceFile.id.desc()),
            )
            .label("rank"),
        )
        .where(
            ProjectSourceFile.user_id == owner,
            ProjectSourceFile.project_id == project,
            ProjectSourceFile.job_id == job_id,
            ProjectSourceFile.status.in_(["COPIED", "REUSED"]),
        )
        .subquery()
    )
    if cursor is not None and re.fullmatch(r"[a-f0-9]{64}", cursor) is None:
        raise DomainError("INVALID_CURSOR", "Baseline source file cursor is invalid", 422)
    query = (
        select(ProjectSourceFile, ProjectSourcePlanFile)
        .join(ranked, (ranked.c.id == ProjectSourceFile.id) & (ranked.c.rank == 1))
        .join(
            ProjectSourcePlanFile,
            (ProjectSourcePlanFile.plan_id == ProjectSourceFile.plan_id)
            & (ProjectSourcePlanFile.file_key_sha256 == ProjectSourceFile.file_key_sha256)
            & (ProjectSourcePlanFile.project_id == ProjectSourceFile.project_id)
            & (ProjectSourcePlanFile.user_id == ProjectSourceFile.user_id),
        )
        .where(ProjectSourceFile.file_key_sha256 > cursor if cursor is not None else true())
        .order_by(ProjectSourceFile.file_key_sha256)
        .limit(limit + 1)
    )
    rows = list(db.execute(query))
    result = []
    for checkpoint, file in rows[:limit]:
        result.append(
            dto.BaselineSourceFileChoice(
                source_file_id=checkpoint.id,
                source_job_id=job.id,
                source_plan_id=plan.id,
                file_key_sha256=file.file_key_sha256,
                path=file.path,
                sha256=file.sha256,
                size_bytes=file.size_bytes,
            )
        )
    return result, rows[limit - 1][0].file_key_sha256 if len(rows) > limit else None
