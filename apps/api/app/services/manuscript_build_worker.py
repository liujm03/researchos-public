"""Document-only worker. Compiler threads hold bytes, never a DB session or research grant."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import SessionLocal
from app.domain.latex_compilation import LatexCompileResult
from app.domain.manuscripts import ManuscriptSourceFile, ManuscriptSourceProject
from app.models import Attachment, User
from app.models_manuscript_builds import ManuscriptBuild, ManuscriptBuildAttempt
from app.providers import registry
from app.schemas_manuscript_builds import BuildPreview
from app.services import manuscript_builds as service


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def recover(db: Session) -> int:
    now = datetime.now(UTC)
    rows = list(
        db.scalars(
            select(ManuscriptBuild)
            .where(
                ManuscriptBuild.status.in_(["RUNNING", "CANCEL_REQUESTED"]),
                ManuscriptBuild.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        row.status = "NEEDS_ATTENTION"
        attempt = db.get(ManuscriptBuildAttempt, row.lease_token)
        if attempt:
            attempt.status = "NEEDS_ATTENTION"
            attempt.error_code = "BUILD_OUTCOME_UNKNOWN"
            attempt.ended_at = now
    if rows:
        db.commit()
    return len(rows)


async def heartbeat(identity: uuid.UUID, token: uuid.UUID) -> None:
    while True:
        await asyncio.sleep(15)
        with SessionLocal() as db:
            db.execute(
                update(ManuscriptBuild)
                .where(
                    ManuscriptBuild.id == identity,
                    ManuscriptBuild.lease_token == token,
                    ManuscriptBuild.status.in_(["RUNNING", "CANCEL_REQUESTED"]),
                )
                .values(lease_expires_at=datetime.now(UTC) + timedelta(minutes=10))
            )
            db.commit()


async def save_bytes(
    db: Session,
    owner: uuid.UUID,
    raw: bytes,
    name: str,
    mime: str,
    max_bytes: int,
    token: uuid.UUID,
    kind: str,
) -> Attachment:
    db.rollback()
    provider = registry.storage_provider()

    async def content() -> AsyncIterator[bytes]:
        yield raw

    stored = await provider.save(
        content(), mime_type=mime, max_bytes=max_bytes, allow_empty=not raw
    )
    attempt = db.get(ManuscriptBuildAttempt, token)
    assert attempt is not None and attempt.user_id == owner
    attempt.observations = [
        *attempt.observations,
        {
            "kind": kind,
            "storage_provider": provider.provider_key,
            "object_key": stored.key,
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "expected_sha256": service.sha(raw),
            "expected_size_bytes": len(raw),
            "receipt_observed": True,
            "readback_verified": False,
        },
    ]
    db.commit()
    if stored.sha256 != service.sha(raw) or stored.size_bytes != len(raw):
        raise ValueError("Storage receipt differs from actual compiler bytes")
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.object_key == stored.key,
            Attachment.user_id == owner,
            Attachment.storage_provider == provider.provider_key,
        )
    )
    if attachment is not None:
        if (
            attachment.deleted_at is not None
            or attachment.sha256 != stored.sha256
            or attachment.size_bytes != stored.size_bytes
            or attachment.mime_type != mime
        ):
            raise ValueError("Existing owned storage object differs from the known receipt")
    else:
        attachment = Attachment(
            id=uuid.uuid4(),
            user_id=owner,
            storage_provider=provider.provider_key,
            object_key=stored.key,
            original_filename=name,
            mime_type=mime,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )
        db.add(attachment)
        db.flush()
    setattr(attempt, kind + "_attachment_id", attachment.id)
    if kind == "source":
        attempt.source_zip_sha256 = service.sha(raw)
        attempt.source_zip_size_bytes = len(raw)
    db.commit()
    await service.read_object(provider.provider_key, stored.key, stored.sha256, stored.size_bytes)
    attempt = db.get(ManuscriptBuildAttempt, token)
    assert attempt is not None
    attempt.observations = [
        *attempt.observations,
        {
            "kind": kind,
            "object_key": stored.key,
            "readback_verified": True,
            "sha256": service.sha(raw),
            "size_bytes": len(raw),
        },
    ]
    db.commit()
    return attachment


def validate_result(result: LatexCompileResult, row: ManuscriptBuild) -> None:
    expected = BuildPreview.model_validate(row.preview_payload).compiler
    if (
        result.source_sha256 != row.compile_source_sha256
        or result.image_id != expected.image_id
        or result.engine != expected.engine
        or result.isolation_contract != expected.isolation_contract
        or service.sha(result.log) != result.log_sha256
        or len(result.log) > 2 * 1024 * 1024
    ):
        raise ValueError("Compiler output does not match the frozen source/image/log contract")
    if result.status == "READY" and (
        result.exit_code != 0
        or result.pdf is None
        or not result.pdf.startswith(b"%PDF-")
        or not 1 <= len(result.pdf) <= 16 * 1024 * 1024
        or service.sha(result.pdf) != result.pdf_sha256
    ):
        raise ValueError("Actual compiled PDF receipt is invalid")
    if result.pdf is not None and (
        service.sha(result.pdf) != result.pdf_sha256 or len(result.pdf) > 16 * 1024 * 1024
    ):
        raise ValueError("PDF bytes/hash mismatch")


def encode_result(result: LatexCompileResult) -> dict[str, Any]:
    values = asdict(result)
    values.pop("pdf")
    values.pop("log")
    values["pdf_size_bytes"] = len(result.pdf) if result.pdf is not None else None
    values["log_size_bytes"] = len(result.log)
    values["observations"] = list(result.observations)
    return values


async def decode_result(db: Session, attempt: ManuscriptBuildAttempt) -> LatexCompileResult:
    assert attempt.result_payload is not None
    value = dict(attempt.result_payload)
    material = []
    for name, identity, hash_key, size_key in (
        ("pdf", attempt.pdf_attachment_id, "pdf_sha256", "pdf_size_bytes"),
        ("log", attempt.log_attachment_id, "log_sha256", "log_size_bytes"),
    ):
        if name == "pdf" and value[hash_key] is None:
            value[name] = None
            continue
        attachment = db.scalar(
            select(Attachment).where(
                Attachment.id == identity, Attachment.user_id == attempt.user_id
            )
        )
        if (
            attachment is None
            or attachment.deleted_at is not None
            or attachment.sha256 != value[hash_key]
            or attachment.size_bytes != value[size_key]
        ):
            raise ValueError(
                "Actual prior compile bytes unavailable; cannot reuse a metadata-only result"
            )
        material.append(
            (
                name,
                attachment.storage_provider,
                attachment.object_key,
                attachment.sha256,
                attachment.size_bytes,
            )
        )
    value.pop("pdf_size_bytes")
    value.pop("log_size_bytes")
    db.rollback()
    for name, provider, key, hash_value, size in material:
        value[name] = await service.read_object(provider, key, hash_value, size)
    value["observations"] = tuple(value["observations"])
    return LatexCompileResult(**value)


async def process_next(db: Session, *, compiler: Any = None) -> ManuscriptBuild | None:
    recover(db)
    row = db.scalar(
        select(ManuscriptBuild)
        .where(
            ManuscriptBuild.status == "QUEUED",
            ManuscriptBuild.input_source_attachment_id.is_not(None),
        )
        .order_by(ManuscriptBuild.created_at, ManuscriptBuild.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        db.rollback()
        return None
    identity, owner = row.id, row.user_id
    token = uuid.uuid4()
    row.status = "RUNNING"
    row.lease_token = token
    row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=10)
    attempt: ManuscriptBuildAttempt | None = ManuscriptBuildAttempt(
        id=token,
        build_id=row.id,
        publication_id=row.publication_id,
        project_id=row.project_id,
        user_id=owner,
        kind="COMPILE",
        status="RUNNING",
        observations=[],
    )
    db.add(attempt)
    expected_compiler_sha = row.compiler_manifest_sha256
    previous = db.scalar(
        select(ManuscriptBuildAttempt)
        .where(
            ManuscriptBuildAttempt.build_id == identity,
            ManuscriptBuildAttempt.id != token,
            ManuscriptBuildAttempt.result_payload.is_not(None),
        )
        .order_by(ManuscriptBuildAttempt.started_at.desc())
        .limit(1)
    )
    previous_id = (
        previous.id
        if previous
        and previous.result_payload
        and previous.result_payload.get("status") == "READY"
        and previous.pdf_attachment_id
        and previous.log_attachment_id
        else None
    )
    db.commit()
    pulse = asyncio.create_task(heartbeat(identity, token))
    try:
        active = compiler if compiler is not None else registry.latex_compilation_provider()
        cap = await asyncio.to_thread(active.probe)
        if service.compiler_identity(cap) != expected_compiler_sha:
            raise ValueError("Configured compiler identity changed after approval")
        request = await service.compile_request(db, row)
        files = await service.stored_files(db, row)
        db.rollback()
        previous = db.get(ManuscriptBuildAttempt, previous_id) if previous_id else None
        reused_result = await decode_result(db, previous) if previous else None
        fresh = db.scalar(
            select(ManuscriptBuild)
            .where(ManuscriptBuild.id == identity, ManuscriptBuild.user_id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = db.get(ManuscriptBuildAttempt, token)
        assert fresh is not None and attempt is not None
        owner_active = db.scalar(select(User.is_active).where(User.id == owner)) is True
        if (
            not owner_active
            or not get_settings().manuscript_builds_enabled
            or fresh.lease_token != token
            or fresh.status not in {"RUNNING", "CANCEL_REQUESTED"}
            or fresh.lease_expires_at is None
            or utc(fresh.lease_expires_at) <= datetime.now(UTC)
        ):
            attempt.status = "LATE"
            attempt.ended_at = datetime.now(UTC)
            attempt.observations = [
                {
                    "compiler_started": False,
                    "reason": "LEASE_OR_OWNER_PERMISSION_CHANGED_BEFORE_COMPILE",
                }
            ]
            if fresh.lease_token == token:
                fresh.status = "NEEDS_ATTENTION"
                fresh.lease_token = None
                fresh.lease_expires_at = None
            db.commit()
            return fresh
        if fresh.status == "CANCEL_REQUESTED":
            attempt.status = "CANCELLED"
            attempt.ended_at = datetime.now(UTC)
            attempt.observations = [
                {"compiler_started": False, "reason": "OWNER_CANCELLED_BEFORE_COMPILE"}
            ]
            fresh.status = "CANCELLED"
            fresh.lease_token = None
            fresh.lease_expires_at = None
            db.commit()
            return fresh
        db.commit()
        result = (
            reused_result
            if reused_result is not None
            else await asyncio.to_thread(active.compile, request)
        )
        row = db.scalar(
            select(ManuscriptBuild)
            .where(ManuscriptBuild.id == identity, ManuscriptBuild.user_id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = db.get(ManuscriptBuildAttempt, token)
        assert row is not None and attempt is not None
        validate_result(result, row)
        attempt.result_payload = encode_result(result)
        attempt.image_id = result.image_id
        attempt.exit_code = result.exit_code
        attempt.observations = list(result.observations)
        late = row.lease_token != token or row.status not in {"RUNNING", "CANCEL_REQUESTED"}
        if late:
            attempt.status = "LATE"
            attempt.ended_at = datetime.now(UTC)
            db.commit()
            return row
        db.commit()
        # Frozen files and raw completed receipt are durable before object storage IO.
        rendered_source_sha = json.loads(
            next(f.content for f in files if f.path == "build/source-manifest.json")
        )["source_sha256"]
        receipt = json.dumps(
            {
                "contract": "researchos-document-build-v1",
                "source_sha256": rendered_source_sha,
                "frozen_source_sha256": row.source_sha256,
                "compile_source_sha256": row.compile_source_sha256,
                "compiler_manifest_sha256": row.compiler_manifest_sha256,
                "template": row.selection["template_key"],
                "variant": row.selection["variant"],
                "status": result.status,
                "image_id": result.image_id,
                "engine": result.engine,
                "isolation_contract": result.isolation_contract,
                "exit_code": result.exit_code,
                "pdf_sha256": result.pdf_sha256,
                "log_sha256": result.log_sha256,
                "observations": result.observations,
                "scientific_verification": "NOT_AUTOMATICALLY_VERIFIED",
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        manifest = ManuscriptSourceFile("build/build-manifest.json", receipt, service.sha(receipt))
        log = ManuscriptSourceFile("build/build.log", result.log, service.sha(result.log))
        source = ManuscriptSourceProject(
            tuple(f for f in files if f.path not in {manifest.path, log.path}) + (manifest, log),
            rendered_source_sha,
            (),
            row.selection["template_key"],
        )
        db.rollback()
        pdf_attachment = (
            await save_bytes(
                db,
                owner,
                result.pdf,
                f"manuscript-{identity}.pdf",
                "application/pdf",
                16 * 1024 * 1024,
                token,
                "pdf",
            )
            if result.status == "READY" and result.pdf is not None
            else None
        )
        pdf_attachment_id = pdf_attachment.id if pdf_attachment else None
        stored_attempt = db.get(ManuscriptBuildAttempt, token)
        assert stored_attempt is not None
        stored_attempt.pdf_attachment_id = pdf_attachment_id
        db.commit()
        log_attachment = await save_bytes(
            db,
            owner,
            result.log,
            f"manuscript-{identity}.log",
            "text/plain",
            2 * 1024 * 1024,
            token,
            "log",
        )
        log_attachment_id = log_attachment.id
        stored_attempt = db.get(ManuscriptBuildAttempt, token)
        assert stored_attempt is not None
        stored_attempt.log_attachment_id = log_attachment_id
        db.commit()
        summary = (
            "# ResearchOS actual document build\n\n"
            + f"Technical status: {result.status}.\nSource SHA-256: {row.source_sha256}\nCompile-source SHA-256: {row.compile_source_sha256}\nCompiler image: {result.image_id}\n\n"
            + f"Renderer source identity: {rendered_source_sha}\n\n"
            + "The editable source and original Markdown remain preserved. The original source manifest describes frozen inputs, not this later build. Actual build receipt and log are in build/. This is technical document processing, not scientific verification, venue acceptance or automatic submission.\n"
        ).encode()
        extras = [manifest, log, ManuscriptSourceFile("README.md", summary, service.sha(summary))]
        if result.pdf is not None:
            extras.append(
                ManuscriptSourceFile("output/manuscript.pdf", result.pdf, service.sha(result.pdf))
            )
        all_files = tuple(f for f in files if f.path not in {x.path for x in extras}) + tuple(
            extras
        )
        manifest_payload = json.loads(receipt)
        manifest_payload["output_inventory"] = [
            {"path": f.path, "sha256": f.sha256, "size_bytes": len(f.content)}
            for f in sorted(all_files, key=lambda f: f.path)
            if f.path != manifest.path
        ]
        manifest_bytes = json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True).encode()
        manifest = ManuscriptSourceFile(manifest.path, manifest_bytes, service.sha(manifest_bytes))
        source = ManuscriptSourceProject(
            tuple(f for f in all_files if f.path != manifest.path) + (manifest,),
            rendered_source_sha,
            (),
            row.selection["template_key"],
            compiled=result.status == "READY",
        )
        archive = registry.manuscript_source_renderer().pack(source, build_outputs=True)
        source_attachment = await save_bytes(
            db,
            owner,
            archive,
            f"manuscript-{identity}.zip",
            "application/zip",
            40 * 1024 * 1024,
            token,
            "source",
        )
        source_attachment_id = source_attachment.id
        stored_attempt = db.get(ManuscriptBuildAttempt, token)
        assert stored_attempt is not None
        stored_attempt.source_attachment_id = source_attachment_id
        db.commit()
        row = db.scalar(
            select(ManuscriptBuild)
            .where(ManuscriptBuild.id == identity, ManuscriptBuild.user_id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = db.get(ManuscriptBuildAttempt, token)
        assert row is not None and attempt is not None
        attempt.source_attachment_id = source_attachment_id
        attempt.log_attachment_id = log_attachment_id
        attempt.pdf_attachment_id = pdf_attachment_id
        attempt.ended_at = datetime.now(UTC)
        if row.lease_token != token or row.status not in {"RUNNING", "CANCEL_REQUESTED"}:
            attempt.status = "LATE"
        else:
            attempt.status = result.status
            row.status = (
                "CANCELLED"
                if row.status == "CANCEL_REQUESTED"
                else "READY"
                if result.status == "READY"
                else "NEEDS_ATTENTION"
                if result.status in {"NEEDS_ATTENTION", "TIMED_OUT"}
                else "FAILED"
            )
            row.source_attachment_id = source_attachment_id
            row.source_zip_sha256 = service.sha(archive)
            row.source_zip_size_bytes = len(archive)
            row.log_attachment_id = log_attachment_id
            row.pdf_attachment_id = pdf_attachment_id if row.status == "READY" else None
            row.lease_token = None
            row.lease_expires_at = None
        db.commit()
        return row
    except Exception as error:
        db.rollback()
        row = db.scalar(
            select(ManuscriptBuild)
            .where(ManuscriptBuild.id == identity, ManuscriptBuild.user_id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = db.get(ManuscriptBuildAttempt, token)
        assert row is not None and attempt is not None
        attempt.error_code = "BUILD_" + type(error).__name__.upper()
        attempt.observations = [
            *attempt.observations,
            {"error_type": type(error).__name__, "message": str(error)[:1000]},
        ]
        attempt.ended_at = datetime.now(UTC)
        if row.lease_token == token and row.status in {"RUNNING", "CANCEL_REQUESTED"}:
            row.status = "CANCELLED" if row.status == "CANCEL_REQUESTED" else "NEEDS_ATTENTION"
            attempt.status = row.status
            row.lease_token = None
            row.lease_expires_at = None
        else:
            attempt.status = "LATE"
        db.commit()
        return row
    finally:
        pulse.cancel()
        try:
            await pulse
        except asyncio.CancelledError:
            pass


async def run_worker() -> None:
    while True:
        try:
            with SessionLocal() as db:
                completed = await process_next(db)
        except Exception:
            import logging

            logging.getLogger("researchos.document-worker").exception(
                "Document build worker failed"
            )
            completed = None
        await asyncio.sleep(1 if completed else 3)
