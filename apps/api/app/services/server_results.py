"""Import server evidence as data; never execute or confer scientific qualification."""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.errors import DomainError
from app.models import Attachment, Task
from app.models_research_briefs import ResearchBrief
from app.models_server_results import (
    ServerResult,
    ServerResultArtifact,
    ServerResultBriefLink,
    ServerResultMetric,
    ServerResultReview,
    ServerResultTaskAction,
)
from app.models_server_task_packages import (
    ServerTaskPackage,
    ServerTaskPackageAsset,
    ServerTaskPackageExpectedArtifact,
    ServerTaskPackageFile,
    ServerTaskPackageTask,
)
from app.providers import registry
from app.schemas import PageMeta
from app.schemas_research_briefs import ResearchBriefCreate
from app.schemas_server_results import (
    ServerResultArtifactOut,
    ServerResultEnvelope,
    ServerResultMetricOut,
    ServerResultNextBriefOut,
    ServerResultNextBriefRequest,
    ServerResultOptions,
    ServerResultOut,
    ServerResultPackageOption,
    ServerResultRetryRequest,
    ServerResultReviewOut,
    ServerResultReviewRequest,
    ServerResultSummary,
    ServerResultTaskOption,
)
from app.services import research_briefs as briefs
from app.services import server_task_packages as packages
from app.services.common import cursor_filter, encode_cursor
from app.services.projects import get_project

MAX_BYTES = 32 * 1024 * 1024
SCOPE_NOTE = "服务器运行与指标仅为来源声明；文件/hash与签名核对不证明实验执行授权、科学正确或复现成功。本人审阅与原始证据分开；不运行本地科研。"


def upload_limit() -> int:
    return min(MAX_BYTES, get_settings().server_result_max_upload_mb * 1024 * 1024)


def error(code: str, message: str, status: int = 409) -> DomainError:
    details = (
        {"committed": False}
        if code
        in {
            "RESULT_TASK_CHANGED",
            "RESULT_REVIEW_CHANGED",
            "RESULT_GAPS_ACK_REQUIRED",
            "RESULT_NOT_ACCEPTED",
        }
        else None
    )
    return DomainError(code, message, status, details=details)


def get_result(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> ServerResult:
    get_project(db, owner, project_id)
    query = (
        select(ServerResult)
        .where(
            ServerResult.id == identity,
            ServerResult.user_id == owner,
            ServerResult.project_id == project_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise error("NOT_FOUND", "Owned server result not found", 404)
    return row


def children(db: Session, row: ServerResult, model: Any) -> list[Any]:
    query = select(model).where(
        model.result_id == row.id, model.user_id == row.user_id, model.project_id == row.project_id
    )
    if hasattr(model, "position"):
        query = query.order_by(model.position)
    elif hasattr(model, "reviewed_at"):
        query = query.order_by(model.reviewed_at, model.id)
    return list(db.scalars(query))


def options(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> ServerResultOptions:
    project = get_project(db, owner, project_id)
    rows = list(
        db.scalars(
            select(ServerTaskPackage)
            .where(
                ServerTaskPackage.user_id == owner,
                ServerTaskPackage.project_id == project_id,
                ServerTaskPackage.status == "READY",
                cursor_filter(ServerTaskPackage, cursor),
            )
            .order_by(ServerTaskPackage.created_at.desc(), ServerTaskPackage.id.desc())
            .limit(limit + 1)
        )
    )
    provider = registry.server_receipt_authentication()
    return ServerResultOptions(
        owner_id=owner,
        project_id=project_id,
        project_name=project.name,
        packages=[
            ServerResultPackageOption(
                id=x.id,
                label=x.label,
                bundle_sha256=x.bundle_sha256,
                preview_sha256=x.preview_sha256,
                readiness=x.readiness,
            )
            for x in rows[:limit]
        ],
        page=PageMeta(
            limit=limit,
            next_cursor=encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None,
        ),
        configured_server_id=getattr(provider, "configured_server_id", None),
        signature_verification_configured=getattr(provider, "configured", False),
        scope_note=SCOPE_NOTE,
    )


def list_results(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[ServerResult], str | None]:
    get_project(db, owner, project_id)
    rows = list(
        db.scalars(
            select(ServerResult)
            .where(
                ServerResult.user_id == owner,
                ServerResult.project_id == project_id,
                cursor_filter(ServerResult, cursor),
            )
            .order_by(ServerResult.created_at.desc(), ServerResult.id.desc())
            .limit(limit + 1)
        )
    )
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None


def summary_out(row: ServerResult) -> ServerResultSummary:
    return ServerResultSummary(
        **{key: getattr(row, key) for key in ServerResultSummary.model_fields}
    )


def review_out(db: Session, row: ServerResultReview) -> ServerResultReviewOut:
    completed = list(
        db.scalars(
            select(ServerResultTaskAction.task_id).where(
                ServerResultTaskAction.review_id == row.id,
                ServerResultTaskAction.user_id == row.user_id,
            )
        )
    )
    return ServerResultReviewOut(
        id=row.id,
        decision=row.decision,
        conclusion=row.conclusion,
        acknowledge_gaps=row.acknowledge_gaps,
        reviewed_at=row.reviewed_at,
        completed_task_ids=completed,
    )


def detail_out(db: Session, row: ServerResult) -> ServerResultOut:
    tasks = list(
        db.scalars(
            select(Task)
            .join(ServerTaskPackageTask, ServerTaskPackageTask.task_id == Task.id)
            .where(
                ServerTaskPackageTask.package_id == row.package_id,
                Task.user_id == row.user_id,
                Task.project_id == row.project_id,
            )
        )
    )
    return ServerResultOut(
        **summary_out(row).model_dump(),
        **{
            key: getattr(row, key)
            for key in (
                "receipt_sha256",
                "input_sha256",
                "claimed_job_id",
                "git_commit",
                "protocol_sha256",
                "config_sha256",
                "dataset_sha256",
                "started_at",
                "ended_at",
                "notes",
                "gaps",
            )
        },
        metrics=[
            ServerResultMetricOut(**{k: getattr(x, k) for k in ServerResultMetricOut.model_fields})
            for x in children(db, row, ServerResultMetric)
        ],
        artifacts=[
            ServerResultArtifactOut(
                **{k: getattr(x, k) for k in ServerResultArtifactOut.model_fields}
            )
            for x in children(db, row, ServerResultArtifact)
        ],
        reviews=[review_out(db, x) for x in children(db, row, ServerResultReview)],
        linked_tasks=[
            ServerResultTaskOption(id=x.id, title=x.title, status=x.status, version=x.version)
            for x in tasks
        ],
        next_brief_ids=[x.brief_id for x in children(db, row, ServerResultBriefLink)],
        scope_note=SCOPE_NOTE,
    )


def _column_value(value: Any) -> str | None:
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=UTC).isoformat()
            if value.tzinfo is None
            else value.astimezone(UTC).isoformat()
        )
    return str(value) if value is not None else None


def _payload(db: Session, row: ServerResult) -> dict[str, Any]:
    return {
        "identity": {
            k: str(getattr(row, k))
            for k in (
                "id",
                "user_id",
                "project_id",
                "package_id",
                "idempotency_key",
                "request_sha256",
                "server_identity",
            )
        },
        "receipt_sha256": row.receipt_sha256,
        "input_sha256": row.input_sha256,
        "raw_envelope": row.raw_envelope,
        "origin": row.origin_verification,
        "columns": {
            key: _column_value(getattr(row, key))
            for key in (
                "receipt_id",
                "server_id",
                "claimed_run_status",
                "claimed_job_id",
                "git_commit",
                "protocol_sha256",
                "config_sha256",
                "dataset_sha256",
                "started_at",
                "ended_at",
                "notes",
            )
        },
        "validation": row.validation_status,
        "match": row.match_snapshot,
        "gaps": row.gaps,
        "metrics": [
            {
                k: getattr(x, k)
                for k in ("position", "name", "value", "unit", "split", "evaluation_protocol")
            }
            for x in children(db, row, ServerResultMetric)
        ],
        "artifacts": [
            {
                k: getattr(x, k)
                for k in (
                    "position",
                    "path",
                    "sha256",
                    "size_bytes",
                    "mime_type",
                    "included",
                    "verification",
                    "actual_sha256",
                    "actual_size_bytes",
                    "attachment_id",
                )
            }
            for x in children(db, row, ServerResultArtifact)
        ],
    }


def result_hash(db: Session, row: ServerResult) -> str:
    payload = _payload(db, row)
    attachment_ids = {
        x.attachment_id for x in children(db, row, ServerResultArtifact) if x.attachment_id
    }
    if row.input_attachment_id:
        attachment_ids.add(row.input_attachment_id)
    payload["attachment_facts"] = [
        {
            key: _column_value(getattr(x, key))
            for key in (
                "id",
                "user_id",
                "storage_provider",
                "object_key",
                "sha256",
                "size_bytes",
                "mime_type",
                "deleted_at",
            )
        }
        for x in db.scalars(
            select(Attachment).where(Attachment.id.in_(attachment_ids)).order_by(Attachment.id)
        )
    ]
    for artifact in payload["artifacts"]:
        if artifact["attachment_id"]:
            artifact["attachment_id"] = str(artifact["attachment_id"])
    return briefs.digest(payload)


def _intact(db: Session, row: ServerResult) -> bool:
    try:
        canonical = json.dumps(
            row.raw_envelope["receipt"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != row.receipt_sha256:
            return False
        receipt = ServerResultEnvelope.model_validate(row.raw_envelope).receipt
        values = receipt.model_dump(mode="json")
        fields = (
            "receipt_id",
            "server_id",
            "claimed_run_status",
            "claimed_job_id",
            "git_commit",
            "protocol_sha256",
            "config_sha256",
            "dataset_sha256",
            "notes",
        )
        if any(getattr(row, k) != values[k] for k in fields):
            return False
        metrics = [
            {k: getattr(x, k) for k in ("name", "value", "unit", "split", "evaluation_protocol")}
            for x in children(db, row, ServerResultMetric)
        ]
        if metrics != values["metrics"]:
            return False
        artifacts = [
            {k: getattr(x, k) for k in ("path", "sha256", "size_bytes", "mime_type", "included")}
            for x in children(db, row, ServerResultArtifact)
        ]
        return artifacts == values["artifacts"] and result_hash(db, row) == row.result_sha256
    except (ValueError, TypeError, KeyError):
        return False


def _match(
    db: Session, package: ServerTaskPackage, receipt: Any, artifacts: Any
) -> tuple[dict[str, Any], list[str], str]:
    gaps = []
    mismatch = False
    expected: dict[str, Any] = {
        "package_id": str(package.id),
        "package_bundle_sha256": package.bundle_sha256,
        "package_preview_sha256": package.preview_sha256,
    }
    for key, initial_value in expected.items():
        if str(getattr(receipt, key)) != initial_value:
            gaps.append(key.upper() + "_MISMATCH")
            mismatch = True
    archive = package.source_snapshot.get("archive")
    commit = archive.get("version", {}).get("commit_sha") if archive else None
    sections = package.source_snapshot.get("brief", {}).get("sections", [])
    protocol = next((x.get("content") for x in sections if x.get("key") == "protocol"), None)
    protocol_sha = hashlib.sha256(protocol.encode()).hexdigest() if protocol else None
    configs = list(
        db.scalars(
            select(ServerTaskPackageFile).where(
                ServerTaskPackageFile.package_id == package.id,
                ServerTaskPackageFile.user_id == package.user_id,
                ServerTaskPackageFile.role == "CONFIG",
            )
        )
    )
    config_sha = configs[0].sha256 if len(configs) == 1 else None
    datasets = list(
        db.scalars(
            select(ServerTaskPackageAsset).where(
                ServerTaskPackageAsset.package_id == package.id,
                ServerTaskPackageAsset.user_id == package.user_id,
                ServerTaskPackageAsset.kind == "DATASET",
            )
        )
    )
    dataset_sha = datasets[0].sha256 if len(datasets) == 1 else None
    if package.readiness != "READY_FOR_SERVER_REVIEW":
        gaps.append("PACKAGE_DECLARED_INCOMPLETE")
    for key, value in (
        ("git_commit", commit),
        ("protocol_sha256", protocol_sha),
        ("config_sha256", config_sha),
        ("dataset_sha256", dataset_sha),
    ):
        expected[key] = value
        claim = getattr(receipt, key)
        if value is None:
            gaps.append(key.upper() + "_BINDING_NOT_VERIFIED")
        elif claim is None:
            gaps.append(key.upper() + "_NOT_REPORTED")
        elif claim != value:
            gaps.append(key.upper() + "_MISMATCH")
            mismatch = True
    gaps.append("DATASET_EXECUTION_NOT_VERIFIED")
    declared = {x.path: x for x in artifacts}
    expected_paths = list(
        db.scalars(
            select(ServerTaskPackageExpectedArtifact.path).where(
                ServerTaskPackageExpectedArtifact.package_id == package.id,
                ServerTaskPackageExpectedArtifact.user_id == package.user_id,
            )
        )
    )
    expected["expected_artifacts"] = expected_paths
    for path in expected_paths:
        if path not in declared:
            gaps.append("EXPECTED_ARTIFACT_MISSING:" + path)
    for artifact in artifacts:
        if artifact.verification == "MISMATCH":
            gaps.append("ARTIFACT_MISMATCH:" + artifact.path)
            mismatch = True
        elif artifact.verification != "BYTES_VERIFIED":
            gaps.append("ARTIFACT_NOT_VERIFIED:" + artifact.path)
    return expected, gaps, "MISMATCH" if mismatch else "GAPS" if gaps else "MATCHED"


async def _save_bytes(
    content: bytes, mime: str, observations: list[dict[str, Any]], path: str
) -> tuple[Any, Any]:
    provider = registry.storage_provider()

    async def chunks() -> AsyncIterator[bytes]:
        yield content

    stored = await provider.save(
        chunks(), mime_type=mime, max_bytes=MAX_BYTES, allow_empty=not content
    )
    if (
        stored.sha256 != hashlib.sha256(content).hexdigest()
        or stored.size_bytes != len(content)
        or stored.mime_type != mime
        or not stored.key
        or len(stored.key) > 320
    ):
        raise error("STORAGE_RECEIPT_INVALID", "Stored receipt differs from input")
    observation = {
        "path": path,
        "storage_provider": provider.provider_key,
        "object_key": stored.key,
        "sha256": stored.sha256,
        "size_bytes": stored.size_bytes,
        "mime_type": stored.mime_type,
        "readback_verified": False,
    }
    observations.append(observation)
    reader = await provider.open(stored.key)
    raw = bytearray()
    try:
        if reader.size_bytes != len(content):
            raise error("STORAGE_OBJECT_CHANGED", "Stored size differs")
        async for chunk in reader.iter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise error("STORAGE_OBJECT_CHANGED", "Stored object exceeds bounds")
    finally:
        await reader.close()
    if bytes(raw) != content:
        raise error("STORAGE_OBJECT_CHANGED", "Read-back bytes differ")
    observation["readback_verified"] = True
    return provider, stored


def _attachment(db: Session, owner: uuid.UUID, provider: Any, stored: Any, name: str) -> Attachment:
    row = db.scalar(select(Attachment).where(Attachment.object_key == stored.key))
    if row is not None:
        if (
            row.user_id != owner
            or row.storage_provider != provider.provider_key
            or row.sha256 != stored.sha256
            or row.size_bytes != stored.size_bytes
            or row.mime_type != stored.mime_type
            or row.deleted_at is not None
        ):
            raise error(
                "STORAGE_OBJECT_CONFLICT", "Existing object has conflicting ownership or metadata"
            )
        return row
    row = Attachment(
        id=uuid.uuid4(),
        user_id=owner,
        storage_provider=provider.provider_key,
        object_key=stored.key,
        original_filename=name,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
    )
    db.add(row)
    db.flush()
    return row


async def import_result(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    key: str,
    content: bytes,
) -> ServerResult:
    if not key or len(key) > 120:
        raise error("VALIDATION_ERROR", "Import key length is invalid", 422)
    if not content or len(content) > upload_limit():
        raise DomainError(
            "RESULT_SIZE_LIMIT",
            "Result ZIP is outside upload bounds",
            413,
            details={"admitted": False},
        )
    get_project(db, owner, project_id)
    early_request_sha = briefs.digest(
        {"package_id": str(package_id), "input_sha256": hashlib.sha256(content).hexdigest()}
    )
    prior_input = db.scalar(
        select(ServerResult).where(
            ServerResult.user_id == owner,
            ServerResult.project_id == project_id,
            ServerResult.idempotency_key == key,
        )
    )
    if prior_input is not None:
        if prior_input.request_sha256 != early_request_sha:
            raise error("IDEMPOTENCY_CONFLICT", "Key already refers to another input")
        return prior_input
    package = packages.get_package(db, owner, project_id, package_id)
    if package.status != "READY" or not packages._frozen_intact(db, package):
        raise error("SERVER_RESULT_PACKAGE_INVALID", "Require an intact READY package")
    parsed, envelope = _parse(content)
    receipt = envelope.receipt
    auth = registry.server_receipt_authentication().verify(
        canonical_receipt=parsed.canonical_receipt,
        server_id=receipt.server_id,
        signature=envelope.signature,
    )
    request_sha = briefs.digest(
        {"package_id": str(package_id), "input_sha256": parsed.input_sha256}
    )
    existing = db.scalar(
        select(ServerResult).where(
            ServerResult.user_id == owner,
            ServerResult.project_id == project_id,
            ServerResult.idempotency_key == key,
        )
    )
    if existing:
        if existing.request_sha256 != request_sha:
            raise error("IDEMPOTENCY_CONFLICT", "Key already refers to another input")
        return existing
    duplicate = db.scalar(
        select(ServerResult).where(
            ServerResult.user_id == owner,
            ServerResult.package_id == package_id,
            ServerResult.server_identity == (receipt.server_id or ""),
            ServerResult.receipt_id == receipt.receipt_id,
        )
    )
    if duplicate:
        if duplicate.input_sha256 != parsed.input_sha256:
            raise error("RECEIPT_CONFLICT", "Receipt identity already refers to different bytes")
        return duplicate
    match, gaps, validation = _match(db, package, receipt, parsed.artifacts)
    gaps = list(dict.fromkeys([*gaps, *parsed.gaps, *auth.gaps]))
    if auth.origin_verification == "INVALID_SIGNATURE":
        validation = "MISMATCH"
    elif gaps and validation == "MATCHED":
        validation = "GAPS"
    token = uuid.uuid4()
    identity = uuid.uuid4()
    package_sha = package.preview_sha256
    row = ServerResult(
        id=identity,
        user_id=owner,
        project_id=project_id,
        package_id=package_id,
        idempotency_key=key,
        request_sha256=request_sha,
        receipt_id=receipt.receipt_id,
        server_identity=receipt.server_id or "",
        server_id=receipt.server_id,
        status="IMPORTING",
        validation_status=validation,
        origin_verification=auth.origin_verification,
        review_status="UNREVIEWED",
        result_sha256="0" * 64,
        receipt_sha256=parsed.receipt_sha256,
        input_sha256=parsed.input_sha256,
        import_token=token,
        raw_envelope=parsed.envelope,
        match_snapshot=match,
        storage_observations=[
            {
                "token": str(token),
                "key": "initial-import",
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "status": "IMPORTING",
                "facts": [],
                "acknowledge_unknown": False,
            }
        ],
        gaps=gaps,
        **{
            k: getattr(receipt, k).astimezone(UTC)
            if k in ("started_at", "ended_at") and getattr(receipt, k) is not None
            else getattr(receipt, k)
            for k in (
                "claimed_run_status",
                "claimed_job_id",
                "git_commit",
                "protocol_sha256",
                "config_sha256",
                "dataset_sha256",
                "started_at",
                "ended_at",
                "notes",
            )
        },
    )
    db.add(row)
    db.flush()
    for pos, metric in enumerate(receipt.metrics):
        db.add(
            ServerResultMetric(
                result_id=identity,
                project_id=project_id,
                user_id=owner,
                position=pos,
                **metric.model_dump(),
            )
        )
    for pos, item in enumerate(receipt.artifacts):
        actual = parsed.artifacts[pos]
        verification = (
            "DECLARED_NOT_INCLUDED"
            if not item.included
            else "MISSING"
            if actual.content is None
            else "MISMATCH"
        )
        db.add(
            ServerResultArtifact(
                result_id=identity,
                project_id=project_id,
                user_id=owner,
                position=pos,
                **item.model_dump(),
                verification=verification,
                actual_sha256=actual.actual_sha256,
                actual_size_bytes=actual.actual_size_bytes,
            )
        )
    db.flush()
    row.result_sha256 = result_hash(db, row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise error(
            "RESULT_IMPORT_CONFLICT", "Concurrent import; reload the existing result"
        ) from None
    return await _perform_save(db, owner, project_id, identity, token, parsed, content, package_sha)


def download_attachment(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, identity: uuid.UUID
) -> Attachment:
    row = get_result(db, owner, project_id, identity)
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == row.input_attachment_id,
            Attachment.user_id == owner,
            Attachment.deleted_at.is_(None),
        )
    )
    if attachment is None or attachment.sha256 != row.input_sha256:
        raise error("RESULT_INPUT_NOT_VERIFIED", "No verified original ZIP is available")
    return attachment


def review_result(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    identity: uuid.UUID,
    body: ServerResultReviewRequest,
) -> ServerResultReviewOut:
    row = get_result(db, owner, project_id, identity, lock=True)
    request_sha = briefs.digest(body.model_dump(mode="json"))
    prior = db.scalar(
        select(ServerResultReview).where(
            ServerResultReview.result_id == identity,
            ServerResultReview.user_id == owner,
            ServerResultReview.idempotency_key == body.idempotency_key,
        )
    )
    if prior:
        if prior.request_sha256 != request_sha:
            raise error("IDEMPOTENCY_CONFLICT", "Review key differs from original decision")
        return review_out(db, prior)
    if (
        row.status != "READY"
        or not _intact(db, row)
        or row.result_sha256 != body.expected_result_sha256
    ):
        raise error("RESULT_REVIEW_CHANGED", "Reload the intact READY result before review")
    if body.decision == "ACCEPT" and row.gaps and not body.acknowledge_gaps:
        raise error("RESULT_GAPS_ACK_REQUIRED", "Acceptance requires explicit gap acknowledgement")
    if body.complete_tasks and body.decision != "ACCEPT":
        raise error(
            "RESULT_TASK_ACCEPT_REQUIRED", "Only explicit ACCEPT can complete selected tasks"
        )
    if len({x.task_id for x in body.complete_tasks}) != len(body.complete_tasks):
        raise error("VALIDATION_ERROR", "Task identities must be unique", 422)
    linked = set(
        db.scalars(
            select(ServerTaskPackageTask.task_id).where(
                ServerTaskPackageTask.package_id == row.package_id,
                ServerTaskPackageTask.user_id == owner,
            )
        )
    )
    selected = []
    for choice in body.complete_tasks:
        task = db.scalar(
            select(Task)
            .where(Task.id == choice.task_id, Task.user_id == owner, Task.project_id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            task is None
            or task.id not in linked
            or task.version != choice.expected_version
            or task.status not in ("todo", "in_progress")
        ):
            raise error(
                "RESULT_TASK_CHANGED", "A selected original task changed; no tasks were updated"
            )
        selected.append(task)
    review = ServerResultReview(
        id=uuid.uuid4(),
        result_id=identity,
        project_id=project_id,
        user_id=owner,
        result_sha256=row.result_sha256,
        request_sha256=request_sha,
        idempotency_key=body.idempotency_key,
        decision=body.decision,
        conclusion=body.conclusion,
        acknowledge_gaps=body.acknowledge_gaps,
    )
    db.add(review)
    db.flush()
    for task in selected:
        db.add(
            ServerResultTaskAction(
                result_id=identity,
                project_id=project_id,
                user_id=owner,
                review_id=review.id,
                task_id=task.id,
                before_status=task.status,
                after_status="completed",
                before_version=task.version,
                after_version=task.version + 1,
            )
        )
        task.status = "completed"
        task.version += 1
        task.completed_at = datetime.now(UTC)
    if body.decision in ("ACCEPT", "REJECT"):
        row.review_status = "ACCEPTED" if body.decision == "ACCEPT" else "REJECTED"
    db.commit()
    db.refresh(review)
    return review_out(db, review)


def next_brief(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    identity: uuid.UUID,
    body: ServerResultNextBriefRequest,
) -> ServerResultNextBriefOut:
    row = get_result(db, owner, project_id, identity, lock=True)
    request_sha = briefs.digest(body.model_dump(mode="json"))
    prior = db.scalar(
        select(ServerResultBriefLink).where(
            ServerResultBriefLink.result_id == identity,
            ServerResultBriefLink.user_id == owner,
            ServerResultBriefLink.idempotency_key == body.idempotency_key,
        )
    )
    if prior:
        if prior.request_sha256 != request_sha:
            raise error("IDEMPOTENCY_CONFLICT", "Next brief key differs from original request")
        return ServerResultNextBriefOut(result_id=identity, brief_id=prior.brief_id)
    if (
        row.status != "READY"
        or row.review_status != "ACCEPTED"
        or row.result_sha256 != body.expected_result_sha256
        or not _intact(db, row)
    ):
        raise error("RESULT_NOT_ACCEPTED", "Require the intact, owner-accepted result")
    reviews = children(db, row, ServerResultReview)
    accepted = next((x for x in reversed(reviews) if x.decision in ("ACCEPT", "REJECT")), None)
    if (
        accepted is None
        or accepted.decision != "ACCEPT"
        or accepted.result_sha256 != row.result_sha256
    ):
        raise error("RESULT_REVIEW_CHANGED", "Acceptance receipt does not match result")
    latest = db.scalar(
        select(ResearchBrief)
        .where(ResearchBrief.user_id == owner, ResearchBrief.project_id == project_id)
        .order_by(ResearchBrief.revision.desc())
        .limit(1)
    )
    created = briefs.create_brief(
        db,
        owner,
        project_id,
        ResearchBriefCreate(
            idea=body.idea,
            sections=body.sections,
            stop_rules=body.stop_rules,
            base_brief_id=latest.id if latest else None,
            expected_base_sha256=latest.sha256 if latest else None,
        ),
        commit=False,
    )
    db.add(
        ServerResultBriefLink(
            result_id=identity,
            project_id=project_id,
            user_id=owner,
            review_id=accepted.id,
            brief_id=created.id,
            result_sha256=row.result_sha256,
            request_sha256=request_sha,
            idempotency_key=body.idempotency_key,
        )
    )
    db.commit()
    return ServerResultNextBriefOut(result_id=identity, brief_id=created.id)


def lookup(db: Session, owner: uuid.UUID, project_id: uuid.UUID, key: str) -> ServerResult:
    get_project(db, owner, project_id)
    row = db.scalar(
        select(ServerResult).where(
            ServerResult.user_id == owner,
            ServerResult.project_id == project_id,
            ServerResult.idempotency_key == key,
        )
    )
    if row is None:
        raise error("NOT_FOUND", "No result import receipt for this key", 404)
    return row


async def _perform_save(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    identity: uuid.UUID,
    token: uuid.UUID,
    parsed: Any,
    content: bytes,
    package_sha: str,
) -> ServerResult:
    row = get_result(db, owner, project_id, identity)
    package_id = row.package_id
    receipt = ServerResultEnvelope.model_validate(parsed.envelope).receipt
    existing_input = (
        db.get(Attachment, row.input_attachment_id) if row.input_attachment_id else None
    )
    existing_artifacts = {
        x.position: db.get(Attachment, x.attachment_id)
        for x in children(db, row, ServerResultArtifact)
        if x.attachment_id
    }
    known = {None: existing_input, **existing_artifacts}
    known_facts = {
        position: {
            k: getattr(value, k)
            for k in (
                "id",
                "user_id",
                "storage_provider",
                "object_key",
                "sha256",
                "size_bytes",
                "mime_type",
                "deleted_at",
            )
        }
        for position, value in known.items()
        if value is not None
    }
    # Release transactions before any storage save or readback.
    db.rollback()
    saved: list[tuple[int | None, Any, Any]] = []
    observations: list[dict[str, Any]] = []
    failure = None
    try:
        if None in known_facts:
            await _verify_known(known_facts[None], owner, content)
        else:
            provider, stored = await _save_bytes(
                content, "application/zip", observations, "original_input.zip"
            )
            saved.append((None, provider, stored))
        for pos, parsed_item in enumerate(parsed.artifacts):
            if parsed_item.content is not None:
                if pos in known_facts:
                    await _verify_known(known_facts[pos], owner, parsed_item.content)
                    continue
                provider, stored = await _save_bytes(
                    parsed_item.content,
                    receipt.artifacts[pos].mime_type,
                    observations,
                    receipt.artifacts[pos].path,
                )
                saved.append((pos, provider, stored))
    except Exception:
        failure = "RESULT_STORAGE_OUTCOME_UNKNOWN"
    db.expire_all()
    current = get_result(db, owner, project_id, identity, lock=True)
    now_package = packages.get_package(db, owner, project_id, package_id)
    intact = (
        current.import_token == token
        and current.status == "IMPORTING"
        and _intact(db, current)
        and now_package.preview_sha256 == package_sha
        and packages._frozen_intact(db, now_package)
    )
    fenced = current.import_token != token or current.status != "IMPORTING"
    artifacts = children(db, current, ServerResultArtifact)
    try:
        for saved_pos, provider, stored in saved:
            fact = _attachment(
                db,
                owner,
                provider,
                stored,
                "server-result-" + str(identity) + ".zip"
                if saved_pos is None
                else receipt.artifacts[saved_pos].path.rsplit("/", 1)[-1],
            )
            if fenced:
                continue
            if saved_pos is None:
                current.input_attachment_id = fact.id
            else:
                artifacts[saved_pos].attachment_id = fact.id
                artifacts[saved_pos].verification = parsed.artifacts[saved_pos].verification
    except DomainError:
        failure = "RESULT_STORAGE_FACT_CONFLICT"
    audit = [dict(x) for x in current.storage_observations]
    attempt = next((x for x in audit if x.get("token") == str(token)), None)
    if attempt is None:
        attempt = {"token": str(token), "key": "late-observed", "facts": []}
        audit.append(attempt)
    attempt.update(
        {
            "finished_at": datetime.now(UTC).isoformat(),
            "status": "LATE" if fenced else "NEEDS_ATTENTION" if failure else "READY",
            "facts": [*attempt.get("facts", []), *observations],
            "error_code": failure,
        }
    )
    current.storage_observations = audit
    if fenced:
        db.commit()
        return current
    if not intact:
        failure = "RESULT_IMPORT_SOURCE_CHANGED"
    current.status = "NEEDS_ATTENTION" if failure else "READY"
    current.error_code = failure
    current.error_message = None
    if failure:
        current.error_code = failure
        current.error_message = (
            "Import outcome requires inspection; the same key does not replay storage writes."
        )
    db.flush()
    current.result_sha256 = result_hash(db, current)
    db.commit()
    db.refresh(current)
    return current


def _parse(content: bytes) -> tuple[Any, ServerResultEnvelope]:
    try:
        parsed = registry.server_result_bundle_parser().parse(content, max_bytes=upload_limit())
    except ValueError:
        raise DomainError(
            "RESULT_BUNDLE_INVALID",
            "Result bundle is malformed or violates safe data limits",
            422,
            details={"admitted": False},
        ) from None
    envelope = ServerResultEnvelope.model_validate(parsed.envelope)
    receipt = envelope.receipt
    canonical = json.dumps(
        parsed.envelope["receipt"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if (
        parsed.input_sha256 != hashlib.sha256(content).hexdigest()
        or parsed.canonical_receipt != canonical
        or parsed.receipt_sha256 != hashlib.sha256(canonical).hexdigest()
        or len(parsed.artifacts) != len(receipt.artifacts)
    ):
        raise DomainError(
            "RESULT_PARSER_CONTRACT_INVALID",
            "Parser output does not match original input bytes",
            422,
            details={"admitted": False},
        )
    for declaration, actual in zip(receipt.artifacts, parsed.artifacts, strict=True):
        expected_verification = (
            "DECLARED_NOT_INCLUDED"
            if not declaration.included
            else "MISSING"
            if actual.content is None
            else "BYTES_VERIFIED"
            if hashlib.sha256(actual.content).hexdigest() == declaration.sha256
            and len(actual.content) == declaration.size_bytes
            else "MISMATCH"
        )
        actual_hash = (
            hashlib.sha256(actual.content).hexdigest() if actual.content is not None else None
        )
        actual_size = len(actual.content) if actual.content is not None else None
        if (
            actual.path != declaration.path
            or actual.mime_type != declaration.mime_type
            or actual.verification != expected_verification
            or actual.actual_sha256 != actual_hash
            or actual.actual_size_bytes != actual_size
            or (not declaration.included and actual.content is not None)
        ):
            raise DomainError(
                "RESULT_PARSER_CONTRACT_INVALID",
                "Parser artifact facts do not match received bytes",
                422,
                details={"admitted": False},
            )
    return parsed, envelope


async def _read_known(fact: dict[str, Any], owner: uuid.UUID) -> bytes:
    if fact["user_id"] != owner or fact["deleted_at"] is not None:
        raise error("RESULT_INPUT_NOT_VERIFIED", "Owned stored object is unavailable")
    provider = registry.storage_provider(fact["storage_provider"])
    reader = await provider.open(fact["object_key"])
    raw = bytearray()
    try:
        if reader.size_bytes != fact["size_bytes"] or reader.size_bytes > MAX_BYTES:
            raise error("STORAGE_OBJECT_CHANGED", "Known object size differs")
        async for chunk in reader.iter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise error("STORAGE_OBJECT_CHANGED", "Known object exceeds bound")
    finally:
        await reader.close()
    if len(raw) != fact["size_bytes"] or hashlib.sha256(raw).hexdigest() != fact["sha256"]:
        raise error("STORAGE_OBJECT_CHANGED", "Known object checksum differs")
    return bytes(raw)


async def _verify_known(fact: dict[str, Any], owner: uuid.UUID, expected: bytes) -> None:
    if await _read_known(fact, owner) != expected:
        raise error("STORAGE_OBJECT_CHANGED", "Known object differs from original input")


async def retry_import(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    identity: uuid.UUID,
    body: ServerResultRetryRequest,
    content: bytes | None = None,
) -> ServerResult:
    row = get_result(db, owner, project_id, identity, lock=True)
    body_sha = briefs.digest(body.model_dump(mode="json"))
    if body.input_sha256 != row.input_sha256 or (
        content is not None and hashlib.sha256(content).hexdigest() != row.input_sha256
    ):
        raise DomainError(
            "RESULT_RETRY_INPUT_CHANGED",
            "Select the exact original uploaded ZIP",
            409,
            details={"committed": False},
        )
    attempt = next(
        (x for x in row.storage_observations if x.get("key") == body.retry_idempotency_key), None
    )
    if attempt:
        if attempt.get("request_sha256") != body_sha:
            raise error("IDEMPOTENCY_CONFLICT", "Retry key differs from original request")
        return row
    if (
        row.status == "READY"
        or row.review_status != "UNREVIEWED"
        or row.result_sha256 != body.expected_result_sha256
        or not _intact(db, row)
    ):
        raise DomainError(
            "RESULT_RETRY_CHANGED",
            "Require the intact unreviewed non-READY result exact checksum",
            409,
            details={"committed": False},
        )
    if len(row.storage_observations) >= 50:
        raise DomainError(
            "RESULT_RETRY_LIMIT",
            "Recovery attempt limit reached; export the preserved audit before maintenance",
            409,
            details={"committed": False},
        )
    if row.status not in ("NEEDS_ATTENTION", "FAILED", "IMPORTING"):
        raise error("RESULT_RETRY_UNAVAILABLE", "This import state cannot recover")
    if not body.acknowledge_unknown:
        raise DomainError(
            "RESULT_RETRY_ACK_REQUIRED",
            "Recovery may repeat a storage write and fences prior callbacks",
            409,
            details={"committed": False},
        )
    if row.status == "IMPORTING":
        current_attempt = next(
            (x for x in row.storage_observations if x.get("token") == str(row.import_token)), None
        )
        started = (
            datetime.fromisoformat(current_attempt["started_at"])
            if current_attempt and current_attempt.get("started_at")
            else row.created_at
        )
        started = started.replace(tzinfo=UTC) if started.tzinfo is None else started.astimezone(UTC)
        if (datetime.now(UTC) - started).total_seconds() < 300:
            raise DomainError(
                "RESULT_IMPORT_STILL_PENDING",
                "Check this admitted import; recovery requires at least five minutes and owner acknowledgement",
                409,
                details={"committed": False},
            )
    package = packages.get_package(db, owner, project_id, row.package_id)
    if (
        package.status != "READY"
        or not packages._frozen_intact(db, package)
        or package.preview_sha256 != row.match_snapshot["package_preview_sha256"]
    ):
        raise DomainError(
            "RESULT_RETRY_SOURCE_CHANGED",
            "Frozen original package is unavailable or changed",
            409,
            details={"committed": False},
        )
    known = db.get(Attachment, row.input_attachment_id) if row.input_attachment_id else None
    known_fact = (
        {
            k: getattr(known, k)
            for k in (
                "id",
                "user_id",
                "storage_provider",
                "object_key",
                "sha256",
                "size_bytes",
                "mime_type",
                "deleted_at",
            )
        }
        if known
        else None
    )
    if content is None and known_fact is None:
        raise DomainError(
            "RESULT_RETRY_FILE_REQUIRED",
            "Re-select the original ZIP because no verified input is stored",
            409,
            details={"committed": False},
        )
    if content is not None and (not content or len(content) > upload_limit()):
        raise DomainError(
            "RESULT_SIZE_LIMIT",
            "Original ZIP exceeds configured recovery upload limit",
            413,
            details={"committed": False},
        )
    token = uuid.uuid4()
    package_sha = package.preview_sha256
    row.import_token = token
    row.status = "IMPORTING"
    row.error_code = None
    row.error_message = None
    row.storage_observations = [
        *row.storage_observations,
        {
            "token": str(token),
            "key": body.retry_idempotency_key,
            "request_sha256": body_sha,
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
            "status": "IMPORTING",
            "acknowledge_unknown": True,
            "facts": [],
        },
    ]
    expected_sha = row.result_sha256
    expected_receipt = row.receipt_sha256
    raw_envelope = row.raw_envelope
    db.commit()
    db.rollback()
    try:
        if content is None:
            assert known_fact is not None
            content = await _read_known(known_fact, owner)
        parsed, _ = _parse(content)
        if (
            parsed.input_sha256 != body.input_sha256
            or parsed.receipt_sha256 != expected_receipt
            or parsed.envelope != raw_envelope
        ):
            raise error(
                "RESULT_RETRY_INPUT_CHANGED", "Recovered receipt differs from frozen original"
            )
    except Exception:
        current = get_result(db, owner, project_id, identity, lock=True)
        audit = [dict(x) for x in current.storage_observations]
        recorded = next(x for x in audit if x.get("token") == str(token))
        recorded.update(
            {
                "finished_at": datetime.now(UTC).isoformat(),
                "status": "NEEDS_ATTENTION"
                if current.import_token == token and current.status == "IMPORTING"
                else "LATE",
                "error_code": "RESULT_RETRY_INPUT_UNAVAILABLE",
            }
        )
        current.storage_observations = audit
        if current.import_token == token and current.status == "IMPORTING":
            current.status = "NEEDS_ATTENTION"
            current.error_code = "RESULT_RETRY_INPUT_UNAVAILABLE"
            current.error_message = "Original input could not be verified; inspect storage or select the same original file."
        db.commit()
        return current
    current = get_result(db, owner, project_id, identity, lock=True)
    if (
        current.import_token != token
        or current.status != "IMPORTING"
        or current.result_sha256 != expected_sha
        or not _intact(db, current)
    ):
        fenced = current.import_token != token or current.status != "IMPORTING"
        audit = [dict(x) for x in current.storage_observations]
        recorded = next(x for x in audit if x.get("token") == str(token))
        recorded.update(
            {
                "finished_at": datetime.now(UTC).isoformat(),
                "status": "LATE" if fenced else "NEEDS_ATTENTION",
                "error_code": "RESULT_RETRY_SOURCE_CHANGED",
            }
        )
        current.storage_observations = audit
        if not fenced:
            current.status = "NEEDS_ATTENTION"
            current.error_code = "RESULT_RETRY_SOURCE_CHANGED"
            current.error_message = "Original result changed during recovery input validation; inspect without replaying."
        db.commit()
        return current
    return await _perform_save(db, owner, project_id, identity, token, parsed, content, package_sha)
