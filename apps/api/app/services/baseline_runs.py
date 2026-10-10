"""Owner-approved bounded execution declarations; all I/O stays behind provider ports."""

import hashlib
import json
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas_baseline_runs as dto
from app.core.config import get_settings
from app.domain.baseline_runs import (
    BaselineRunInput,
    BaselineRunLimits,
    BaselineRunProjection,
    BaselineRunProvider,
    BaselineRunRequest,
    BaselineRuntimeEvidence,
    run_projection_sha256,
    run_request_sha256,
)
from app.domain.baselines import BaselineProbeAsset, BaselineProbeRequest
from app.domain.github_archive import GitHubPrivateRepository
from app.domain.project_sources import ProjectSourceFile, ProjectSourceScope
from app.errors import DomainError
from app.models import ResearchEvent
from app.models_baseline_runs import (
    BaselineRunArtifact,
    BaselineRunAttempt,
    BaselineRunJob,
    BaselineRunPermit,
    BaselineRunPlan,
    BaselineRunPlanInput,
)
from app.models_baselines import BaselineMaterialCheck
from app.services import baselines
from app.services.research_briefs import digest

LIMIT_NAMES = tuple(dto.BaselineRunLimitsIn.model_fields)


def now() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def provider_port() -> BaselineRunProvider:
    from app.providers.registry import baseline_run_provider

    return baseline_run_provider()


def enabled() -> None:
    from app.domain.research_execution_policy import require_local_research_execution

    require_local_research_execution()
    if not get_settings().baseline_runner_enabled:
        raise DomainError("BASELINE_RUNNER_DISABLED", "Bounded baseline execution is disabled", 503)


def json_value(value: Any) -> Any:
    return json.loads(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    )


def get_plan(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> BaselineRunPlan:
    return cast(BaselineRunPlan, baselines._get(db, BaselineRunPlan, owner, identity, lock=lock))


def get_job(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> BaselineRunJob:
    return cast(BaselineRunJob, baselines._get(db, BaselineRunJob, owner, identity, lock=lock))


def plan_inputs(db: Session, plan: BaselineRunPlan) -> list[BaselineRunPlanInput]:
    return list(
        db.scalars(
            select(BaselineRunPlanInput)
            .where(
                BaselineRunPlanInput.plan_id == plan.id,
                BaselineRunPlanInput.version_id == plan.version_id,
                BaselineRunPlanInput.project_id == plan.project_id,
                BaselineRunPlanInput.user_id == plan.user_id,
            )
            .order_by(BaselineRunPlanInput.path)
            .execution_options(populate_existing=True)
        )
    )


def limits(plan: BaselineRunPlan) -> BaselineRunLimits:
    return BaselineRunLimits(**{key: getattr(plan, key) for key in LIMIT_NAMES})


def scope_decode(raw: dict[str, Any]) -> ProjectSourceScope:
    value = dict(raw)
    for key in ("owner_id", "project_id", "plan_id", "asset_snapshot_id", "archive_binding_id"):
        value[key] = uuid.UUID(value[key])
    value["repository"] = GitHubPrivateRepository(**value["repository"])
    return ProjectSourceScope(**value)


def input_decode(raw: dict[str, Any]) -> BaselineRunInput:
    value = dict(raw)
    value["asset_id"] = uuid.UUID(value["asset_id"])
    value["source_scope"] = scope_decode(value["source_scope"])
    value["source_file"] = ProjectSourceFile(**value["source_file"])
    if value.get("dataset_version_id"):
        value["dataset_version_id"] = uuid.UUID(value["dataset_version_id"])
    if value.get("projected_content") is not None:
        value["projected_content"] = value["projected_content"].encode("utf-8")
    return BaselineRunInput(**value)


def transport_inputs(db: Session, plan: BaselineRunPlan) -> tuple[BaselineRunInput, ...]:
    assets = {
        asset.id: asset
        for asset in baselines.assets(db, baselines.get_version(db, plan.user_id, plan.version_id))
    }
    result = []
    for row in plan_inputs(db, plan):
        asset = assets.get(row.asset_id)
        if asset is None:
            raise DomainError(
                "BASELINE_RUN_INPUT_CHANGED", "Recorded input asset is no longer available", 409
            )
        result.append(
            BaselineRunInput(
                row.asset_id,
                row.role,
                scope_decode(row.source_scope_payload),
                ProjectSourceFile(asset.path, row.source_sha256, asset.size_bytes),
                row.path,
                cast(Literal["TRAIN", "VALIDATION"] | None, row.dataset_split),
                row.dataset_version_id,
                row.sample_id,
                row.group_id,
                row.projected_content.encode("utf-8")
                if row.projected_content is not None
                else None,
            )
        )
    return tuple(result)


def material_hash(db: Session, row: BaselineMaterialCheck) -> str:
    return digest(baselines.check_out(db, row).model_dump(mode="json"))


def plan_hash(db: Session, plan: BaselineRunPlan) -> str:
    header = baselines._columns(
        plan,
        (
            "sha256",
            "state",
            "approved_sha256",
            "approved_by",
            "approved_at",
            "used_jobs",
            "created_at",
        ),
    )
    header["expires_at"] = utc(plan.expires_at).isoformat()
    return digest(
        {
            "schema": "baseline-run-grant-v1",
            "plan": header,
            "inputs": [baselines._columns(row, ("id",)) for row in plan_inputs(db, plan)],
        }
    )


def _intact(db: Session, plan: BaselineRunPlan) -> None:
    if plan.sha256 != plan_hash(db, plan) or plan.input_manifest_sha256 != run_projection_sha256(
        transport_inputs(db, plan)
    ):
        raise DomainError(
            "BASELINE_RUN_PLAN_CHANGED", "Frozen execution scope or input manifest changed", 409
        )


def validate_plan(db: Session, plan: BaselineRunPlan, *, active: bool = True) -> None:
    _intact(db, plan)
    version = baselines.get_version(db, plan.user_id, plan.version_id)
    if version.project_id != plan.project_id or version.sha256 != plan.version_sha256:
        raise DomainError("BASELINE_RUN_VERSION_CHANGED", "Frozen baseline version changed", 409)
    fresh = {item.asset_id: item for item in baselines._scope(db, version)}
    gaps = baselines.declaration_gaps(db, version)
    if gaps:
        raise DomainError(
            "BASELINE_RUN_MATERIALS_INCOMPLETE", "Baseline required materials are incomplete", 409
        )
    if plan.material_check_id is None:
        raise DomainError(
            "BASELINE_RUN_MATERIAL_CHECK_MISSING",
            "A recorded measured material check is required",
            409,
        )
    check = baselines.get_check(db, plan.user_id, plan.version_id, plan.material_check_id)
    if (
        check.outcome != "MATERIALIZED"
        or check.version_sha256 != version.sha256
        or material_hash(db, check) != plan.material_check_sha256
    ):
        raise DomainError(
            "BASELINE_RUN_MATERIAL_CHECK_CHANGED",
            "Selected material evidence is not complete or changed",
            409,
        )
    rows = plan_inputs(db, plan)
    if (
        len(rows) > plan.max_input_files
        or sum(row.size_bytes for row in rows) > plan.max_input_bytes
    ):
        raise DomainError(
            "BASELINE_RUN_INPUT_LIMIT", "Input projection exceeds its frozen limits", 409
        )
    for item in transport_inputs(db, plan):
        source = fresh.get(item.asset_id)
        if (
            source is None
            or source.role != item.role
            or source.dataset_version_id != item.dataset_version_id
            or source.source_scope != item.source_scope
            or source.source_file != item.source_file
        ):
            raise DomainError(
                "BASELINE_RUN_SOURCE_CHANGED",
                "Input source identity or current approval changed",
                409,
            )
        content = item.projected_content
        if item.role == "DATA" and item.dataset_split not in {"TRAIN", "VALIDATION"}:
            raise DomainError(
                "BASELINE_RUN_TEST_INPUT_FORBIDDEN", "TEST data cannot be an execution input", 409
            )
        if item.role == "SPLIT_MANIFEST" and content is None:
            raise DomainError(
                "BASELINE_RUN_RAW_MANIFEST_FORBIDDEN",
                "Original full split manifests cannot be mounted",
                409,
            )
    selected = {row.asset_id: row for row in rows}
    if (
        plan.entry_asset_id not in selected
        or selected[plan.entry_asset_id].role not in {"CODE", "EVALUATOR"}
        or not selected[plan.entry_asset_id].path.endswith(".py")
    ):
        raise DomainError(
            "BASELINE_RUN_ENTRY_MISSING", "Choose a fixed Python CODE or EVALUATOR entry asset", 409
        )
    if plan.config_asset_id not in selected or selected[plan.config_asset_id].role != "CONFIG":
        raise DomainError("BASELINE_RUN_CONFIG_MISSING", "Choose a fixed CONFIG input asset", 409)
    if active:
        enabled()
        if (
            plan.state != "ACTIVE"
            or plan.approved_by != plan.user_id
            or plan.approved_sha256 != plan.sha256
            or plan.approved_at is None
        ):
            raise DomainError(
                "BASELINE_RUN_GRANT_INACTIVE", "Exact bounded execution approval is not active", 409
            )
        if utc(plan.expires_at) <= now():
            raise DomainError("BASELINE_RUN_GRANT_EXPIRED", "Execution approval expired", 409)


def runtime_valid(plan: BaselineRunPlan, evidence: BaselineRuntimeEvidence) -> None:
    if (
        evidence.available is not True
        or not plan.image_id
        or not plan.daemon_id
        or (evidence.image_id, evidence.daemon_id) != (plan.image_id, plan.daemon_id)
    ):
        raise DomainError(
            "BASELINE_RUN_RUNTIME_CHANGED",
            "Configured local Docker image or engine is unavailable or changed",
            409,
        )


async def runtime(provider: BaselineRunProvider | None = None) -> dto.BaselineRuntimeOut:
    from app.domain.research_execution_policy import (
        LOCAL_RESEARCH_POLICY_CODE,
        local_research_execution_allowed,
    )

    if not local_research_execution_allowed():
        return dto.BaselineRuntimeOut(
            enabled=False,
            available=False,
            docker_host="",
            daemon_id=None,
            image_id=None,
            issues=[LOCAL_RESEARCH_POLICY_CODE, "LAB_SERVER_CHANNEL_NOT_CONFIGURED"],
            checked_at=now(),
        )
    evidence = await (provider or provider_port()).runtime()
    return dto.BaselineRuntimeOut(
        enabled=get_settings().baseline_runner_enabled,
        available=evidence.available,
        docker_host=evidence.docker_host,
        daemon_id=evidence.daemon_id,
        image_id=evidence.image_id,
        issues=list(evidence.issues),
        checked_at=evidence.checked_at,
    )


def _projection_valid(request: BaselineProbeRequest, projection: BaselineRunProjection) -> None:
    if not isinstance(
        projection, BaselineRunProjection
    ) or projection.sha256 != run_projection_sha256(projection.inputs):
        raise DomainError("BASELINE_RUN_PROJECTION_INVALID", "Projection digest is invalid", 502)
    sources = {item.asset_id: item for item in request.assets}
    seen = set()
    paths = set()
    groups: dict[tuple[uuid.UUID | None, str], str] = {}
    samples: set[tuple[uuid.UUID | None, str]] = set()
    for item in projection.inputs:
        source = sources.get(item.asset_id)
        if (
            source is None
            or item.asset_id in seen
            or item.relative_path in paths
            or item.role != source.role
            or item.source_scope != source.source_scope
            or item.source_file != source.source_file
        ):
            raise DomainError(
                "BASELINE_RUN_PROJECTION_INVALID",
                "Projection has ambiguous or changed input identity",
                502,
            )
        seen.add(item.asset_id)
        paths.add(item.relative_path)
        if (
            item.relative_path.startswith(("/", "\\"))
            or "\\" in item.relative_path
            or any(part in {"", ".", ".."} for part in item.relative_path.split("/"))
        ):
            raise DomainError(
                "BASELINE_RUN_PROJECTION_INVALID",
                "Projection paths must be fixed relative members",
                502,
            )
        if item.role == "DATA":
            if (
                item.dataset_version_id != source.dataset_version_id
                or item.dataset_split not in {"TRAIN", "VALIDATION"}
                or not item.sample_id
                or not item.group_id
                or (item.dataset_version_id, item.sample_id) in samples
                or (
                    (item.dataset_version_id, item.group_id) in groups
                    and groups[(item.dataset_version_id, item.group_id)] != item.dataset_split
                )
                or item.projected_content is not None
            ):
                raise DomainError(
                    "BASELINE_RUN_TEST_INPUT_FORBIDDEN",
                    "Projection must contain distinct TRAIN/VALIDATION sample groups",
                    502,
                )
            samples.add((item.dataset_version_id, item.sample_id))
            groups[(item.dataset_version_id, item.group_id)] = item.dataset_split
        elif item.role == "SPLIT_MANIFEST":
            if (
                item.projected_content is None
                or item.dataset_version_id != source.dataset_version_id
            ):
                raise DomainError(
                    "BASELINE_RUN_RAW_MANIFEST_FORBIDDEN",
                    "Split manifests must be generated projections",
                    502,
                )
            payload = json.loads(item.projected_content)
            if (
                not isinstance(payload, dict)
                or set(payload)
                != {"schema", "dataset_version_id", "source_manifest_sha256", "splits"}
                or payload.get("dataset_version_id") != str(item.dataset_version_id)
                or payload.get("source_manifest_sha256") != item.source_file.sha256
                or payload.get("schema") != "baseline-run-split-projection-v1"
                or {part["name"] for part in payload.get("splits", [])} != {"TRAIN", "VALIDATION"}
            ):
                raise DomainError(
                    "BASELINE_RUN_TEST_INPUT_FORBIDDEN",
                    "Only TRAIN/VALIDATION manifests may be mounted",
                    502,
                )
            if len(payload["splits"]) != 2:
                raise DomainError(
                    "BASELINE_RUN_PROJECTION_INVALID",
                    "Projected split records must be exactly TRAIN and VALIDATION",
                    502,
                )
            for part in payload["splits"]:
                expected = {
                    (
                        entry.sample_id,
                        entry.group_id,
                        entry.relative_path,
                        entry.source_file.sha256,
                        entry.source_file.size_bytes,
                    )
                    for entry in projection.inputs
                    if entry.role == "DATA"
                    and entry.dataset_version_id == item.dataset_version_id
                    and entry.dataset_split == part["name"]
                }
                try:
                    observed = {
                        (
                            sample["sample_id"],
                            sample["group_id"],
                            sample["path"],
                            sample["sha256"],
                            sample["size_bytes"],
                        )
                        for sample in part["samples"]
                    }
                    exact = (
                        set(part) == {"name", "samples"}
                        and len(part["samples"]) == len(observed)
                        and all(
                            set(sample) == {"sample_id", "group_id", "path", "sha256", "size_bytes"}
                            for sample in part["samples"]
                        )
                    )
                except (KeyError, TypeError):
                    exact = False
                    observed = set()
                if not exact or not expected or observed != expected:
                    raise DomainError(
                        "BASELINE_RUN_PROJECTION_INVALID",
                        "Projected sample closure differs from actual selected DATA members",
                        502,
                    )
        elif any(
            value is not None
            for value in (
                item.dataset_version_id,
                item.dataset_split,
                item.sample_id,
                item.group_id,
                item.projected_content,
            )
        ):
            raise DomainError(
                "BASELINE_RUN_PROJECTION_INVALID",
                "Non-data inputs cannot redefine sample scope",
                502,
            )
    if {item.asset_id for item in request.assets if item.role not in {"DATA"}} != {
        item.asset_id for item in projection.inputs if item.role != "DATA"
    }:
        raise DomainError(
            "BASELINE_RUN_PROJECTION_INCOMPLETE",
            "Projection must retain every non-TEST baseline dependency",
            502,
        )


async def create_plan(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    body: dto.BaselineRunPlanCreate,
    *,
    provider: BaselineRunProvider | None = None,
    probe_provider: Any = None,
) -> BaselineRunPlan:
    version = baselines.get_version(db, owner, identity)
    if version.sha256 != body.expected_version_sha256:
        raise DomainError(
            "BASELINE_RUN_VERSION_CONFLICT",
            "Review the exact baseline version before saving a run plan",
            409,
        )
    if body.expires_at.utcoffset() is None or not now() < utc(body.expires_at) <= now() + timedelta(
        days=30
    ):
        raise DomainError(
            "VALIDATION_ERROR",
            "Execution expiry must be timezone-aware and within thirty days",
            422,
        )
    members = {asset.id: asset for asset in baselines.assets(db, version)}
    for identity_asset, roles in (
        (body.entry_asset_id, {"CODE", "EVALUATOR"}),
        (body.config_asset_id, {"CONFIG"}),
    ):
        if identity_asset is not None and (
            identity_asset not in members or members[identity_asset].role not in roles
        ):
            raise DomainError(
                "NOT_FOUND", "Owned matching baseline entry or config asset not found", 404
            )
    check = (
        baselines.get_check(db, owner, version.id, body.material_check_id)
        if body.material_check_id
        else db.scalar(
            select(BaselineMaterialCheck)
            .where(
                BaselineMaterialCheck.user_id == owner,
                BaselineMaterialCheck.version_id == version.id,
                BaselineMaterialCheck.project_id == version.project_id,
            )
            .order_by(BaselineMaterialCheck.created_at.desc(), BaselineMaterialCheck.id.desc())
            .limit(1)
        )
    )
    captured_check_sha = material_hash(db, check) if check else None
    initial_scope: tuple[BaselineProbeAsset, ...] = ()
    gaps = baselines.declaration_gaps(db, version)
    try:
        initial_scope = baselines._scope(db, version)
    except DomainError as error:
        gaps.append(error.code)
    request = BaselineProbeRequest(
        version.id,
        owner,
        version.project_id,
        version.sha256,
        initial_scope,
        tuple(item.dataset_version_id for item in baselines.datasets(db, version)),
    )
    if check is None or check.outcome != "MATERIALIZED" or check.version_sha256 != version.sha256:
        gaps.append("MATERIAL_CHECK_REQUIRED")
    version_sha = version.sha256
    project = version.project_id
    db.rollback()
    adapter = provider or provider_port()
    evidence = await adapter.runtime()
    projection = BaselineRunProjection((), run_projection_sha256(()))
    if initial_scope and not gaps:
        if probe_provider is None:
            from app.providers.registry import baseline_asset_probe_provider

            probe_provider = baseline_asset_probe_provider()
        result = await probe_provider.probe(request)
        expected = {item.asset_id: item for item in request.assets}
        if (
            not baselines._receipt_valid(result, request)
            or result.split_valid is not True
            or result.gaps
            or len(result.observations) != len(expected)
            or any(
                item.status != "VERIFIED"
                or (item.actual_sha256, item.actual_size_bytes)
                != (
                    expected[item.asset_id].source_file.sha256,
                    expected[item.asset_id].source_file.size_bytes,
                )
                for item in result.observations
            )
        ):
            gaps.append("CURRENT_MATERIAL_PROBE_INCOMPLETE")
        else:
            projection = await adapter.project_inputs(request)
            _projection_valid(request, projection)
            gaps.extend(projection.issues)
    fresh = baselines.get_version(db, owner, identity)
    try:
        if fresh.sha256 != version_sha or baselines._scope(db, fresh) != initial_scope:
            gaps.append("RUN_SCOPE_CHANGED_DURING_PREVIEW")
    except DomainError:
        gaps.append("RUN_SCOPE_CHANGED_DURING_PREVIEW")
    if evidence.available is not True:
        gaps.extend(evidence.issues or ("DOCKER_RUNTIME_UNAVAILABLE",))
    if body.entry_asset_id is None:
        gaps.append("ENTRY_ASSET_REQUIRED")
    if body.config_asset_id is None:
        gaps.append("CONFIG_ASSET_REQUIRED")
    if (
        len(projection.inputs) > body.limits.max_input_files
        or sum(
            len(item.projected_content)
            if item.projected_content is not None
            else item.source_file.size_bytes
            for item in projection.inputs
        )
        > body.limits.max_input_bytes
    ):
        gaps.append("PROJECTED_INPUT_LIMIT_EXCEEDED")
    plan = BaselineRunPlan(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project,
        version_id=identity,
        version_sha256=version_sha,
        material_check_id=check.id if check else None,
        material_check_sha256=captured_check_sha,
        image_id=evidence.image_id,
        daemon_id=evidence.daemon_id,
        profile=body.profile,
        entry_asset_id=body.entry_asset_id,
        config_asset_id=body.config_asset_id,
        random_seed=body.parameters.random_seed,
        **body.limits.model_dump(),
        expires_at=utc(body.expires_at),
        max_jobs=body.max_jobs,
        used_jobs=0,
        state="DRAFT",
        input_manifest_sha256=projection.sha256,
        sha256="0" * 64,
        gaps_text=json.dumps(list(dict.fromkeys(gaps))),
        created_at=now(),
    )
    try:
        db.add(plan)
        db.flush()
        for item in sorted(projection.inputs, key=lambda entry: entry.relative_path):
            content = item.projected_content
            db.add(
                BaselineRunPlanInput(
                    id=uuid.uuid4(),
                    user_id=owner,
                    project_id=project,
                    version_id=identity,
                    plan_id=plan.id,
                    asset_id=item.asset_id,
                    role=item.role,
                    dataset_version_id=item.dataset_version_id,
                    dataset_split=item.dataset_split,
                    sample_id=item.sample_id,
                    group_id=item.group_id,
                    path=item.relative_path,
                    source_sha256=item.source_file.sha256,
                    input_sha256=hashlib.sha256(content).hexdigest()
                    if content is not None
                    else item.source_file.sha256,
                    size_bytes=len(content) if content is not None else item.source_file.size_bytes,
                    projected_content=content.decode("utf-8") if content is not None else None,
                    source_scope_payload=json_value(asdict(item.source_scope)),
                )
            )
        db.flush()
        plan.input_manifest_sha256 = run_projection_sha256(transport_inputs(db, plan))
        plan.sha256 = plan_hash(db, plan)
        db.commit()
        db.refresh(plan)
        return plan
    except (IntegrityError, ValueError):
        db.rollback()
        raise DomainError(
            "BASELINE_RUN_PLAN_CONFLICT",
            "Frozen source identity changed before the draft could be saved",
            409,
        ) from None


def build_request(db: Session, plan: BaselineRunPlan, job_id: uuid.UUID) -> BaselineRunRequest:
    if (
        plan.entry_asset_id is None
        or plan.config_asset_id is None
        or not plan.image_id
        or not plan.daemon_id
    ):
        raise DomainError(
            "BASELINE_RUN_PLAN_INCOMPLETE",
            "Plan has no fixed runnable entry, config or runtime",
            409,
        )
    request = BaselineRunRequest(
        job_id,
        plan.user_id,
        plan.project_id,
        plan.version_id,
        plan.version_sha256,
        "",
        plan.sha256,
        plan.image_id,
        plan.daemon_id,
        plan.entry_asset_id,
        transport_inputs(db, plan),
        limits(plan),
        config_asset_id=plan.config_asset_id,
        random_seed=plan.random_seed,
    )
    return replace(request, request_sha256=run_request_sha256(request))


def request_payload(request: BaselineRunRequest) -> dict[str, Any]:
    value = asdict(request)
    for item in value["inputs"]:
        if item["projected_content"] is not None:
            item["projected_content"] = item["projected_content"].decode("utf-8")
    return cast(dict[str, Any], json_value(value))


def request_decode(raw: dict[str, Any]) -> BaselineRunRequest:
    value = dict(raw)
    for key in (
        "job_id",
        "owner_id",
        "project_id",
        "version_id",
        "entry_asset_id",
        "config_asset_id",
    ):
        if value.get(key) is not None:
            value[key] = uuid.UUID(value[key])
    value["inputs"] = tuple(input_decode(item) for item in value["inputs"])
    value["limits"] = BaselineRunLimits(**value["limits"])
    return BaselineRunRequest(**value)


def validate_job(
    db: Session, job: BaselineRunJob, *, active: bool = True
) -> tuple[BaselineRunPlan, BaselineRunRequest]:
    plan = get_plan(db, job.user_id, job.plan_id)
    validate_plan(db, plan, active=active)
    try:
        request = request_decode(job.manifest_payload)
    except (KeyError, ValueError, TypeError):
        raise DomainError(
            "BASELINE_RUN_MANIFEST_CHANGED", "Recorded execution request is invalid", 409
        ) from None
    if (
        request.request_sha256 != job.manifest_sha256
        or run_request_sha256(request) != job.manifest_sha256
        or request != build_request(db, plan, job.id)
        or request.owner_id != job.user_id
        or request.project_id != job.project_id
        or request.version_id != job.version_id
    ):
        raise DomainError(
            "BASELINE_RUN_MANIFEST_CHANGED", "Execution snapshot differs from the exact grant", 409
        )
    return plan, request


def event(db: Session, job: BaselineRunJob, kind: str, code: str | None = None) -> None:
    db.add(
        ResearchEvent(
            event_id=uuid.uuid4(),
            user_id=job.user_id,
            event_type="baseline.run." + kind.lower(),
            occurred_at=now(),
            source="baseline-run-worker",
            correlation_id=job.id,
            payload={
                "job_id": str(job.id),
                "plan_id": str(job.plan_id),
                "status": job.status,
                "code": code,
            },
        )
    )


def _enqueue(db: Session, plan: BaselineRunPlan, key: str) -> BaselineRunJob:
    validate_plan(db, plan)
    identity = uuid.uuid4()
    request = build_request(db, plan, identity)
    payload = request_payload(request)
    if len(json.dumps(payload).encode()) > 4 * 1024 * 1024:
        raise DomainError(
            "BASELINE_RUN_REQUEST_TOO_LARGE", "Frozen execution snapshot exceeds its bound", 422
        )
    changed = db.execute(
        update(BaselineRunPlan)
        .where(
            BaselineRunPlan.id == plan.id,
            BaselineRunPlan.user_id == plan.user_id,
            BaselineRunPlan.state == "ACTIVE",
            BaselineRunPlan.sha256 == plan.sha256,
            BaselineRunPlan.used_jobs < BaselineRunPlan.max_jobs,
        )
        .values(used_jobs=BaselineRunPlan.used_jobs + 1)
        .execution_options(synchronize_session=False)
    )
    if cast(Any, changed).rowcount != 1:
        raise DomainError(
            "BASELINE_RUN_JOB_BUDGET_EXHAUSTED", "No execution jobs remain in this exact grant", 409
        )
    job = BaselineRunJob(
        id=identity,
        user_id=plan.user_id,
        project_id=plan.project_id,
        version_id=plan.version_id,
        plan_id=plan.id,
        status="QUEUED",
        manifest_sha256=request.request_sha256,
        manifest_payload=payload,
        idempotency_key=key,
        created_at=now(),
    )
    db.add(job)
    db.flush()
    db.add(
        BaselineRunPermit(
            id=uuid.uuid4(),
            user_id=plan.user_id,
            project_id=plan.project_id,
            version_id=plan.version_id,
            plan_id=plan.id,
            job_id=job.id,
            nonce=uuid.uuid4(),
            state="RESERVED",
            manifest_sha256=job.manifest_sha256,
            expires_at=plan.expires_at,
        )
    )
    event(db, job, "QUEUED")
    db.flush()
    return job


async def approve_plan(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    body: dto.BaselineRunPlanApprove,
    *,
    provider: BaselineRunProvider | None = None,
) -> BaselineRunPlan:
    plan = get_plan(db, owner, identity)
    if plan.sha256 != body.expected_sha256:
        raise DomainError(
            "BASELINE_RUN_APPROVAL_CONFLICT",
            "Review the exact execution scope before approval",
            409,
        )
    enabled()
    if plan.state == "ACTIVE" and plan.approved_sha256 == plan.sha256:
        return plan
    validate_plan(db, plan, active=False)
    if plan.state != "DRAFT" or utc(plan.expires_at) <= now() or json.loads(plan.gaps_text):
        raise DomainError(
            "BASELINE_RUN_PLAN_INCOMPLETE",
            "An unexpired complete draft with runtime evidence is required",
            409,
        )
    db.rollback()
    evidence = await (provider or provider_port()).runtime()
    plan = get_plan(db, owner, identity, lock=True)
    try:
        validate_plan(db, plan, active=False)
        runtime_valid(plan, evidence)
        if plan.state != "DRAFT" or plan.sha256 != body.expected_sha256:
            raise DomainError(
                "BASELINE_RUN_APPROVAL_CONFLICT", "Draft changed or is no longer approvable", 409
            )
        plan.state = "ACTIVE"
        plan.approved_by = owner
        plan.approved_sha256 = plan.sha256
        plan.approved_at = now()
        db.flush()
        _enqueue(db, plan, "initial-" + plan.id.hex)
        db.commit()
        db.refresh(plan)
        return plan
    except (DomainError, IntegrityError):
        db.rollback()
        raise


async def enqueue_job(
    db: Session,
    owner: uuid.UUID,
    identity: uuid.UUID,
    body: dto.BaselineRunJobCreate,
    *,
    provider: BaselineRunProvider | None = None,
) -> BaselineRunJob:
    plan = get_plan(db, owner, identity)
    existing = db.scalar(
        select(BaselineRunJob).where(
            BaselineRunJob.plan_id == identity,
            BaselineRunJob.user_id == owner,
            BaselineRunJob.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None:
        return existing
    enabled()
    validate_plan(db, plan)
    db.rollback()
    evidence = await (provider or provider_port()).runtime()
    plan = get_plan(db, owner, identity, lock=True)
    try:
        existing = db.scalar(
            select(BaselineRunJob).where(
                BaselineRunJob.plan_id == identity,
                BaselineRunJob.user_id == owner,
                BaselineRunJob.idempotency_key == body.idempotency_key,
            )
        )
        if existing is not None:
            return existing
        runtime_valid(plan, evidence)
        job = _enqueue(db, plan, body.idempotency_key)
        db.commit()
        db.refresh(job)
        return job
    except (DomainError, IntegrityError):
        db.rollback()
        raise


def permit(db: Session, job: BaselineRunJob) -> BaselineRunPermit:
    row = db.scalar(
        select(BaselineRunPermit)
        .where(
            BaselineRunPermit.job_id == job.id,
            BaselineRunPermit.plan_id == job.plan_id,
            BaselineRunPermit.version_id == job.version_id,
            BaselineRunPermit.project_id == job.project_id,
            BaselineRunPermit.user_id == job.user_id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError(
            "BASELINE_RUN_PERMIT_MISSING", "Exact execution reservation is missing", 409
        )
    return row


def cancel_job(db: Session, owner: uuid.UUID, identity: uuid.UUID) -> BaselineRunJob:
    job = get_job(db, owner, identity, lock=True)
    if job.status == "QUEUED":
        job.status = "CANCELLED"
        job.finished_at = now()
        permit(db, job).state = "REVOKED"
    elif job.status in {"STARTING", "RUNNING"}:
        job.status = "CANCEL_REQUESTED"
    event(db, job, "CANCEL_REQUESTED")
    db.commit()
    db.refresh(job)
    return job


def revoke_plan(db: Session, owner: uuid.UUID, identity: uuid.UUID) -> BaselineRunPlan:
    plan = get_plan(db, owner, identity, lock=True)
    plan.state = "REVOKED"
    jobs = list(
        db.scalars(
            select(BaselineRunJob)
            .where(
                BaselineRunJob.plan_id == identity,
                BaselineRunJob.user_id == owner,
                BaselineRunJob.status.in_(["QUEUED", "STARTING", "RUNNING"]),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for job in jobs:
        if job.status == "QUEUED":
            job.status = "CANCELLED"
            job.finished_at = now()
            permit(db, job).state = "REVOKED"
        else:
            job.status = "CANCEL_REQUESTED"
        event(db, job, "GRANT_REVOKED")
    db.commit()
    db.refresh(plan)
    return plan


def plan_out(db: Session, plan: BaselineRunPlan) -> dto.BaselineRunPlanOut:
    from app.domain.research_execution_policy import (
        LOCAL_RESEARCH_POLICY_CODE,
        local_research_execution_allowed,
    )

    current = True
    gaps = list(json.loads(plan.gaps_text))
    try:
        validate_plan(db, plan, active=False)
    except DomainError as error:
        current = False
        gaps.append(error.code)
    expired = utc(plan.expires_at) <= now()
    initial = db.scalar(
        select(BaselineRunJob.id)
        .where(BaselineRunJob.plan_id == plan.id, BaselineRunJob.user_id == plan.user_id)
        .order_by(BaselineRunJob.created_at, BaselineRunJob.id)
        .limit(1)
    )
    public = baselines._columns(
        plan, ("user_id", "random_seed", "gaps_text", "approved_by") + LIMIT_NAMES
    )
    return dto.BaselineRunPlanOut(
        **public,
        parameters=dto.BaselineRunParameters(random_seed=plan.random_seed),
        limits=dto.BaselineRunLimitsIn(**{key: getattr(plan, key) for key in LIMIT_NAMES}),
        expired=expired,
        jobs_remaining=max(0, plan.max_jobs - plan.used_jobs),
        context_current=current,
        can_approve=current
        and not gaps
        and not expired
        and plan.state == "DRAFT"
        and get_settings().baseline_runner_enabled
        and local_research_execution_allowed(),
        can_enqueue=current
        and not expired
        and plan.state == "ACTIVE"
        and plan.approved_sha256 == plan.sha256
        and plan.used_jobs < plan.max_jobs
        and get_settings().baseline_runner_enabled
        and local_research_execution_allowed(),
        gaps=list(
            dict.fromkeys(
                gaps + ([] if local_research_execution_allowed() else [LOCAL_RESEARCH_POLICY_CODE])
            )
        ),
        inputs=[
            dto.BaselineRunInputOut(
                **baselines._columns(
                    row, ("user_id", "project_id", "version_id", "plan_id", "source_scope_payload")
                )
            )
            for row in plan_inputs(db, plan)
        ],
        initial_job_id=initial,
    )


def job_out(db: Session, job: BaselineRunJob) -> dto.BaselineRunJobOut:
    p = permit(db, job)
    attempt = db.scalar(
        select(BaselineRunAttempt).where(
            BaselineRunAttempt.job_id == job.id,
            BaselineRunAttempt.user_id == job.user_id,
            BaselineRunAttempt.plan_id == job.plan_id,
            BaselineRunAttempt.version_id == job.version_id,
            BaselineRunAttempt.project_id == job.project_id,
        )
    )
    recorded = None
    if attempt is not None:
        recorded = dto.BaselineRunAttemptOut(
            **baselines._columns(
                attempt,
                (
                    "user_id",
                    "project_id",
                    "version_id",
                    "plan_id",
                    "job_id",
                    "permit_id",
                    "permit_nonce",
                    "issues_text",
                    "input_seal_payload",
                ),
            ),
            issues=json.loads(attempt.issues_text),
            input_seal=attempt.input_seal_payload,
        )
    arts = list(
        db.scalars(
            select(BaselineRunArtifact)
            .where(
                BaselineRunArtifact.job_id == job.id,
                BaselineRunArtifact.user_id == job.user_id,
                BaselineRunArtifact.project_id == job.project_id,
            )
            .order_by(BaselineRunArtifact.created_at, BaselineRunArtifact.id)
        )
    )
    return dto.BaselineRunJobOut(
        **baselines._columns(
            job,
            ("user_id", "active_owner_id", "manifest_payload", "lease_token", "lease_expires_at"),
        ),
        can_cancel=job.status in {"QUEUED", "STARTING", "RUNNING", "CANCEL_REQUESTED"}
        or job.status == "NEEDS_ATTENTION"
        and job.lease_token is None,
        can_reconcile=(
            job.status == "NEEDS_ATTENTION"
            or job.status == "FAILED"
            and job.error_code == "BASELINE_RUN_ARTIFACT_BACKUP_FAILED"
        )
        and job.lease_token is None,
        permit=dto.BaselineRunPermitOut.model_validate(
            {key: getattr(p, key) for key in dto.BaselineRunPermitOut.model_fields}
        ),
        attempt=recorded,
        artifacts=[
            dto.BaselineRunArtifactOut(
                **baselines._columns(
                    row, ("user_id", "project_id", "version_id", "plan_id", "job_id")
                )
            )
            for row in arts
        ],
    )


def list_plans(
    db: Session, owner: uuid.UUID, version_id: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[BaselineRunPlan], str | None]:
    version = baselines.get_version(db, owner, version_id)
    return baselines._page(
        db,
        BaselineRunPlan,
        [
            BaselineRunPlan.user_id == owner,
            BaselineRunPlan.version_id == version.id,
            BaselineRunPlan.project_id == version.project_id,
        ],
        limit,
        cursor,
    )


def list_jobs(
    db: Session, owner: uuid.UUID, plan_id: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[BaselineRunJob], str | None]:
    plan = get_plan(db, owner, plan_id)
    return baselines._page(
        db,
        BaselineRunJob,
        [
            BaselineRunJob.user_id == owner,
            BaselineRunJob.plan_id == plan.id,
            BaselineRunJob.version_id == plan.version_id,
            BaselineRunJob.project_id == plan.project_id,
        ],
        limit,
        cursor,
    )


def events_out(db: Session, job: BaselineRunJob) -> list[dto.BaselineRunEventOut]:
    rows = list(
        db.scalars(
            select(ResearchEvent)
            .where(
                ResearchEvent.user_id == job.user_id,
                ResearchEvent.correlation_id == job.id,
                ResearchEvent.event_type.like("baseline.run.%"),
            )
            .order_by(ResearchEvent.occurred_at, ResearchEvent.id)
        )
    )
    return [
        dto.BaselineRunEventOut(
            id=row.event_id,
            event_type=row.event_type,
            occurred_at=row.occurred_at,
            status=row.payload.get("status")
            if isinstance(row.payload.get("status"), str)
            else None,
            code=row.payload.get("code") if isinstance(row.payload.get("code"), str) else None,
        )
        for row in rows
    ]
