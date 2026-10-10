"""Read-only handoff of owned persisted reading facts; no filesystem or model I/O."""

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.task_results import (
    EnvelopeArtifact,
    EnvelopeGap,
    EnvelopeInputRef,
    EnvelopeReceipt,
    ReadingEnvelopeSkillOut,
    ReadingResultEnvelopeOut,
)
from app.errors import DomainError
from app.models import (
    AnalysisInputSnapshot,
    Attachment,
    CanonicalAnalyticalNote,
    Paper,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperPDFReadingSource,
    PaperReadingApproval,
    PaperReadingApprovalPlan,
    ProjectPaper,
    ResearchEvent,
    ResearchProject,
)
from app.services import reading_source_bindings
from app.services.analysis_outcomes import REVALIDATED_EVENT, UNCERTAIN_EVENT, UNUSABLE_EVENT
from app.services.analysis_worker import _request_from_snapshot
from app.services.analytical_plans import plan_payload
from app.services.note_deletion_state import require_not_permanently_deleted
from app.services.paper_analysis import _payload_hash
from app.services.pdf_reading import validate_pdf_frozen


def _tokens(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _response_id(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 200 else None


def reading_result_envelope(
    db: Session, owner: uuid.UUID, job_id: uuid.UUID
) -> ReadingResultEnvelopeOut:
    # A projection must not flush a caller's unrelated pending changes.
    with db.no_autoflush:
        return _project(db, owner, job_id)


def _project(db: Session, owner: uuid.UUID, job_id: uuid.UUID) -> ReadingResultEnvelopeOut:
    require_not_permanently_deleted(db, owner, job_id)
    job = db.scalar(
        select(PaperAnalysisJob)
        .join(Paper, Paper.id == PaperAnalysisJob.paper_id)
        .where(
            PaperAnalysisJob.id == job_id,
            PaperAnalysisJob.user_id == owner,
            Paper.user_id == owner,
        )
    )
    if job is None:
        raise DomainError("NOT_FOUND", "Owned paper analysis job not found", 404)
    gaps: list[EnvelopeGap] = []
    blocked = False

    def gap(code: str, detail: str, *, critical: bool = False) -> None:
        nonlocal blocked
        if not any(row.code == code for row in gaps):
            gaps.append(EnvelopeGap(code=code, detail=detail))
        blocked |= critical

    gap(
        "ATTEMPT_ID_NOT_RECORDED",
        "No independent durable attempt identity was recorded; part and event references remain separate.",
    )
    gap(
        "EXECUTION_PROJECT_NOT_RECORDED",
        "No project identity was frozen on this execution; project_ids describes current owned paper associations only.",
    )
    project_ids = list(
        db.scalars(
            select(ResearchProject.id)
            .join(ProjectPaper, ProjectPaper.project_id == ResearchProject.id)
            .join(Paper, Paper.id == ProjectPaper.paper_id)
            .where(
                ResearchProject.user_id == owner,
                Paper.user_id == owner,
                ProjectPaper.paper_id == job.paper_id,
            )
            .distinct()
            .order_by(ResearchProject.id)
        )
    )
    if len(project_ids) > 1:
        gap(
            "PROJECT_CONTEXT_AMBIGUOUS",
            "This paper is linked to multiple owned projects; none is inferred as the execution project.",
        )
    elif not project_ids:
        gap("PROJECT_NOT_LINKED", "No owned project relationship is recorded for this paper.")
    paper = db.get(Paper, job.paper_id)
    assert paper is not None
    refs = [
        EnvelopeInputRef(kind="PAPER", id=str(paper.id)),
        EnvelopeInputRef(kind="AI_MODEL", id=job.model_key),
    ]
    refs.extend(
        EnvelopeInputRef(kind="CURRENT_PROJECT_ASSOCIATION", id=str(identity))
        for identity in project_ids
    )
    source = db.scalar(
        select(PaperPDFReadingSource).where(
            PaperPDFReadingSource.job_id == job.id, PaperPDFReadingSource.user_id == owner
        )
    )
    plan = db.scalar(
        select(PaperReadingApprovalPlan)
        .join(PaperReadingApproval, PaperReadingApproval.plan_id == PaperReadingApprovalPlan.id)
        .where(
            PaperReadingApproval.job_id == job.id,
            PaperReadingApproval.user_id == owner,
            PaperReadingApprovalPlan.user_id == owner,
            PaperReadingApprovalPlan.paper_id == job.paper_id,
        )
    )
    plan_valid = False
    refs[0].version = str(plan.paper_version) if plan is not None else None
    source_verified = False
    if source is not None:
        refs.append(
            EnvelopeInputRef(
                kind="ORIGINAL_PDF",
                id=str(source.attachment_id),
                sha256=source.sha256,
                version=source.render_version,
                page_count=source.page_count,
            )
        )
    else:
        gap(
            "ORIGINAL_PDF_NOT_RECORDED",
            "This historical task has no owned original-PDF reading source.",
            critical=job.source_type == "PDF",
        )
    if plan is None:
        gap(
            "OWNER_APPROVAL_NOT_RECORDED",
            "No owned per-paper canonical approval plan is linked to this job.",
            critical=job.source_type == "PDF",
        )
    else:
        refs.append(
            EnvelopeInputRef(
                kind="READING_APPROVAL_PLAN",
                id=str(plan.id),
                sha256=plan.plan_sha256,
                version=plan.source_binding_version,
                page_count=plan.page_count,
            )
        )
        rows = reading_source_bindings.sources(db, plan)
        for row in rows:
            refs.append(
                EnvelopeInputRef(
                    kind="READING_SOURCE_FILE", id=row.file_key_sha256, sha256=row.sha256
                )
            )
        try:
            if _payload_hash(plan_payload(plan)) != plan.plan_sha256:
                raise DomainError("READING_PLAN_CHANGED", "Frozen plan hash changed", 409)
            reading_source_bindings.validate(plan, rows)
            plan_valid = True
            source_verified = plan.source_manifest_sha256 is not None
        except (DomainError, ValidationError, ValueError, TypeError, UnicodeError):
            gap(
                "READING_SOURCE_INVALID",
                "Frozen approval or actual-source evidence failed local database validation.",
                critical=True,
            )
        if plan.source_manifest_sha256 is None:
            gap(
                "SOURCE_FILES_NOT_RECORDED",
                "The historical approval retains its assembled instruction hash, but actual source-file versions were not captured.",
            )
    snapshot = db.scalar(
        select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.job_id == job.id)
    )
    snapshot_valid = False
    if snapshot is None:
        gap(
            "INPUT_SNAPSHOT_NOT_RECORDED",
            "No durable analysis input snapshot is available.",
            critical=True,
        )
    else:
        refs.append(
            EnvelopeInputRef(
                kind="ANALYSIS_INPUT_SNAPSHOT",
                id=str(job.id),
                sha256=snapshot.input_sha256,
                version=job.schema_version,
            )
        )
        try:
            if (
                snapshot.input_sha256 != job.input_sha256
                or _payload_hash(snapshot.payload) != snapshot.input_sha256
            ):
                raise DomainError("INVALID_SNAPSHOT", "Input snapshot hash changed", 409)
            if job.source_type == "PDF":
                validate_pdf_frozen(db, job, _request_from_snapshot(snapshot))
            snapshot_valid = True
        except (DomainError, ValidationError, ValueError, TypeError, UnicodeError):
            gap(
                "INPUT_SNAPSHOT_INVALID",
                "Persisted input or PDF/skill approval relationships failed local database validation.",
                critical=True,
            )
    source_verified = source_verified and snapshot_valid and source is not None
    skill = None
    recorded_binding = plan if plan is not None else source
    if recorded_binding is not None:
        skill = ReadingEnvelopeSkillOut(
            key=recorded_binding.skill_key,
            version=recorded_binding.skill_version,
            assembled_sha256=recorded_binding.skill_sha256,
            source_manifest_sha256=plan.source_manifest_sha256 if plan else None,
            source_binding_version=plan.source_binding_version if plan else None,
            source_verified=source_verified,
        )
    parts = list(
        db.scalars(
            select(PaperAnalysisPart)
            .where(
                PaperAnalysisPart.user_id == owner,
                PaperAnalysisPart.job_id == job.id,
            )
            .order_by(PaperAnalysisPart.part_index)
        )
    )
    if any(part.status == "NEEDS_ATTENTION" for part in parts):
        gap(
            "PART_OUTCOME_UNCONFIRMED",
            "A persisted reading part has an unknown outcome; no completed whole-paper result is proposed.",
            critical=True,
        )
    if any(part.status == "ANALYZING" for part in parts):
        gap(
            "PART_IN_PROGRESS",
            "A reading part is currently analyzing; wait for its durable result before proposing whole-paper completion.",
        )
    if any(part.status == "FAILED" for part in parts):
        gap(
            "PART_FAILED",
            "A persisted reading part failed; its receipt remains separate from an accepted whole-paper result.",
            critical=True,
        )
    receipts = [
        EnvelopeReceipt(
            id=str(part.id),
            kind="ANALYSIS_PART",
            status=part.status,
            provider_response_id=_response_id(part.provider_response_id),
            input_tokens=_tokens(part.input_tokens),
            output_tokens=_tokens(part.output_tokens),
        )
        for part in parts
    ]
    event_status = {
        UNCERTAIN_EVENT: "OUTCOME_UNCERTAIN",
        UNUSABLE_EVENT: "UNUSABLE",
        REVALIDATED_EVENT: "LOCALLY_REVALIDATED",
        "paper.analysis_completed": "COMPLETED",
    }
    events = list(
        db.scalars(
            select(ResearchEvent)
            .where(
                ResearchEvent.user_id == owner,
                ResearchEvent.correlation_id == job.id,
                ResearchEvent.paper_id == job.paper_id,
                ResearchEvent.event_type.in_(event_status),
            )
            .order_by(ResearchEvent.occurred_at, ResearchEvent.id)
        )
    )
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if not isinstance(event.payload, dict):
            gap(
                "RECEIPT_METADATA_INVALID",
                "A recognized durable event has invalid metadata; no usage or provider response identity is inferred.",
            )
        receipts.append(
            EnvelopeReceipt(
                id=str(event.event_id),
                kind=event.event_type,
                status=event_status[event.event_type],
                provider_response_id=_response_id(payload.get("provider_response_id")),
                input_tokens=_tokens(
                    payload.get("input_tokens", payload.get("reported_input_tokens"))
                ),
                output_tokens=_tokens(
                    payload.get("output_tokens", payload.get("reported_output_tokens"))
                ),
            )
        )
        if event.event_type == UNCERTAIN_EVENT:
            historical = job.status == "COMPLETED"
            gap(
                "HISTORICAL_PROVIDER_OUTCOME_UNCERTAIN"
                if historical
                else "PROVIDER_OUTCOME_UNCERTAIN",
                "A durable unknown provider outcome remains recorded; later completed results do not resolve this earlier call or initiate a retry.",
                critical=not historical,
            )
        elif event.event_type == UNUSABLE_EVENT:
            gap(
                "UNUSABLE_RESPONSE_RECORDED",
                "An unusable response receipt is retained; it is not an accepted scientific result.",
            )
        elif event.event_type == REVALIDATED_EVENT:
            gap(
                "LOCAL_REVALIDATION_NOT_SCIENTIFIC_REVIEW",
                "A local result-check receipt is recorded; it does not establish human scientific approval.",
            )
    if not receipts:
        gap(
            "TOOL_RECEIPTS_NOT_RECORDED",
            "No owned persisted part or recognized model-call event is available.",
        )
    if job.status in {
        "FAILED",
        "NEEDS_ATTENTION",
        "CANCELLED",
        "WAITING_CONFIG",
        "WAITING_BUDGET",
        "WAITING_INPUT_REDUCTION",
    }:
        gap(
            "JOB_NOT_COMPLETE",
            "The task is failed, cancelled, waiting or unconfirmed; no complete result is proposed.",
            critical=True,
        )
    elif job.status != "COMPLETED":
        gap(
            "JOB_STILL_IN_PROGRESS",
            "The persisted job has not completed; partial receipts remain visible.",
        )
    artifacts: list[EnvelopeArtifact] = []
    note = db.scalar(
        select(CanonicalAnalyticalNote).where(
            CanonicalAnalyticalNote.user_id == owner, CanonicalAnalyticalNote.job_id == job.id
        )
    )
    note_valid = False
    file_recheck_available = False
    if note is None:
        gap(
            "CANONICAL_RESULT_NOT_RECORDED",
            "No owned complete canonical Markdown result is recorded for this job.",
        )
    else:
        try:
            body = note.markdown.encode("utf-8")
            note_valid = hashlib.sha256(body).hexdigest() == note.sha256
        except UnicodeError:
            body = b""
        if not note_valid:
            gap(
                "CANONICAL_HASH_MISMATCH",
                "Canonical result content does not match its persisted hash.",
                critical=True,
            )
        linked = plan is not None and note.plan_id == plan.id
        if not linked:
            gap(
                "CANONICAL_APPROVAL_LINK_INVALID",
                "The canonical result is not linked to this job's owned approval plan.",
                critical=True,
            )
        path_matches = plan is not None and note.output_path.replace("\\", "/") == str(
            PurePosixPath(plan.output_root.replace("\\", "/")) / plan.output_path
        )
        if not path_matches:
            gap(
                "CANONICAL_OUTPUT_PATH_MISMATCH",
                "The recorded canonical output path does not match its owned approved destination.",
                critical=True,
            )
        verification = (
            "INVALID"
            if not note_valid
            else "RECORDED_FILE_NOT_RECHECKED"
            if note.export_status == "SAVED"
            else "HASH_VERIFIED_CANDIDATE"
        )
        artifacts.append(
            EnvelopeArtifact(
                kind="CANONICAL_ANALYTICAL_NOTE",
                id=note.id,
                sha256=note.sha256,
                size_bytes=len(body),
                path=note.output_path if linked else None,
                verification=verification,
            )
        )
        gap(
            "CANDIDATE_UNREVIEWED",
            "No human scientific review of this exact canonical Markdown hash is proven; the result remains a candidate.",
        )
        if note.export_status == "SAVED":
            gap(
                "FILE_NOT_RECHECKED",
                "SAVED records an earlier publication receipt; current filesystem bytes have not been checked by this GET.",
            )
        else:
            gap(
                "FILE_PUBLICATION_NOT_SAVED",
                "The canonical result is retained in the database; a successful final-file publication is not recorded.",
            )
        file_recheck_available = (
            linked
            and path_matches
            and note_valid
            and plan_valid
            and snapshot_valid
            and job.source_type == "PDF"
        )
        if note.attachment_id is not None:
            attachment = db.scalar(
                select(Attachment).where(
                    Attachment.id == note.attachment_id, Attachment.user_id == owner
                )
            )
            if attachment is None:
                gap(
                    "ARTIFACT_ATTACHMENT_NOT_OWNED",
                    "The canonical attachment is unavailable in this owner's scope.",
                    critical=True,
                )
            else:
                coherent = attachment.sha256 == note.sha256 and attachment.size_bytes == len(body)
                if not coherent:
                    gap(
                        "ARTIFACT_ATTACHMENT_MISMATCH",
                        "Owned attachment metadata differs from the canonical result hash or byte size.",
                        critical=True,
                    )
                if attachment.size_bytes >= 0:
                    artifacts.append(
                        EnvelopeArtifact(
                            kind="MANAGED_ATTACHMENT",
                            id=attachment.id,
                            sha256=attachment.sha256,
                            size_bytes=attachment.size_bytes,
                            verification="RECORDED_ATTACHMENT_NOT_RECHECKED"
                            if coherent
                            else "INVALID",
                        )
                    )
                gap(
                    "ATTACHMENT_NOT_RECHECKED",
                    "Owned attachment metadata is recorded; current stored object bytes were not read.",
                )
        else:
            gap(
                "ARTIFACT_ATTACHMENT_NOT_RECORDED",
                "No managed attachment backup is linked to this canonical result.",
            )
    proposal = (
        "BLOCKED"
        if blocked
        else "NEEDS_HUMAN_REVIEW"
        if note_valid and job.status == "COMPLETED"
        else "NO_RESULT"
    )
    return ReadingResultEnvelopeOut(
        task_id=job.id,
        project_id=None,
        project_ids=project_ids,
        paper_id=job.paper_id,
        checked_at=datetime.now(UTC),
        job_status=job.status,
        skill_binding=skill,
        input_refs=refs,
        output_artifacts=artifacts,
        tool_receipt_refs=receipts,
        gaps=gaps,
        completion_proposal=proposal,
        next_action="Inspect the recorded gaps and repair or resolve the blocked source/result before retrying."
        if blocked
        else "Review the original PDF and canonical candidate; explicitly check the saved file if needed."
        if proposal == "NEEDS_HUMAN_REVIEW"
        else "Wait for or explicitly start the approved reading task; no completed canonical result is available yet.",
        file_recheck_available=file_recheck_available and not blocked,
    )
