"""Owner-approved frozen document builds. No AI, model execution or scientific aggregation."""

import asyncio
import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.latex_compilation import (
    LatexCompilerCapabilities,
    LatexCompileRequest,
    LatexSourceFile,
    source_manifest_sha,
    validate_request,
)
from app.domain.manuscripts import (
    ManuscriptSourceFile,
    ManuscriptSourceProject,
    ManuscriptSourceRequest,
)
from app.models import Attachment
from app.models_manuscript_builds import (
    ManuscriptBuild,
    ManuscriptBuildAttempt,
    ManuscriptBuildFigure,
    ManuscriptBuildFile,
    ManuscriptBuildMetric,
    ManuscriptBuildOperation,
    ManuscriptBuildTable,
)
from app.models_server_results import ServerResultArtifact, ServerResultMetric
from app.providers import registry
from app.schemas_manuscript_builds import (
    BuildAttemptOut,
    BuildCancel,
    BuildCompilerOut,
    BuildCreate,
    BuildFileOut,
    BuildOptions,
    BuildOut,
    BuildPreview,
    BuildRetry,
    BuildSelection,
    BuildTemplateOut,
)
from app.services import publications, server_results
from app.services.claims import fail as fail
from app.services.research_briefs import digest


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def enabled() -> None:
    if not get_settings().manuscript_builds_enabled:
        raise fail("MANUSCRIPT_BUILDS_DISABLED", "Document builds are disabled on this host", 503)


def compiler_identity(cap: LatexCompilerCapabilities) -> str:
    return digest(
        {
            "image_id": cap.image_id,
            "engine": cap.engine,
            "isolation_contract": cap.isolation_contract,
            "packages": list(cap.packages),
            "chinese_font": cap.chinese_font,
        }
    )


async def capabilities() -> LatexCompilerCapabilities:
    from app.errors import DomainError

    try:
        return await asyncio.to_thread(registry.latex_compilation_provider().probe)
    except DomainError as error:
        return LatexCompilerCapabilities(False, error.message, None)


def compiler_out(cap: LatexCompilerCapabilities) -> BuildCompilerOut:
    return BuildCompilerOut(**{k: getattr(cap, k) for k in BuildCompilerOut.model_fields})


async def options() -> BuildOptions:
    cap = await capabilities()
    return BuildOptions(
        enabled=get_settings().manuscript_builds_enabled,
        templates=[
            BuildTemplateOut(**asdict(x))
            for x in registry.manuscript_template_provider().descriptors()
        ],
        compiler=compiler_out(cap),
    )


def freeze_inputs(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    publication: uuid.UUID,
    choice: BuildSelection,
) -> dict[str, Any]:
    parent = publications.get(db, owner, project, publication)
    revision = publications.revision(db, parent, choice.revision_id)
    detail = publications.revision_out(db, revision)
    if (
        detail.sha256 != choice.expected_revision_sha256
        or not detail.integrity_valid
        or not detail.context_current
    ):
        raise fail(
            "BUILD_REVISION_CHANGED", "Select the exact intact manuscript and evidence revision"
        )
    figures = []
    tables = []
    for selected in choice.figures:
        result = server_results.get_result(db, owner, project, selected.result_id)
        artifact = db.scalar(
            select(ServerResultArtifact).where(
                ServerResultArtifact.id == selected.artifact_id,
                ServerResultArtifact.result_id == result.id,
                ServerResultArtifact.user_id == owner,
            )
        )
        attachment = (
            db.scalar(
                select(Attachment)
                .where(Attachment.id == artifact.attachment_id, Attachment.user_id == owner)
                .execution_options(populate_existing=True)
            )
            if artifact
            else None
        )
        if (
            result.status != "READY"
            or not server_results._intact(db, result)
            or result.result_sha256 != selected.expected_result_sha256
            or artifact is None
            or artifact.sha256 != selected.expected_artifact_sha256
            or artifact.verification != "BYTES_VERIFIED"
            or artifact.actual_sha256 != artifact.sha256
            or attachment is None
            or attachment.deleted_at is not None
            or attachment.sha256 != artifact.sha256
            or attachment.size_bytes != artifact.size_bytes
            or attachment.size_bytes > 8 * 1024 * 1024
            or not selected.caption.strip()
        ):
            raise fail(
                "BUILD_FIGURE_SOURCE_INVALID",
                "Select an owned byte-verified bounded report artifact and exact hash",
                422,
            )
        figures.append(
            {
                "path": selected.path,
                "caption": selected.caption,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "result_id": str(result.id),
                "artifact_id": str(artifact.id),
                "attachment_id": str(attachment.id),
                "storage_provider": attachment.storage_provider,
                "object_key": attachment.object_key,
                "result_sha256": result.result_sha256,
                "git_commit": result.git_commit,
                "protocol_sha256": result.protocol_sha256,
                "dataset_sha256": result.dataset_sha256,
                "config_sha256": result.config_sha256,
                "origin_verification": result.origin_verification,
                "claimed_run_status": result.claimed_run_status,
            }
        )
        expected_mime = {"png": "image/png", "jpg": "image/jpeg", "pdf": "application/pdf"}[
            selected.path.rsplit(".", 1)[-1]
        ]
        if artifact.mime_type != expected_mime or attachment.mime_type != expected_mime:
            raise fail(
                "BUILD_FIGURE_MIME", "Figure filename and actual source MIME must agree", 422
            )
    for selected_table in choice.tables:
        metrics = []
        for item in selected_table.metrics:
            result = server_results.get_result(db, owner, project, item.result_id)
            metric = db.scalar(
                select(ServerResultMetric).where(
                    ServerResultMetric.id == item.metric_id,
                    ServerResultMetric.result_id == result.id,
                    ServerResultMetric.user_id == owner,
                )
            )
            if (
                result.status != "READY"
                or not server_results._intact(db, result)
                or result.result_sha256 != item.expected_result_sha256
                or metric is None
            ):
                raise fail(
                    "BUILD_METRIC_SOURCE_INVALID",
                    "Select actual metrics from an owned intact report",
                    422,
                )
            metrics.append(
                {
                    "result_id": str(result.id),
                    "metric_id": str(metric.id),
                    "result_sha256": result.result_sha256,
                    "name": metric.name,
                    "value": metric.value,
                    "unit": metric.unit,
                    "split": metric.split,
                    "evaluation_protocol": metric.evaluation_protocol,
                    "protocol_sha256": result.protocol_sha256,
                    "dataset_sha256": result.dataset_sha256,
                    "config_sha256": result.config_sha256,
                    "git_commit": result.git_commit,
                    "origin_verification": result.origin_verification,
                    "claimed_run_status": result.claimed_run_status,
                }
            )
        tables.append(
            {"key": selected_table.key, "title": selected_table.title, "metrics": metrics}
        )
    return {
        "revision": detail.model_dump(mode="json"),
        "evidence_snapshots": [x.snapshot for x in detail.source_details],
        "figures": figures,
        "tables": tables,
    }


async def read_object(provider_key: str, key: str, expected_sha: str, size: int) -> bytes:
    provider = registry.storage_provider(provider_key)
    reader = await provider.open(key)
    try:
        raw = bytearray()
        async for part in reader.iter_bytes():
            raw.extend(part)
            if len(raw) > size:
                raise fail("BUILD_BYTES_CHANGED", "Selected artifact exceeds frozen byte count")
    finally:
        await reader.close()
    if len(raw) != size or sha(bytes(raw)) != expected_sha:
        raise fail("BUILD_BYTES_CHANGED", "Actual object hash or size changed")
    return bytes(raw)


def file_out(file: ManuscriptSourceFile) -> BuildFileOut:
    binary = file.path.endswith((".png", ".jpg", ".jpeg", ".pdf"))
    try:
        text = None if binary else file.content.decode("utf-8")
    except UnicodeDecodeError:
        text = None
        binary = True
    return BuildFileOut(
        path=file.path,
        sha256=file.sha256,
        size_bytes=len(file.content),
        binary=binary,
        text_content=text,
    )


@dataclass(frozen=True)
class PreparedBuild:
    preview: BuildPreview
    source: ManuscriptSourceProject
    compile_files: tuple[ManuscriptSourceFile, ...]
    snapshot: dict[str, Any]


async def prepare(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    publication: uuid.UUID,
    choice: BuildSelection,
) -> PreparedBuild:
    enabled()
    frozen = freeze_inputs(db, owner, project, publication, choice)
    template = registry.manuscript_template_provider().load_resources(
        choice.template_key,
        choice.expected_template_manifest_sha256,
        private_use_approved=choice.private_template_use_approved,
    )
    if choice.variant not in {v.key for v in template.descriptor.variants}:
        raise fail("BUILD_VARIANT_INVALID", "Choose an actual available template variant", 422)
    db.rollback()
    figures = []
    for row in frozen["figures"]:
        raw = await read_object(
            row["storage_provider"], row["object_key"], row["sha256"], row["size_bytes"]
        )
        figures.append(ManuscriptSourceFile(row["path"], raw, row["sha256"]))
    cap = await capabilities()
    if digest(freeze_inputs(db, owner, project, publication, choice)) != digest(frozen):
        raise fail("BUILD_SOURCE_CHANGED", "Build sources changed during actual byte preview")
    request = ManuscriptSourceRequest(
        revision=frozen["revision"],
        evidence_snapshots=tuple(frozen["evidence_snapshots"]),
        figures=tuple(figures),
        figure_provenance=tuple(frozen["figures"]),
        table_provenance=tuple(frozen["tables"]),
        template=template,
        variant=choice.variant,
        font_profile=choice.font_profile,
        submission_id=choice.submission_id,
        tex_overrides=tuple(
            ManuscriptSourceFile(x.path, x.content.encode(), sha(x.content.encode()))
            for x in choice.tex_overrides
        ),
    )
    renderer = registry.manuscript_source_renderer()
    source = renderer.render(request)
    archive = renderer.pack(source)
    compile_files = renderer.compile_files(source)
    complete = tuple(LatexSourceFile(f.path, f.content, f.sha256) for f in source.files)
    compiled = tuple(LatexSourceFile(f.path, f.content, f.sha256) for f in compile_files)
    compile_sha = source_manifest_sha(compiled)
    validate_request(LatexCompileRequest(compiled, compile_sha))
    if len(source.files) > 200 or sum(len(f.content) for f in source.files) > 16 * 1024 * 1024:
        raise fail(
            "BUILD_SOURCE_BOUND",
            "Document source exceeds the 16MiB frozen byte bound",
            422,
        )
    gaps = list(source.warnings) + frozen["revision"]["gaps"]
    if not cap.available:
        gaps.append("COMPILER_UNAVAILABLE")
    for table in frozen["tables"]:
        protocols = {
            (x["name"], x["unit"], x["split"], x["protocol_sha256"], x["dataset_sha256"])
            for x in table["metrics"]
        }
        if len(protocols) > 1:
            gaps.append("TABLE_MIXED_DEFINITIONS_OR_PROTOCOLS: " + table["key"])
    payload = {
        "selection": choice.model_dump(mode="json"),
        "snapshot": frozen,
        "files": [
            {"path": x.path, "sha256": x.sha256, "size_bytes": len(x.content)}
            for x in sorted(source.files, key=lambda f: f.path)
        ],
        "source_sha256": source_manifest_sha(complete),
        "compile_source_sha256": compile_sha,
        "compiler_manifest_sha256": compiler_identity(cap),
        "input_source_zip_sha256": sha(archive),
        "template": asdict(template.descriptor),
        "gaps": sorted(set(gaps)),
    }
    preview = BuildPreview(
        selection=choice,
        preview_sha256=digest(payload),
        source_sha256=payload["source_sha256"],
        compile_source_sha256=compile_sha,
        compiler_manifest_sha256=payload["compiler_manifest_sha256"],
        input_source_zip_sha256=sha(archive),
        compiler=compiler_out(cap),
        template=BuildTemplateOut(**asdict(template.descriptor)),
        files=[file_out(f) for f in source.files],
        gaps=sorted(set(gaps)),
        source_artifact_bytes_included=bool(figures),
    )
    return PreparedBuild(preview, source, compile_files, frozen)


def get(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    publication: uuid.UUID,
    identity: uuid.UUID,
    *,
    lock: bool = False,
) -> ManuscriptBuild:
    publications.get(db, owner, project, publication)
    query = (
        select(ManuscriptBuild)
        .where(
            ManuscriptBuild.id == identity,
            ManuscriptBuild.user_id == owner,
            ManuscriptBuild.project_id == project,
            ManuscriptBuild.publication_id == publication,
        )
        .execution_options(populate_existing=True)
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise fail("NOT_FOUND", "Owned document build not found", 404)
    return row


def file_records(db: Session, row: ManuscriptBuild) -> list[ManuscriptBuildFile]:
    records = list(
        db.scalars(
            select(ManuscriptBuildFile)
            .where(
                ManuscriptBuildFile.build_id == row.id, ManuscriptBuildFile.user_id == row.user_id
            )
            .order_by(ManuscriptBuildFile.path)
        )
    )
    inventory = [{"path": f.path, "sha256": f.sha256, "size_bytes": f.size_bytes} for f in records]
    if digest({"entrypoint": "main.tex", "files": inventory}) != row.source_sha256 or any(
        f.content_text is not None
        and (
            sha(f.content_text.encode()) != f.sha256 or len(f.content_text.encode()) != f.size_bytes
        )
        for f in records
    ):
        raise fail("BUILD_FROZEN_FILES_CHANGED", "Frozen text/inventory hash changed")
    payload = {
        "selection": row.selection,
        "snapshot": row.snapshot,
        "files": inventory,
        "source_sha256": row.source_sha256,
        "compile_source_sha256": row.compile_source_sha256,
        "compiler_manifest_sha256": row.compiler_manifest_sha256,
        "input_source_zip_sha256": row.input_source_zip_sha256,
        "template": row.preview_payload["template"],
        "gaps": row.preview_payload["gaps"],
    }
    if digest(payload) != row.preview_sha256:
        raise fail("BUILD_MANIFEST_CHANGED", "Frozen source/selection/provenance manifest changed")
    return records


async def stored_files(db: Session, row: ManuscriptBuild) -> tuple[ManuscriptSourceFile, ...]:
    records = file_records(db, row)
    inventory = [(r.path, r.sha256, r.size_bytes) for r in records]
    attachment = db.scalar(
        select(Attachment)
        .where(Attachment.id == row.input_source_attachment_id, Attachment.user_id == row.user_id)
        .execution_options(populate_existing=True)
    )
    if (
        attachment is None
        or attachment.deleted_at is not None
        or attachment.sha256 != row.input_source_zip_sha256
        or attachment.size_bytes > 32 * 1024 * 1024
    ):
        raise fail("BUILD_INPUT_UNAVAILABLE", "Actual immutable source ZIP is unavailable")
    key, provider, hash_value, size = (
        attachment.object_key,
        attachment.storage_provider,
        attachment.sha256,
        attachment.size_bytes,
    )
    db.rollback()
    raw = await read_object(provider, key, hash_value, size)
    files = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) != len(inventory) or {
            x.filename for x in archive.infolist()
        } != {x[0] for x in inventory}:
            raise fail("BUILD_ZIP_INVENTORY", "Source ZIP inventory changed")
        for path, expected, expected_size in inventory:
            info = archive.getinfo(path)
            if info.file_size != expected_size or info.file_size > 8 * 1024 * 1024:
                raise fail("BUILD_ZIP_BOUND", "Source ZIP member byte bound changed")
            content = archive.read(info)
            if sha(content) != expected:
                raise fail("BUILD_BYTES_CHANGED", "Source ZIP member hash changed")
            files.append(ManuscriptSourceFile(path, content, expected))
    return tuple(files)


async def compile_request(db: Session, row: ManuscriptBuild) -> LatexCompileRequest:
    selected = set(
        db.scalars(
            select(ManuscriptBuildFile.path).where(
                ManuscriptBuildFile.build_id == row.id,
                ManuscriptBuildFile.user_id == row.user_id,
                ManuscriptBuildFile.compile_input.is_(True),
            )
        )
    )
    expected = row.compile_source_sha256
    files = await stored_files(db, row)
    request = LatexCompileRequest(
        tuple(LatexSourceFile(f.path, f.content, f.sha256) for f in files if f.path in selected),
        expected,
    )
    validate_request(request)
    return request


def detail(db: Session, row: ManuscriptBuild) -> BuildOut:
    current = True
    gaps = list(row.preview_payload["gaps"])
    try:
        records = file_records(db, row)
        if digest(
            freeze_inputs(
                db,
                row.user_id,
                row.project_id,
                row.publication_id,
                BuildSelection.model_validate(row.selection),
            )
        ) != digest(row.snapshot):
            current = False
            gaps.append("BUILD_CURRENT_SOURCE_CHANGED")
    except Exception as error:
        from app.errors import DomainError

        if not isinstance(error, (DomainError, ValueError, KeyError)):
            raise
        records = []
        current = False
        gaps.append("BUILD_SOURCE_UNAVAILABLE")
    attempts = list(
        db.scalars(
            select(ManuscriptBuildAttempt)
            .where(
                ManuscriptBuildAttempt.build_id == row.id,
                ManuscriptBuildAttempt.user_id == row.user_id,
            )
            .order_by(ManuscriptBuildAttempt.started_at, ManuscriptBuildAttempt.id)
        )
    )
    return BuildOut(
        **{
            k: getattr(row, k)
            for k in (
                "id",
                "project_id",
                "publication_id",
                "revision_id",
                "status",
                "preview_sha256",
                "source_sha256",
                "compile_source_sha256",
                "compiler_manifest_sha256",
                "input_source_zip_sha256",
                "created_at",
                "input_source_attachment_id",
                "source_attachment_id",
                "source_zip_sha256",
                "source_zip_size_bytes",
                "pdf_attachment_id",
                "log_attachment_id",
            )
        },
        selection=BuildSelection.model_validate(row.selection),
        files=[
            BuildFileOut(
                path=f.path,
                sha256=f.sha256,
                size_bytes=f.size_bytes,
                text_content=f.content_text,
                binary=f.content_text is None,
            )
            for f in records
        ],
        gaps=sorted(set(gaps)),
        context_current=current,
        attempts=[BuildAttemptOut.model_validate(a) for a in attempts],
    )


async def create(
    db: Session, owner: uuid.UUID, project: uuid.UUID, publication: uuid.UUID, body: BuildCreate
) -> ManuscriptBuild:
    request_sha = digest(body.model_dump(mode="json"))
    publications.get(db, owner, project, publication)
    old = db.scalar(
        select(ManuscriptBuild).where(
            ManuscriptBuild.user_id == owner,
            ManuscriptBuild.publication_id == publication,
            ManuscriptBuild.create_key == body.idempotency_key,
        )
    )
    if old:
        if old.request_sha256 != request_sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Same build key has different frozen inputs")
        return old
    prepared = await prepare(db, owner, project, publication, body.selection)
    preview = prepared.preview
    if preview.preview_sha256 != body.expected_preview_sha256:
        raise fail("BUILD_PREVIEW_CHANGED", "Actual source/template/compiler preview changed")
    if preview.gaps and not body.acknowledge_gaps:
        raise fail("BUILD_GAPS_REQUIRE_ACK", "Acknowledge document/source gaps before queuing")
    publications.get(db, owner, project, publication, lock=True)
    if digest(freeze_inputs(db, owner, project, publication, body.selection)) != digest(
        prepared.snapshot
    ):
        raise fail("BUILD_SOURCE_CHANGED", "Source changed before queue admission")
    old = db.scalar(
        select(ManuscriptBuild).where(
            ManuscriptBuild.user_id == owner,
            ManuscriptBuild.publication_id == publication,
            ManuscriptBuild.create_key == body.idempotency_key,
        )
    )
    if old:
        if old.request_sha256 != request_sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Same build key has different frozen inputs")
        return old
    row = ManuscriptBuild(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project,
        publication_id=publication,
        revision_id=body.selection.revision_id,
        create_key=body.idempotency_key,
        request_sha256=request_sha,
        preview_sha256=preview.preview_sha256,
        source_sha256=preview.source_sha256,
        compile_source_sha256=preview.compile_source_sha256,
        compiler_manifest_sha256=preview.compiler_manifest_sha256,
        input_source_zip_sha256=preview.input_source_zip_sha256,
        selection=body.selection.model_dump(mode="json"),
        snapshot=prepared.snapshot,
        preview_payload=preview.model_dump(mode="json"),
        status="SAVING",
    )
    try:
        db.add(row)
        db.flush()
        scope = {
            "build_id": row.id,
            "user_id": owner,
            "project_id": project,
            "publication_id": publication,
        }
        compile_paths = {f.path for f in prepared.compile_files}
        for f in prepared.source.files:
            db.add(
                ManuscriptBuildFile(
                    **scope,
                    path=f.path,
                    sha256=f.sha256,
                    size_bytes=len(f.content),
                    content_text=file_out(f).text_content,
                    compile_input=f.path in compile_paths,
                )
            )
        for f in prepared.snapshot["figures"]:
            db.add(
                ManuscriptBuildFigure(
                    **scope,
                    result_id=uuid.UUID(f["result_id"]),
                    artifact_id=uuid.UUID(f["artifact_id"]),
                    attachment_id=uuid.UUID(f["attachment_id"]),
                    result_sha256=f["result_sha256"],
                    sha256=f["sha256"],
                    path=f["path"],
                    caption=f["caption"],
                    facts=f,
                )
            )
        for pos, t in enumerate(prepared.snapshot["tables"]):
            table = ManuscriptBuildTable(
                id=uuid.uuid4(), **scope, key=t["key"], title=t["title"], position=pos
            )
            db.add(table)
            db.flush()
            for ix, m in enumerate(t["metrics"]):
                db.add(
                    ManuscriptBuildMetric(
                        **scope,
                        table_id=table.id,
                        result_id=uuid.UUID(m["result_id"]),
                        metric_id=uuid.UUID(m["metric_id"]),
                        result_sha256=m["result_sha256"],
                        position=ix,
                        name=m["name"],
                        value=m["value"],
                        unit=m["unit"],
                        split=m["split"],
                        evaluation_protocol=m["evaluation_protocol"],
                        facts=m,
                    )
                )
        token = uuid.uuid4()
        row.lease_token = token
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.add(
            ManuscriptBuildAttempt(
                id=token, **scope, kind="SOURCE_SAVE", status="SAVING", observations=[]
            )
        )
        db.commit()
        return await save_input(db, row, prepared.source, token)
    except Exception:
        db.rollback()
        raise


def lookup(
    db: Session, owner: uuid.UUID, project: uuid.UUID, publication: uuid.UUID, key: str
) -> ManuscriptBuild:
    publications.get(db, owner, project, publication)
    row = db.scalar(
        select(ManuscriptBuild).where(
            ManuscriptBuild.user_id == owner,
            ManuscriptBuild.publication_id == publication,
            ManuscriptBuild.create_key == key,
        )
    )
    if row is None:
        raise fail("NOT_FOUND", "Owned build capture not found", 404)
    return row


async def operate(
    db: Session, row: ManuscriptBuild, kind: str, body: BuildCancel | BuildRetry
) -> ManuscriptBuild:
    row = get(db, row.user_id, row.project_id, row.publication_id, row.id, lock=True)
    digest_value = digest(body.model_dump(mode="json"))
    old = db.scalar(
        select(ManuscriptBuildOperation).where(
            ManuscriptBuildOperation.build_id == row.id,
            ManuscriptBuildOperation.kind == kind,
            ManuscriptBuildOperation.idempotency_key == body.idempotency_key,
        )
    )
    if old:
        if old.request_sha256 != digest_value:
            raise fail("IDEMPOTENCY_CONFLICT", "Same build operation key has different input")
        return row
    if kind == "cancel":
        if row.status == "QUEUED":
            row.status = "CANCELLED"
        elif row.status in {"RUNNING", "SAVING"}:
            row.status = "CANCEL_REQUESTED"
    else:
        assert isinstance(body, BuildRetry)
        if row.source_sha256 != body.expected_source_sha256:
            raise fail("BUILD_SOURCE_CHANGED", "Retry must use original frozen source")
        if (
            row.status == "SAVING"
            and row.lease_expires_at
            and (
                row.lease_expires_at.replace(tzinfo=UTC)
                if row.lease_expires_at.tzinfo is None
                else row.lease_expires_at
            )
            > datetime.now(UTC)
        ):
            raise fail(
                "BUILD_SOURCE_SAVE_ACTIVE",
                "Actual source save has an active lease; do not duplicate it",
            )
        if row.status not in {"FAILED", "NEEDS_ATTENTION", "CANCELLED", "SAVING"}:
            raise fail("BUILD_RETRY_NOT_ALLOWED", "Build is active or already ready")
        if (
            len(
                list(
                    db.scalars(
                        select(ManuscriptBuildAttempt.id).where(
                            ManuscriptBuildAttempt.build_id == row.id
                        )
                    )
                )
            )
            >= 50
        ):
            raise fail("BUILD_ATTEMPT_LIMIT", "Build has reached its bounded retry history")
        file_records(db, row)
        row.status = "QUEUED" if row.input_source_attachment_id else "SAVING"
        row.lease_token = None
        row.lease_expires_at = None
    db.add(
        ManuscriptBuildOperation(
            build_id=row.id,
            user_id=row.user_id,
            project_id=row.project_id,
            publication_id=row.publication_id,
            kind=kind,
            idempotency_key=body.idempotency_key,
            request_sha256=digest_value,
        )
    )
    token = None
    if kind == "retry" and row.input_source_attachment_id is None:
        token = uuid.uuid4()
        row.lease_token = token
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.add(
            ManuscriptBuildAttempt(
                id=token,
                build_id=row.id,
                user_id=row.user_id,
                project_id=row.project_id,
                publication_id=row.publication_id,
                kind="SOURCE_SAVE",
                status="SAVING",
                observations=[],
            )
        )
    db.commit()
    if token is not None:
        try:
            source = await reconstruct_input(db, row)
        except Exception:
            current = get(db, row.user_id, row.project_id, row.publication_id, row.id, lock=True)
            if current.lease_token == token:
                current.status = "NEEDS_ATTENTION"
                current.lease_token = None
                current.lease_expires_at = None
            attempt = db.get(ManuscriptBuildAttempt, token)
            assert attempt is not None
            attempt.status = "NEEDS_ATTENTION"
            attempt.error_code = "BUILD_SOURCE_RECONSTRUCTION_FAILED"
            attempt.ended_at = datetime.now(UTC)
            db.commit()
            raise
        return await save_input(db, row, source, token)
    return row


async def reconstruct_input(db: Session, row: ManuscriptBuild) -> ManuscriptSourceProject:
    records = file_records(db, row)
    originals = [(x.path, x.content_text, x.sha256, x.size_bytes) for x in records]
    figures = {f["path"]: f for f in row.snapshot["figures"]}
    owner = row.user_id
    template = registry.manuscript_template_provider().load_resources(
        row.selection["template_key"],
        row.selection["expected_template_manifest_sha256"],
        private_use_approved=row.selection.get("private_template_use_approved", False),
    )
    resources = {f.path: f for f in template.files}
    template_key = row.selection["template_key"]
    db.rollback()
    files = []
    for path, text, expected, size in originals:
        if text is not None:
            content = text.encode()
        elif path in figures:
            facts = figures[path]
            attachment = db.scalar(
                select(Attachment).where(
                    Attachment.id == uuid.UUID(facts["attachment_id"]), Attachment.user_id == owner
                )
            )
            if (
                attachment is None
                or attachment.deleted_at is not None
                or attachment.sha256 != expected
                or attachment.size_bytes != size
            ):
                raise fail(
                    "BUILD_SOURCE_RECONSTRUCTION_FAILED",
                    "Original selected figure is unavailable; no dummy frozen bytes",
                )
            provider, key = attachment.storage_provider, attachment.object_key
            db.rollback()
            content = await read_object(provider, key, expected, size)
        elif path in resources:
            content = resources[path].content
        else:
            raise fail(
                "BUILD_SOURCE_RECONSTRUCTION_FAILED",
                "Opaque source cannot be recovered from its original attachment",
            )
        if sha(content) != expected or len(content) != size:
            raise fail("BUILD_SOURCE_RECONSTRUCTION_FAILED", "Original frozen source hash changed")
        files.append(ManuscriptSourceFile(path, content, expected))
    render_sha = json.loads(
        next(f.content for f in files if f.path == "build/source-manifest.json")
    )["source_sha256"]
    return ManuscriptSourceProject(tuple(files), render_sha, (), template=template_key)


async def save_input(
    db: Session, row: ManuscriptBuild, source: ManuscriptSourceProject, token: uuid.UUID
) -> ManuscriptBuild:
    identity, owner, project, publication = row.id, row.user_id, row.project_id, row.publication_id
    expected = row.input_source_zip_sha256
    archive = registry.manuscript_source_renderer().pack(source)
    if sha(archive) != expected:
        raise fail("BUILD_SOURCE_PACK_CHANGED", "Rebuilt source ZIP differs from original approval")
    previous = db.scalar(
        select(ManuscriptBuildAttempt)
        .where(
            ManuscriptBuildAttempt.build_id == identity,
            ManuscriptBuildAttempt.user_id == owner,
            ManuscriptBuildAttempt.kind == "SOURCE_SAVE",
            ManuscriptBuildAttempt.id != token,
            ManuscriptBuildAttempt.source_attachment_id.is_not(None),
            ManuscriptBuildAttempt.source_zip_sha256 == expected,
            ManuscriptBuildAttempt.source_zip_size_bytes == len(archive),
        )
        .order_by(ManuscriptBuildAttempt.started_at.desc())
        .limit(1)
    )
    prior_attachment_id = previous.source_attachment_id if previous else None
    db.rollback()
    try:
        provider = registry.storage_provider()

        async def content() -> AsyncIterator[bytes]:
            yield archive

        attachment = (
            db.scalar(
                select(Attachment).where(
                    Attachment.id == prior_attachment_id,
                    Attachment.user_id == owner,
                    Attachment.deleted_at.is_(None),
                    Attachment.sha256 == expected,
                    Attachment.size_bytes == len(archive),
                )
            )
            if prior_attachment_id
            else None
        )
        if attachment is None:
            db.rollback()
            stored = await provider.save(
                content(), mime_type="application/zip", max_bytes=32 * 1024 * 1024
            )
            attempt = db.get(ManuscriptBuildAttempt, token)
            assert attempt is not None
            attempt.observations = [
                *attempt.observations,
                {
                    "kind": "source",
                    "storage_provider": provider.provider_key,
                    "object_key": stored.key,
                    "sha256": stored.sha256,
                    "size_bytes": stored.size_bytes,
                    "expected_sha256": expected,
                    "expected_size_bytes": len(archive),
                    "receipt_observed": True,
                    "readback_verified": False,
                },
            ]
            db.commit()
            if stored.sha256 != expected or stored.size_bytes != len(archive):
                raise ValueError("Actual source save receipt changed")
            attachment = Attachment(
                id=uuid.uuid4(),
                user_id=owner,
                storage_provider=provider.provider_key,
                object_key=stored.key,
                original_filename=f"manuscript-input-{identity}.zip",
                mime_type="application/zip",
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
            )
            db.add(attachment)
            db.flush()
        attachment_id = attachment.id
        storage_provider, object_key = attachment.storage_provider, attachment.object_key
        attempt = db.get(ManuscriptBuildAttempt, token)
        assert attempt is not None
        attempt.source_attachment_id = attachment_id
        attempt.source_zip_sha256 = expected
        attempt.source_zip_size_bytes = len(archive)
        db.commit()
        await read_object(storage_provider, object_key, expected, len(archive))
        row = get(db, owner, project, publication, identity, lock=True)
        attempt = db.get(ManuscriptBuildAttempt, token)
        assert attempt is not None
        attempt.observations = [
            *attempt.observations,
            {
                "kind": "source",
                "object_key": object_key,
                "readback_verified": True,
                "reused_known_receipt": prior_attachment_id is not None,
            },
        ]
        attempt.source_attachment_id = attachment.id
        attempt.ended_at = datetime.now(UTC)
        if row.lease_token != token or row.status not in {"SAVING", "CANCEL_REQUESTED"}:
            attempt.status = "LATE"
        else:
            attempt.status = "READY"
            row.status = "CANCELLED" if row.status == "CANCEL_REQUESTED" else "QUEUED"
            row.input_source_attachment_id = attachment_id
            row.source_attachment_id = attachment_id
            row.lease_token = None
            row.lease_expires_at = None
        db.commit()
        return row
    except Exception as error:
        db.rollback()
        row = get(db, owner, project, publication, identity, lock=True)
        attempt = db.get(ManuscriptBuildAttempt, token)
        assert attempt is not None
        attempt.error_code = "BUILD_SOURCE_SAVE_UNKNOWN"
        attempt.observations = [*attempt.observations, {"error_type": type(error).__name__}]
        attempt.ended_at = datetime.now(UTC)
        if row.lease_token == token and row.status in {"SAVING", "CANCEL_REQUESTED"}:
            row.status = "CANCELLED" if row.status == "CANCEL_REQUESTED" else "NEEDS_ATTENTION"
            attempt.status = row.status
            row.lease_token = None
            row.lease_expires_at = None
        else:
            attempt.status = "LATE"
        db.commit()
        return row
