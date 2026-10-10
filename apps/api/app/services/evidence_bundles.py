"""Frozen internal evidence exports; Storage bytes and scientific status stay separate."""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.evidence_bundles import EvidenceFile, RenderedEvidenceBundle, evidence_payloads
from app.errors import DomainError
from app.models import Attachment, Author, Paper, PaperAuthor
from app.models_evidence_bundles import (
    EvidenceBundle,
    EvidenceBundleClaim,
    EvidenceBundleFile,
    EvidenceBundleSaveAttempt,
)
from app.providers import registry
from app.schemas_claims import ClaimRevisionOut
from app.schemas_evidence_bundles import (
    EvidenceBundleAttemptOut,
    EvidenceBundleCreate,
    EvidenceBundleFileOut,
    EvidenceBundleOut,
    EvidenceBundlePreview,
    EvidenceBundleRetry,
    EvidenceBundleSelection,
)
from app.services import claims
from app.services.projects import get_project
from app.services.research_briefs import digest


def fail(code: str, message: str) -> DomainError:
    return DomainError(code, message, 409)


def snapshot(
    db: Session, owner: uuid.UUID, project: uuid.UUID, selected: EvidenceBundleSelection
) -> dict[str, Any]:
    parent = get_project(db, owner, project)
    records = []
    paper_ids: set[uuid.UUID] = set()
    for source in selected.claims:
        row = claims.get(db, owner, source.claim_id)
        if row.project_id != project:
            raise fail("BUNDLE_CLAIM_SCOPE", "Selected claim is outside this project")
        revision = claims.revision(db, row, source.revision_id)
        out = claims.revision_out(db, revision)
        if (
            out.sha256 != source.expected_revision_sha256
            or not out.integrity_valid
            or not out.context_current
        ):
            raise fail("BUNDLE_SOURCE_CHANGED", "Selected claim/evidence is changed or not intact")
        records.append(out.model_dump(mode="json"))
        paper_ids.update(item.paper_id for item in out.evidence if item.paper_id)
    references = []
    for identity in sorted(paper_ids, key=str):
        paper = db.scalar(
            select(Paper)
            .where(Paper.id == identity, Paper.user_id == owner)
            .execution_options(populate_existing=True)
        )
        if paper is None:
            raise fail("BUNDLE_SOURCE_CHANGED", "Reference source no longer belongs to this owner")
        authors = list(
            db.scalars(
                select(Author.display_name)
                .join(PaperAuthor, PaperAuthor.author_id == Author.id)
                .where(PaperAuthor.paper_id == paper.id, Author.user_id == owner)
                .order_by(PaperAuthor.position)
            )
        )
        references.append(
            {
                "paper_id": str(paper.id),
                "paper_version": paper.version,
                "title": paper.title,
                "year": paper.year,
                "doi": paper.doi,
                "url": paper.url,
                "authors": authors,
                "verification": "STORED_METADATA_NOT_CITATION_SUPPORT_VERIFICATION",
            }
        )
    return {
        "contract": "researchos-evidence-snapshot-v1",
        "owner_id": str(owner),
        "project_id": str(project),
        "project_version": parent.version,
        "label": selected.label,
        "claims": records,
        "references": references,
        "source_artifact_bytes_included": False,
        "execution_authorized": False,
    }


def render(source: dict[str, Any]) -> RenderedEvidenceBundle:
    provider = registry.evidence_bundle_renderer()
    try:
        bundle = provider.render(source)
        if (
            hashlib.sha256(bundle.content).hexdigest() != bundle.sha256
            or len(bundle.content) != bundle.size_bytes
        ):
            raise ValueError("Invalid ZIP bytes")
        # Independently require raw evidence.json to preserve the frozen source.
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            expected_payloads = evidence_payloads(source)
            if (
                set(archive.namelist()) != set(expected_payloads) | {"manifest.json", "SHA256SUMS"}
                or len(archive.namelist()) != len(expected_payloads) + 2
            ):
                raise ValueError("Unexpected evidence file set")
            for path, content in expected_payloads.items():
                if archive.read(path) != content.encode("utf-8"):
                    raise ValueError("Derived evidence content differs from source contract")
            if set(archive.namelist()) != {file.path for file in bundle.files}:
                raise ValueError("ZIP file inventory differs")
            for file in bundle.files:
                raw = file.content.encode()
                if (
                    archive.read(file.path) != raw
                    or hashlib.sha256(raw).hexdigest() != file.sha256
                    or len(raw) != file.size_bytes
                ):
                    raise ValueError("Actual file content differs")
            if json.loads(archive.read("evidence.json")) != source:
                raise ValueError("Source snapshot was replaced")
            manifest = json.loads(archive.read("manifest.json"))
            if (
                manifest["snapshot_sha256"] != digest(source)
                or manifest["source_artifact_bytes_included"] is not False
                or manifest["execution_authorized"] is not False
            ):
                raise ValueError("Invalid scientific/transfer boundary")
            expected_entries = [
                {"path": f.path, "sha256": f.sha256, "size_bytes": f.size_bytes}
                for f in sorted(bundle.files, key=lambda f: f.path)
                if f.path != "manifest.json"
            ]
            if manifest["files"] != expected_entries:
                raise ValueError("Evidence file manifest differs")
            sums = "".join(
                f"{hashlib.sha256(content.encode()).hexdigest()}  {path}\n"
                for path, content in sorted(expected_payloads.items())
            )
            if archive.read("SHA256SUMS") != sums.encode():
                raise ValueError("Evidence checksum manifest differs")
        return bundle
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        raise fail(
            "EVIDENCE_RENDER_INVALID", "Rendered evidence package failed exact verification"
        ) from error


def preview(
    db: Session, owner: uuid.UUID, project: uuid.UUID, selected: EvidenceBundleSelection
) -> tuple[EvidenceBundlePreview, dict[str, Any], RenderedEvidenceBundle]:
    source = snapshot(db, owner, project, selected)
    bundle = render(source)
    files = [EvidenceBundleFileOut(**asdict(file)) for file in bundle.files]
    gaps = sorted({gap for claim in source["claims"] for gap in claim["gaps"]})
    if any(claim["scientific_state"] != "OWNER_ACCEPTED" for claim in source["claims"]):
        gaps.append("INTERNAL_CANDIDATE_CLAIMS_NOT_OWNER_ACCEPTED")
    value = digest(
        {
            "selection": selected.model_dump(mode="json"),
            "snapshot_sha256": digest(source),
            "files": [f.model_dump() for f in files],
            "bundle_sha256": bundle.sha256,
        }
    )
    return (
        EvidenceBundlePreview(
            selection=selected,
            snapshot_sha256=digest(source),
            preview_sha256=value,
            bundle_sha256=bundle.sha256,
            bundle_size_bytes=bundle.size_bytes,
            files=files,
            gaps=gaps,
        ),
        source,
        bundle,
    )


def get(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> EvidenceBundle:
    get_project(db, owner, project)
    query = (
        select(EvidenceBundle)
        .where(
            EvidenceBundle.id == identity,
            EvidenceBundle.user_id == owner,
            EvidenceBundle.project_id == project,
        )
        .execution_options(populate_existing=True)
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise DomainError("NOT_FOUND", "Evidence bundle not found", 404)
    return row


def files(db: Session, row: EvidenceBundle) -> tuple[EvidenceFile, ...]:
    return tuple(
        EvidenceFile(f.path, f.content, f.sha256, f.size_bytes)
        for f in db.scalars(
            select(EvidenceBundleFile)
            .where(
                EvidenceBundleFile.bundle_id == row.id, EvidenceBundleFile.user_id == row.user_id
            )
            .order_by(EvidenceBundleFile.path)
        )
    )


def intact(db: Session, row: EvidenceBundle) -> bool:
    try:
        expected = render(row.snapshot)
        selection = EvidenceBundleSelection.model_validate(row.selection)
        actual = files(db, row)
        value = digest(
            {
                "selection": selection.model_dump(mode="json"),
                "snapshot_sha256": digest(row.snapshot),
                "files": [asdict(f) for f in actual],
                "bundle_sha256": expected.sha256,
            }
        )
        links = list(
            db.scalars(
                select(EvidenceBundleClaim)
                .where(
                    EvidenceBundleClaim.bundle_id == row.id,
                    EvidenceBundleClaim.user_id == row.user_id,
                )
                .order_by(EvidenceBundleClaim.position)
            )
        )
        return (
            expected.files == actual
            and expected.sha256 == row.bundle_sha256
            and expected.size_bytes == row.bundle_size_bytes
            and digest(row.snapshot) == row.snapshot_sha256
            and value == row.preview_sha256
            and [
                (str(x.claim_id), str(x.revision_id), x.revision_sha256, x.evidence_sha256)
                for x in links
            ]
            == [
                (str(x.claim_id), str(x.id), x.sha256, x.evidence_sha256)
                for x in (
                    ClaimRevisionOut.model_validate(entry)
                    for entry in row.snapshot["claims"]
                )
            ]
        )
    except (DomainError, ValueError, TypeError, KeyError):
        return False


def out(db: Session, row: EvidenceBundle) -> EvidenceBundleOut:
    gaps = []
    valid = intact(db, row)
    if not valid:
        gaps.append("FROZEN_EVIDENCE_BUNDLE_INVALID")
    try:
        is_current = (
            digest(
                snapshot(
                    db,
                    row.user_id,
                    row.project_id,
                    EvidenceBundleSelection.model_validate(row.selection),
                )
            )
            == row.snapshot_sha256
        )
    except DomainError:
        is_current = False
    if not is_current:
        gaps.append("SOURCE_OR_REVIEW_CONTEXT_CHANGED")
    attempts = db.scalars(
        select(EvidenceBundleSaveAttempt)
        .where(
            EvidenceBundleSaveAttempt.bundle_id == row.id,
            EvidenceBundleSaveAttempt.user_id == row.user_id,
        )
        .order_by(EvidenceBundleSaveAttempt.started_at, EvidenceBundleSaveAttempt.id)
    )
    return EvidenceBundleOut(
        **{
            k: getattr(row, k)
            for k in (
                "id",
                "project_id",
                "label",
                "status",
                "bundle_sha256",
                "created_at",
                "snapshot_sha256",
                "preview_sha256",
                "bundle_size_bytes",
                "snapshot",
                "attachment_id",
            )
        },
        selection=EvidenceBundleSelection.model_validate(row.selection),
        files=[EvidenceBundleFileOut(**asdict(f)) for f in files(db, row)],
        attempts=[EvidenceBundleAttemptOut.model_validate(a) for a in attempts],
        integrity_valid=valid,
        context_current=is_current,
        current_gaps=gaps,
    )


async def save(
    db: Session, row: EvidenceBundle, attempt: EvidenceBundleSaveAttempt
) -> EvidenceBundle:
    identity, owner, project, token = row.id, row.user_id, row.project_id, attempt.id
    expected_sha, expected_size = row.bundle_sha256, row.bundle_size_bytes
    frozen_files = files(db, row)
    storage = registry.storage_provider()
    db.rollback()
    observations = []
    attachment = None
    error_code = None
    try:
        raw = registry.evidence_bundle_renderer().pack(frozen_files).content
        if hashlib.sha256(raw).hexdigest() != expected_sha or len(raw) != expected_size:
            raise fail("EVIDENCE_RENDER_INVALID", "Frozen evidence ZIP differs before Storage")

        async def body() -> AsyncIterator[bytes]:
            yield raw

        saved = await storage.save(body(), mime_type="application/zip", max_bytes=4 * 1024 * 1024)
        observations.append(
            {
                "phase": "SAVE_RETURNED",
                "object_key": saved.key,
                "sha256": saved.sha256,
                "size_bytes": saved.size_bytes,
            }
        )
        if saved.sha256 != expected_sha or saved.size_bytes != expected_size:
            raise fail("BUNDLE_STORAGE_MISMATCH", "Stored bytes differ")
        reader = await storage.open(saved.key)
        try:
            actual = bytearray()
            async for chunk in reader.iter_bytes():
                if len(actual) + len(chunk) > expected_size:
                    raise fail("BUNDLE_STORAGE_MISMATCH", "Stored bytes exceed expected size")
                actual.extend(chunk)
        finally:
            await reader.close()
        if bytes(actual) != raw or hashlib.sha256(actual).hexdigest() != expected_sha:
            raise fail("BUNDLE_STORAGE_MISMATCH", "Readback bytes differ")
        db.expire_all()
        current = get(db, owner, project, identity, lock=True)
        attachment = db.scalar(
            select(Attachment).where(
                Attachment.user_id == owner,
                Attachment.object_key == saved.key,
                Attachment.storage_provider == storage.provider_key,
                Attachment.sha256 == expected_sha,
                Attachment.size_bytes == expected_size,
                Attachment.deleted_at.is_(None),
            )
        )
        if attachment is None:
            attachment = Attachment(
                id=uuid.uuid4(),
                user_id=owner,
                storage_provider=storage.provider_key,
                object_key=saved.key,
                original_filename=f"evidence-{identity}.zip",
                mime_type="application/zip",
                size_bytes=expected_size,
                sha256=expected_sha,
            )
            db.add(attachment)
        db.flush()
        if current.current_attempt_id != token:
            state = "LATE"
        elif not intact(db, current):
            state = "NEEDS_ATTENTION"
            error_code = "BUNDLE_FROZEN_SOURCE_CHANGED"
        else:
            state = "READY"
    except Exception as error:
        db.rollback()
        attachment = None
        state = "NEEDS_ATTENTION"
        error_code = error.code if isinstance(error, DomainError) else "EVIDENCE_SAVE_UNKNOWN"
    current = get(db, owner, project, identity, lock=True)
    recorded = db.get(EvidenceBundleSaveAttempt, token)
    if recorded is None:
        raise fail("BUNDLE_ATTEMPT_MISSING", "Save attempt no longer exists")
    recorded.status = "LATE" if current.current_attempt_id != token else state
    recorded.error_code = error_code
    recorded.observations = observations
    recorded.ended_at = datetime.now(UTC)
    if attachment is not None:
        recorded.attachment_id = attachment.id
    if current.current_attempt_id == token and current.status != "READY":
        current.status = state
        if state == "READY" and attachment is not None:
            current.attachment_id = attachment.id
    db.commit()
    db.refresh(current)
    return current


async def create(
    db: Session, owner: uuid.UUID, project: uuid.UUID, body: EvidenceBundleCreate
) -> EvidenceBundle:
    get_project(db, owner, project)
    request = digest(body.model_dump(mode="json"))
    existing = db.scalar(
        select(EvidenceBundle).where(
            EvidenceBundle.project_id == project,
            EvidenceBundle.user_id == owner,
            EvidenceBundle.idempotency_key == body.idempotency_key,
        )
    )
    if existing:
        if existing.request_sha256 != request:
            raise fail("IDEMPOTENCY_CONFLICT", "Bundle creation key differs")
        return existing
    frozen, source, bundle = preview(db, owner, project, body.selection)
    if frozen.preview_sha256 != body.expected_preview_sha256:
        raise fail("BUNDLE_PREVIEW_CHANGED", "Sources or reviews changed; preview again")
    if frozen.gaps and not body.acknowledge_gaps:
        raise fail("BUNDLE_GAPS_ACK_REQUIRED", "Acknowledge internal evidence gaps")
    token = uuid.uuid4()
    row = EvidenceBundle(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project,
        label=body.selection.label,
        selection=body.selection.model_dump(mode="json"),
        snapshot=source,
        snapshot_sha256=frozen.snapshot_sha256,
        preview_sha256=frozen.preview_sha256,
        bundle_sha256=bundle.sha256,
        bundle_size_bytes=bundle.size_bytes,
        status="SAVING",
        current_attempt_id=token,
        idempotency_key=body.idempotency_key,
        request_sha256=request,
    )
    try:
        db.add(row)
        db.flush()
        for position, selected in enumerate(body.selection.claims):
            entry = source["claims"][position]
            db.add(
                EvidenceBundleClaim(
                    bundle_id=row.id,
                    revision_id=selected.revision_id,
                    claim_id=selected.claim_id,
                    user_id=owner,
                    project_id=project,
                    position=position,
                    revision_sha256=entry["sha256"],
                    evidence_sha256=entry["evidence_sha256"],
                )
            )
        for f in bundle.files:
            db.add(
                EvidenceBundleFile(bundle_id=row.id, user_id=owner, project_id=project, **asdict(f))
            )
        attempt = EvidenceBundleSaveAttempt(
            id=token,
            bundle_id=row.id,
            user_id=owner,
            project_id=project,
            status="SAVING",
            idempotency_key="initial",
            observations=[],
        )
        db.add(attempt)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise fail("BUNDLE_CREATE_CONFLICT", "Concurrent creation; inspect the same key") from None
    return await save(db, row, attempt)


async def retry(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    identity: uuid.UUID,
    body: EvidenceBundleRetry,
) -> EvidenceBundle:
    row = get(db, owner, project, identity, lock=True)
    if row.preview_sha256 != body.expected_preview_sha256 or not intact(db, row):
        raise fail("BUNDLE_SOURCE_CHANGED", "Frozen package differs")
    existing = db.scalar(
        select(EvidenceBundleSaveAttempt).where(
            EvidenceBundleSaveAttempt.bundle_id == identity,
            EvidenceBundleSaveAttempt.user_id == owner,
            EvidenceBundleSaveAttempt.idempotency_key == body.idempotency_key,
        )
    )
    if existing or row.status == "READY":
        return row
    previous = db.get(EvidenceBundleSaveAttempt, row.current_attempt_id)
    if previous and previous.status == "SAVING":
        started = (
            previous.started_at.replace(tzinfo=UTC)
            if previous.started_at.tzinfo is None
            else previous.started_at
        )
        if (datetime.now(UTC) - started).total_seconds() < 300:
            raise fail("BUNDLE_SAVE_ACTIVE", "Save is still in its bounded activity window")
    if (
        len(
            list(
                db.scalars(
                    select(EvidenceBundleSaveAttempt.id).where(
                        EvidenceBundleSaveAttempt.bundle_id == identity
                    )
                )
            )
        )
        >= 50
    ):
        raise fail("BUNDLE_ATTEMPT_LIMIT", "Retain attempts and review before further retries")
    token = uuid.uuid4()
    row.current_attempt_id = token
    row.status = "SAVING"
    attempt = EvidenceBundleSaveAttempt(
        id=token,
        bundle_id=identity,
        user_id=owner,
        project_id=project,
        status="SAVING",
        idempotency_key=body.idempotency_key,
        observations=[],
    )
    db.add(attempt)
    db.commit()
    return await save(db, row, attempt)
