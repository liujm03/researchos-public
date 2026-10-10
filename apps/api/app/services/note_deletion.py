"""Durable irreversible deletion: fence, exact file receipts, then content removal."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.errors import DomainError
from app.models import (
    AnalysisInputSnapshot,
    Attachment,
    CanonicalAnalyticalNote,
    EntityTag,
    InboxItem,
    LiteratureIngestJob,
    NoteReviewAction,
    Paper,
    PaperAnalysisJob,
    PaperAnalysisPart,
    PaperResearchNote,
    ResearchEntity,
    ResearchEvent,
    ResearchNoteEvidence,
    ResearchNoteSection,
    User,
)
from app.models_note_deletion import NoteDeletionFile, NoteDeletionMember, NotePermanentDeletion
from app.models_note_trash import NoteTrashEntry, NoteTrashMember, NoteTrashOperation
from app.providers import registry
from app.schemas_note_deletion import NoteDeletionOut, NoteDeletionRequest
from app.services.note_deletion_plan import build_plan, dependency_blockers, family
from app.services.note_trash import _content, _sha

LEASE_SECONDS = 600
USAGE_KEYS = frozenset(
    {
        "job_id",
        "part_id",
        "attempt",
        "call_started_at",
        "input_sha256",
        "request_sha256",
        "budget_accounted_tokens",
        "allowance_basis",
        "usage_reported",
        "reported_input_tokens",
        "reported_output_tokens",
        "provider_response_id",
        "input_tokens",
        "output_tokens",
        "source_event_id",
        "source_attempt",
        "source_event_type",
        "accepted_result_sha256",
        "candidate_result_sha256",
        "restored_part_id",
        "restored_note_id",
        "scope",
        "provider_key",
        "model_key",
        "note_id",
    }
)


def get_operation(db: Session, owner: uuid.UUID, operation_id: uuid.UUID) -> NotePermanentDeletion:
    row = db.scalar(
        select(NotePermanentDeletion)
        .where(NotePermanentDeletion.id == operation_id, NotePermanentDeletion.user_id == owner)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "未找到本账户的永久删除记录。", 404)
    return row


def by_key(db: Session, owner: uuid.UUID, key: str) -> NotePermanentDeletion:
    row = db.scalar(
        select(NotePermanentDeletion)
        .where(NotePermanentDeletion.user_id == owner, NotePermanentDeletion.idempotency_key == key)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("NOT_FOUND", "尚未查到这次永久删除请求。", 404)
    return row


def out(db: Session, operation: NotePermanentDeletion) -> NoteDeletionOut:
    rows = list(
        db.scalars(
            select(NoteDeletionFile).where(
                NoteDeletionFile.operation_id == operation.id,
                NoteDeletionFile.user_id == operation.user_id,
            )
        )
    )
    return NoteDeletionOut(
        id=operation.id,
        note_id=operation.note_id,
        paper_id=operation.paper_id,
        preview_sha256=operation.preview_sha256,
        idempotency_key=operation.idempotency_key,
        state=operation.state,
        error_code=operation.error_code,
        error_message=operation.error_message,
        created_at=operation.created_at,
        completed_at=operation.completed_at,
        files_total=len(rows),
        files_deleted_count=sum(f.state == "DELETED" for f in rows),
    )


def _replay(
    db: Session, owner: uuid.UUID, note_id: uuid.UUID, body: NoteDeletionRequest
) -> NotePermanentDeletion | None:
    row = db.scalar(
        select(NotePermanentDeletion)
        .where(
            NotePermanentDeletion.user_id == owner,
            NotePermanentDeletion.idempotency_key == body.idempotency_key,
        )
        .execution_options(populate_existing=True)
    )
    if row is not None and (
        row.note_id != note_id
        or row.request_sha256 != _sha({"note_id": str(note_id), **body.model_dump()})
    ):
        raise DomainError("IDEMPOTENCY_CONFLICT", "原请求标识对应不同删除范围，请核查记录。", 409)
    return row


async def start(
    db: Session, owner: uuid.UUID, note_id: uuid.UUID, body: NoteDeletionRequest
) -> NotePermanentDeletion:
    previous = _replay(db, owner, note_id, body)
    if previous is not None:
        return previous
    db.scalar(select(User.id).where(User.id == owner).with_for_update())
    previous = _replay(db, owner, note_id, body)
    if previous is not None:
        return previous
    notes = family(db, owner, note_id)
    db.scalar(
        select(Paper.id)
        .where(Paper.id == notes[0].paper_id, Paper.user_id == owner)
        .with_for_update()
    )
    from app.services.note_deletion_state import lock_note_output_path

    jobs = {n.analysis_job_id for n in notes if n.analysis_job_id}
    canonicals = (
        list(
            db.scalars(
                select(CanonicalAnalyticalNote).where(
                    CanonicalAnalyticalNote.user_id == owner,
                    CanonicalAnalyticalNote.job_id.in_(jobs),
                )
            )
        )
        if jobs
        else []
    )
    from app.models import PaperReadingApprovalPlan

    paths = []
    for c in canonicals:
        reading_plan = db.get(PaperReadingApprovalPlan, c.plan_id)
        if reading_plan:
            paths.append((reading_plan.output_root, reading_plan.output_path))
    for output_root, relative_path in sorted(set(paths)):
        lock_note_output_path(db, owner, output_root, relative_path)
    if jobs:
        db.scalars(
            select(PaperAnalysisJob)
            .where(PaperAnalysisJob.user_id == owner, PaperAnalysisJob.id.in_(jobs))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        db.scalars(
            select(CanonicalAnalyticalNote)
            .where(
                CanonicalAnalyticalNote.user_id == owner, CanonicalAnalyticalNote.job_id.in_(jobs)
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    plan = await build_plan(db, owner, note_id)
    if not plan.preview.can_delete:
        raise DomainError(
            "NOTE_DELETION_BLOCKED",
            "存在引用、共享文件或未结束的处理，未执行删除。",
            409,
            plan.preview.model_dump(mode="json"),
        )
    if plan.preview.preview_sha256 != body.expected_preview_sha256:
        raise DomainError(
            "NOTE_DELETION_PREVIEW_CHANGED", "笔记或文件在预览后发生变化，请重新预览。", 409
        )
    admitted = db.scalar(
        select(NotePermanentDeletion).where(
            NotePermanentDeletion.user_id == owner,
            NotePermanentDeletion.family_key == plan.family_key,
        )
    )
    if admitted:
        raise DomainError(
            "NOTE_DELETION_ALREADY_ADMITTED",
            "该精读已有删除记录，请继续原操作。",
            409,
            {"operation_id": str(admitted.id)},
        )
    now, token = datetime.now(UTC), uuid.uuid4()
    operation = NotePermanentDeletion(
        id=uuid.uuid4(),
        user_id=owner,
        paper_id=plan.preview.paper_id,
        note_id=note_id,
        reading_job_id=plan.preview.reading_job_id,
        family_key=plan.family_key,
        idempotency_key=body.idempotency_key,
        request_sha256=_sha({"note_id": str(note_id), **body.model_dump()}),
        preview_sha256=plan.preview.preview_sha256,
        state="DELETING",
        lease_token=token,
        lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
        created_at=now,
    )
    db.add(operation)
    db.flush()
    if operation.reading_job_id:
        from app.services.analysis_outcomes import capture_deletion_budget_receipts

        capture_deletion_budget_receipts(db, owner, operation.reading_job_id, operation.id)
    for member in plan.preview.members:
        db.add(
            NoteDeletionMember(
                operation_id=operation.id,
                user_id=owner,
                note_id=member.note_id,
                revision=member.revision,
                content_sha256=member.content_sha256,
            )
        )
    for file in plan.files:
        db.add(
            NoteDeletionFile(
                id=uuid.uuid4(), operation_id=operation.id, user_id=owner, state="PENDING", **file
            )
        )
    db.execute(
        update(ResearchEntity)
        .where(
            ResearchEntity.user_id == owner,
            ResearchEntity.id.in_([m.note_id for m in plan.preview.members]),
        )
        .values(deleted_at=now)
    )
    db.commit()  # Admission is durable before any irreversible file I/O.
    return await _execute(db, owner, operation.id, token)


def _assert_lease(
    db: Session, owner: uuid.UUID, operation_id: uuid.UUID, token: uuid.UUID
) -> NotePermanentDeletion:
    operation = get_operation(db, owner, operation_id)
    expiry = operation.lease_expires_at
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if (
        operation.lease_token != token
        or expiry is None
        or expiry <= datetime.now(UTC)
        or operation.state != "DELETING"
    ):
        raise DomainError("NOTE_DELETION_LEASE_LOST", "删除执行权已改变，请核查原操作。", 409)
    return operation


async def retry(db: Session, owner: uuid.UUID, operation_id: uuid.UUID) -> NotePermanentDeletion:
    operation = get_operation(db, owner, operation_id)
    if operation.state == "COMPLETED":
        return operation
    now, token = datetime.now(UTC), uuid.uuid4()
    changed = db.scalar(
        update(NotePermanentDeletion)
        .where(
            NotePermanentDeletion.id == operation_id,
            NotePermanentDeletion.user_id == owner,
            NotePermanentDeletion.state != "COMPLETED",
            or_(
                NotePermanentDeletion.lease_token.is_(None),
                NotePermanentDeletion.lease_expires_at <= now,
            ),
        )
        .values(
            state="DELETING",
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            error_code=None,
            error_message=None,
        )
        .returning(NotePermanentDeletion.id)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if changed is None:
        raise DomainError("NOTE_DELETION_BUSY", "原删除仍在执行，请先核查状态。", 409)
    return await _execute(db, owner, operation_id, token)


async def _execute(
    db: Session, owner: uuid.UUID, operation_id: uuid.UUID, token: uuid.UUID
) -> NotePermanentDeletion:
    try:
        rows = list(
            db.scalars(
                select(NoteDeletionFile)
                .where(
                    NoteDeletionFile.operation_id == operation_id, NoteDeletionFile.user_id == owner
                )
                .order_by(NoteDeletionFile.id)
            )
        )
        for file in rows:
            _assert_lease(db, owner, operation_id, token)
            if file.state in {"DELETED", "ALREADY_ABSENT"}:
                continue
            provider = registry.generated_file_deletion_provider(
                file.root_path, "storage" if file.kind == "NOTE_MIRROR" else "markdown"
            )
            receipt = await asyncio.to_thread(
                provider.delete_verified, file.relative_path, file.sha256
            )
            _assert_lease(db, owner, operation_id, token)
            if (
                receipt.relative_path != file.relative_path
                or receipt.sha256 != file.sha256
                or receipt.status not in {"DELETED", "ALREADY_ABSENT"}
            ):
                raise DomainError(
                    "GENERATED_FILE_RECEIPT_INVALID", "文件删除回执与原范围不一致。", 503
                )
            file.state, file.error_code = receipt.status, None
            db.commit()  # Retain exact known file outcome before the next action.
        operation = _assert_lease(db, owner, operation_id, token)
        _purge_database(db, operation)
        operation.state, operation.completed_at = "COMPLETED", datetime.now(UTC)
        operation.lease_token = operation.lease_expires_at = None
        operation.error_code = operation.error_message = None
        db.commit()
        return get_operation(db, owner, operation_id)
    except Exception as cause:
        db.rollback()
        code = cause.code if isinstance(cause, DomainError) else "NOTE_DELETION_OUTCOME_UNKNOWN"
        message = (
            cause.message
            if isinstance(cause, DomainError)
            else "删除结果尚未完整确认，请核查原操作并继续；不会重新生成笔记。"
        )
        try:
            db.execute(
                update(NotePermanentDeletion)
                .where(
                    NotePermanentDeletion.id == operation_id,
                    NotePermanentDeletion.user_id == owner,
                    NotePermanentDeletion.lease_token == token,
                )
                .values(
                    state="NEEDS_ATTENTION",
                    error_code=code,
                    error_message=message,
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            db.commit()
            return get_operation(db, owner, operation_id)
        except Exception:
            db.rollback()
            raise DomainError(
                "NOTE_DELETION_OUTCOME_UNKNOWN", "请按原请求标识核查删除状态。", 503
            ) from None


def _purge_database(db: Session, operation: NotePermanentDeletion) -> None:
    owner = operation.user_id
    db.scalar(select(User.id).where(User.id == owner).with_for_update())
    db.scalar(
        select(Paper.id)
        .where(Paper.id == operation.paper_id, Paper.user_id == owner)
        .with_for_update()
    )
    members = list(
        db.scalars(
            select(NoteDeletionMember).where(
                NoteDeletionMember.operation_id == operation.id, NoteDeletionMember.user_id == owner
            )
        )
    )
    ids = [m.note_id for m in members]
    notes = list(
        db.scalars(
            select(PaperResearchNote)
            .where(PaperResearchNote.id.in_(ids), PaperResearchNote.user_id == owner)
            .execution_options(populate_existing=True)
        )
    )
    if len(notes) != len(members) or any(
        _sha(_content(db, n)) != next(m.content_sha256 for m in members if m.note_id == n.id)
        for n in notes
    ):
        raise DomainError(
            "NOTE_DELETION_CONTENT_CHANGED", "待删除笔记的原始内容已变化，未销毁数据库内容。", 409
        )
    jobs = {n.analysis_job_id for n in notes if n.analysis_job_id}
    canonicals = (
        list(
            db.scalars(
                select(CanonicalAnalyticalNote).where(
                    CanonicalAnalyticalNote.user_id == owner,
                    CanonicalAnalyticalNote.job_id.in_(jobs),
                )
            )
        )
        if jobs
        else []
    )
    attachments = list(
        db.scalars(
            select(Attachment).where(
                Attachment.user_id == owner,
                Attachment.id.in_([c.attachment_id for c in canonicals if c.attachment_id]),
            )
        )
    )
    trash_ids = list(
        db.scalars(
            select(NoteTrashEntry.id).where(
                NoteTrashEntry.user_id == owner,
                or_(NoteTrashEntry.note_id.in_(ids), exists_member_clause(ids)),
            )
        )
    )
    if dependency_blockers(db, owner, notes, canonicals, attachments, trash_ids):
        raise DomainError(
            "NOTE_DELETION_REFERENCES_CHANGED",
            "删除过程中出现新的引用，数据库内容未销毁，请核查。",
            409,
        )
    section_ids = list(
        db.scalars(select(ResearchNoteSection.id).where(ResearchNoteSection.note_id.in_(ids)))
    )
    inbox_ids = list(
        db.scalars(
            select(InboxItem.id).where(InboxItem.user_id == owner, InboxItem.note_id.in_(ids))
        )
    )
    db.execute(
        update(LiteratureIngestJob)
        .where(
            LiteratureIngestJob.user_id == owner, LiteratureIngestJob.inbox_item_id.in_(inbox_ids)
        )
        .values(inbox_item_id=None)
    )
    for model, clause in (
        (NoteTrashOperation, NoteTrashOperation.entry_id.in_(trash_ids)),
        (NoteTrashMember, NoteTrashMember.entry_id.in_(trash_ids)),
        (NoteTrashEntry, NoteTrashEntry.id.in_(trash_ids)),
        (InboxItem, InboxItem.id.in_(inbox_ids)),
        (NoteReviewAction, NoteReviewAction.note_id.in_(ids)),
        (ResearchNoteEvidence, ResearchNoteEvidence.section_id.in_(section_ids)),
        (ResearchNoteSection, ResearchNoteSection.id.in_(section_ids)),
        (PaperResearchNote, PaperResearchNote.id.in_(ids)),
        (EntityTag, EntityTag.entity_id.in_(ids)),
        (ResearchEntity, ResearchEntity.id.in_(ids)),
        (CanonicalAnalyticalNote, CanonicalAnalyticalNote.id.in_([c.id for c in canonicals])),
        (Attachment, Attachment.id.in_([a.id for a in attachments])),
        (AnalysisInputSnapshot, AnalysisInputSnapshot.job_id.in_(jobs)),
    ):
        db.execute(delete(model).where(clause).execution_options(synchronize_session=False))
    for part in db.scalars(
        select(PaperAnalysisPart).where(
            PaperAnalysisPart.user_id == owner, PaperAnalysisPart.job_id.in_(jobs)
        )
    ):
        part.request_payload, part.response_payload = {}, None
        part.error_code, part.error_message = (
            "NOTE_PERMANENTLY_DELETED",
            "精读内容已按本人选择永久删除。",
        )
    job_strings = {str(j) for j in jobs}
    part_strings = set(
        db.scalars(select(PaperAnalysisPart.id).where(PaperAnalysisPart.job_id.in_(jobs)))
    )
    for event in db.scalars(select(ResearchEvent).where(ResearchEvent.user_id == owner)):
        payload = event.payload
        if (
            event.correlation_id in jobs
            or str(payload.get("job_id")) in job_strings
            or str(payload.get("part_id")) in {str(p) for p in part_strings}
        ):
            redacted: dict[str, object] = {
                k: v
                for k, v in payload.items()
                if k in USAGE_KEYS and (v is None or isinstance(v, (str, int, float, bool)))
            }
            redacted["content_permanently_deleted"] = True
            event.payload = redacted
    for job in db.scalars(
        select(PaperAnalysisJob).where(
            PaperAnalysisJob.user_id == owner, PaperAnalysisJob.id.in_(jobs)
        )
    ):
        job.error_code, job.error_message = (
            "NOTE_PERMANENTLY_DELETED",
            "该次精读的生成内容已永久删除，不可恢复或重试。",
        )
        job.next_retry_at = None
    db.flush()


def exists_member_clause(ids: list[uuid.UUID]) -> ColumnElement[bool]:
    from sqlalchemy import exists

    return exists(
        select(NoteTrashMember.note_id).where(
            NoteTrashMember.entry_id == NoteTrashEntry.id, NoteTrashMember.note_id.in_(ids)
        )
    )
