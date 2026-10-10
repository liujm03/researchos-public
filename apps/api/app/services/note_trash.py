"""Transactional reversible removal from normal note views; no file IO or AI."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.errors import DomainError
from app.models import (
    CanonicalAnalyticalNote,
    InboxItem,
    NoteReviewAction,
    Paper,
    PaperAnalysisJob,
    PaperResearchNote,
    ResearchEntity,
    ResearchNoteSection,
    User,
)
from app.models_note_trash import (
    GeneratedFileSettings,
    NoteTrashEntry,
    NoteTrashMember,
    NoteTrashOperation,
)
from app.schemas_note_trash import (
    GeneratedFileSettingsOut,
    GeneratedFileSettingsPatch,
    NoteDeleteScope,
    NoteTrashEntryOut,
    NoteTrashMemberOut,
    NoteTrashPreviewOut,
    NoteTrashRequest,
    NoteTrashRestoreRequest,
)
from app.services.note_deletion_state import (
    require_not_permanently_deleted,
    selectable_deletion_clause,
)


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def selectable_job_clause(owner: uuid.UUID, job_id_column: Any = None) -> ColumnElement[bool]:
    """Historical no-note jobs stay visible; all-trashed families are hidden."""
    if job_id_column is None:
        job_id_column = CanonicalAnalyticalNote.job_id
    n, e = aliased(PaperResearchNote), aliased(ResearchEntity)
    any_note = exists(select(n.id).where(n.user_id == owner, n.analysis_job_id == job_id_column))
    visible = exists(
        select(n.id)
        .join(e, (e.id == n.id) & (e.user_id == owner))
        .where(n.user_id == owner, n.analysis_job_id == job_id_column, e.deleted_at.is_(None))
    )
    return selectable_deletion_clause(owner, job_id_column) & (~any_note | visible)


def job_fully_trashed(db: Session, owner: uuid.UUID, job_id: uuid.UUID) -> bool:
    return not bool(db.scalar(select(selectable_job_clause(owner, job_id))))


def require_selectable_job(db: Session, owner: uuid.UUID, job_id: uuid.UUID) -> None:
    require_not_permanently_deleted(db, owner, job_id)
    if job_fully_trashed(db, owner, job_id):
        raise DomainError(
            "NOTE_TRASHED", "Restore this reading's notes before selecting or publishing them", 409
        )


def settings_out(db: Session, owner: uuid.UUID) -> GeneratedFileSettingsOut:
    row = db.get(GeneratedFileSettings, owner)
    return GeneratedFileSettingsOut.model_validate(
        {
            "enabled": row.enabled if row else True,
            "note_delete_scope": "READING_RUN",
        }
    )


def patch_settings(
    db: Session, owner: uuid.UUID, body: GeneratedFileSettingsPatch
) -> GeneratedFileSettingsOut:
    changes = body.model_dump(exclude_unset=True)
    if changes.get("note_delete_scope") not in {None, "READING_RUN"}:
        raise DomainError("NOTE_DELETION_SCOPE_RETIRED", "永久删除按本次精读所有版本处理，不支持只隐藏单版本。", 422)
    if any(v is None for v in changes.values()):
        raise DomainError("VALIDATION_ERROR", "Deletion settings cannot be null", 422)
    db.scalar(select(User).where(User.id == owner).with_for_update())
    row = db.get(GeneratedFileSettings, owner)
    if row is None:
        row = GeneratedFileSettings(user_id=owner)
        db.add(row)
    for name, value in changes.items():
        setattr(row, name, value)
    db.commit()
    return settings_out(db, owner)


def _target(
    db: Session, owner: uuid.UUID, note_id: uuid.UUID, *, lock: bool = False
) -> PaperResearchNote:
    note = db.scalar(
        select(PaperResearchNote).where(
            PaperResearchNote.id == note_id, PaperResearchNote.user_id == owner
        )
    )
    if note is None:
        raise DomainError("NOT_FOUND", "Research note not found", 404)
    if lock:
        db.scalar(
            select(Paper).where(Paper.id == note.paper_id, Paper.user_id == owner).with_for_update()
        )
    entity = db.scalar(
        select(ResearchEntity)
        .where(
            ResearchEntity.id == note_id,
            ResearchEntity.user_id == owner,
            ResearchEntity.kind == "research_note",
        )
        .execution_options(populate_existing=True)
    )
    if entity is None:
        raise DomainError("NOT_FOUND", "Research note not found", 404)
    if entity.deleted_at is not None:
        raise DomainError("NOTE_TRASHED", "Research note is in the recycle bin", 409)
    return note


def _family(
    db: Session, owner: uuid.UUID, note: PaperResearchNote, scope: NoteDeleteScope
) -> list[PaperResearchNote]:
    query = (
        select(PaperResearchNote)
        .join(
            ResearchEntity,
            (ResearchEntity.id == PaperResearchNote.id) & (ResearchEntity.user_id == owner),
        )
        .where(
            PaperResearchNote.user_id == owner,
            PaperResearchNote.paper_id == note.paper_id,
            ResearchEntity.deleted_at.is_(None),
        )
    )
    query = (
        query.where(PaperResearchNote.analysis_job_id == note.analysis_job_id)
        if scope == "READING_RUN" and note.analysis_job_id
        else query.where(PaperResearchNote.id == note.id)
    )
    rows = list(db.scalars(query.order_by(PaperResearchNote.revision)))
    if len(rows) > 1000:
        raise DomainError(
            "NOTE_TRASH_TOO_LARGE", "Use a single-version deletion for this reading", 409
        )
    return rows


def _idle(db: Session, owner: uuid.UUID, notes: list[PaperResearchNote]) -> None:
    jobs = {n.analysis_job_id for n in notes if n.analysis_job_id}
    if not jobs:
        return
    active = db.scalar(
        select(PaperAnalysisJob.id).where(
            PaperAnalysisJob.user_id == owner,
            PaperAnalysisJob.id.in_(jobs),
            PaperAnalysisJob.status.in_(["QUEUED", "ANALYZING", "RETRY_WAIT", "RUNNING"]),
        )
    )
    if active:
        raise DomainError(
            "NOTE_READING_ACTIVE",
            "Wait for or cancel the active reading before recycling its notes",
            409,
        )
    publishing = db.scalar(
        select(CanonicalAnalyticalNote.id).where(
            CanonicalAnalyticalNote.user_id == owner,
            CanonicalAnalyticalNote.job_id.in_(jobs),
            CanonicalAnalyticalNote.export_status == "SAVING",
        )
    )
    if publishing:
        raise DomainError(
            "NOTE_PUBLICATION_ACTIVE",
            "Finish or recover the active note save before recycling",
            409,
        )


def _content(db: Session, note: PaperResearchNote) -> dict[str, object]:
    sections = list(
        db.scalars(
            select(ResearchNoteSection)
            .where(ResearchNoteSection.note_id == note.id)
            .order_by(ResearchNoteSection.section_key)
        )
    )
    return {
        "summary": note.summary,
        "sections": [
            {
                "key": s.section_key,
                "body": s.body_markdown,
                "origin": s.origin_type,
                "review": s.review_status,
                "uncertainty": s.uncertainty,
            }
            for s in sections
        ],
    }


def _references(
    db: Session,
    owner: uuid.UUID,
    notes: list[PaperResearchNote],
    canonicals: list[CanonicalAnalyticalNote],
) -> list[dict[str, object]]:
    from app.models import PaperReproductionContext
    from app.models_claims import ClaimEvidence
    from app.models_ideas import IdeaSource
    from app.models_reproduction_sources import PaperReproductionCanonicalSource
    from app.models_research_briefs import ResearchBriefCanonicalSource

    ids = [n.id for n in canonicals]
    refs: list[dict[str, object]] = []
    for kind, model in (
        ("Idea", IdeaSource),
        ("Research brief", ResearchBriefCanonicalSource),
        ("Research claim", ClaimEvidence),
        ("Reproduction source", PaperReproductionCanonicalSource),
    ):
        count = (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.user_id == owner, model.canonical_note_id.in_(ids))
            )
            if ids
            else 0
        )
        if count:
            refs.append({"kind": kind, "count": count})
    count = db.scalar(
        select(func.count())
        .select_from(PaperReproductionContext)
        .where(
            PaperReproductionContext.user_id == owner,
            PaperReproductionContext.note_id.in_([n.id for n in notes]),
        )
    )
    if count:
        refs.append({"kind": "Reproduction context", "count": count})
    return refs


def preview(
    db: Session, owner: uuid.UUID, note_id: uuid.UUID, scope: NoteDeleteScope | None = None
) -> NoteTrashPreviewOut:
    if not settings_out(db, owner).enabled:
        raise DomainError(
            "NOTE_DELETION_DISABLED", "Enable generated-note deletion in settings first", 409
        )
    note = _target(db, owner, note_id)
    selected_scope: NoteDeleteScope = scope or settings_out(db, owner).note_delete_scope
    notes = _family(db, owner, note, selected_scope)
    _idle(db, owner, notes)
    paper = db.get(Paper, note.paper_id)
    jobs = {n.analysis_job_id for n in notes if n.analysis_job_id}
    canonicals = (
        list(
            db.scalars(
                select(CanonicalAnalyticalNote)
                .where(
                    CanonicalAnalyticalNote.user_id == owner,
                    CanonicalAnalyticalNote.job_id.in_(jobs),
                )
                .order_by(CanonicalAnalyticalNote.id)
                .execution_options(populate_existing=True)
            )
        )
        if jobs
        else []
    )
    members = [
        NoteTrashMemberOut(
            note_id=n.id,
            revision=n.revision,
            created_by=n.created_by,
            content_sha256=_sha(_content(db, n)),
        )
        for n in notes
    ]
    payload = {
        "note_id": note.id,
        "paper_id": note.paper_id,
        "paper_title": paper.title if paper else "",
        "scope": selected_scope,
        "members": [m.model_dump(mode="json") for m in members],
        "file_paths": sorted({c.output_path for c in canonicals}),
        "reference_counts": _references(db, owner, notes, canonicals),
        "warnings": [
            "移入回收站只隐藏系统笔记；原文 PDF、Zotero、外部 Markdown 与附件保留，不释放磁盘空间。",
            "已有课题、Idea 和稿件的固定来源引用保留，恢复后可再次选择。",
        ],
        "file_disposition": "PRESERVED",
        "reclaims_disk_space": False,
    }
    # Include review/inbox/source facts in optimistic preview without changing them.
    facts = {
        "payload": payload,
        "notes": [
            {"id": n.id, "review": n.review_status, "updated_at": n.updated_at} for n in notes
        ],
        "reviews": [
            (r.id, r.action, r.comment)
            for r in db.scalars(
                select(NoteReviewAction)
                .where(NoteReviewAction.note_id.in_([n.id for n in notes]))
                .order_by(NoteReviewAction.id)
            )
        ],
        "inbox": [
            (i.id, i.status)
            for i in db.scalars(
                select(InboxItem)
                .where(InboxItem.user_id == owner, InboxItem.note_id.in_([n.id for n in notes]))
                .order_by(InboxItem.id)
            )
        ],
        "canonical": [
            {"id": c.id, "sha": c.sha256, "status": c.export_status, "attachment": c.attachment_id}
            for c in canonicals
        ],
    }
    return NoteTrashPreviewOut.model_validate(payload | {"preview_sha256": _sha(facts)})


def get_entry(db: Session, owner: uuid.UUID, entry_id: uuid.UUID) -> NoteTrashEntry:
    entry = db.scalar(
        select(NoteTrashEntry).where(NoteTrashEntry.id == entry_id, NoteTrashEntry.user_id == owner)
    )
    if entry is None:
        raise DomainError("NOT_FOUND", "Recycle-bin entry not found", 404)
    return entry


def entry_out(entry: NoteTrashEntry) -> NoteTrashEntryOut:
    return NoteTrashEntryOut.model_validate(
        entry.preview_payload
        | {
            "id": entry.id,
            "state": entry.state,
            "version": entry.version,
            "idempotency_key": entry.idempotency_key,
            "created_at": entry.created_at,
            "restored_at": entry.restored_at,
        }
    )


def lookup(db: Session, owner: uuid.UUID, key: str) -> NoteTrashEntry:
    operation = db.scalar(
        select(NoteTrashOperation).where(
            NoteTrashOperation.user_id == owner, NoteTrashOperation.idempotency_key == key
        )
    )
    if operation is None:
        raise DomainError(
            "NOT_FOUND", "No completed recycle-bin operation exists for this key", 404
        )
    return get_entry(db, owner, operation.entry_id)


def _replay(
    db: Session, owner: uuid.UUID, key: str, kind: str, request_sha: str
) -> NoteTrashEntry | None:
    operation = db.scalar(
        select(NoteTrashOperation).where(
            NoteTrashOperation.user_id == owner, NoteTrashOperation.idempotency_key == key
        )
    )
    if operation is None:
        return None
    if operation.kind != kind or operation.request_sha256 != request_sha:
        raise DomainError(
            "IDEMPOTENCY_CONFLICT", "This operation key was used with a different request", 409
        )
    return get_entry(db, owner, operation.entry_id)


def trash(
    db: Session, owner: uuid.UUID, note_id: uuid.UUID, body: NoteTrashRequest
) -> NoteTrashEntry:
    request_sha = _sha({"note_id": note_id, **body.model_dump()})
    existing = _replay(db, owner, body.idempotency_key, "TRASH", request_sha)
    if existing:
        return existing
    # Use the same global ordering as analysis admission: owner, paper, output.
    db.scalar(select(User).where(User.id == owner).with_for_update())
    target = _target(db, owner, note_id, lock=True)
    if target.analysis_job_id:
        # Serialize with the publisher's conditional UPDATE lease claim. After
        # waiting, preview reads its fresh status and rejects an active save.
        db.scalars(
            select(CanonicalAnalyticalNote)
            .where(
                CanonicalAnalyticalNote.user_id == owner,
                CanonicalAnalyticalNote.job_id == target.analysis_job_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    existing = _replay(db, owner, body.idempotency_key, "TRASH", request_sha)
    if existing:
        return existing
    plan = preview(db, owner, note_id, body.scope)
    if plan.preview_sha256 != body.expected_preview_sha256:
        raise DomainError(
            "NOTE_TRASH_PREVIEW_CHANGED",
            "The notes or references changed; preview the deletion again",
            409,
        )
    now = datetime.now(UTC)
    entry = NoteTrashEntry(
        id=uuid.uuid4(),
        user_id=owner,
        note_id=note_id,
        paper_id=plan.paper_id,
        scope=body.scope,
        state="TRASHED",
        version=1,
        preview_sha256=plan.preview_sha256,
        request_sha256=request_sha,
        idempotency_key=body.idempotency_key,
        preview_payload=plan.model_dump(mode="json"),
        created_at=now,
    )
    db.add(entry)
    db.flush()
    for member in plan.members:
        changed = db.scalar(
            update(ResearchEntity)
            .where(
                ResearchEntity.id == member.note_id,
                ResearchEntity.user_id == owner,
                ResearchEntity.deleted_at.is_(None),
            )
            .values(deleted_at=now)
            .returning(ResearchEntity.id)
        )
        if changed is None:
            db.rollback()
            raise DomainError(
                "NOTE_TRASH_CONFLICT", "A note changed during deletion; preview again", 409
            )
        db.add(
            NoteTrashMember(
                entry_id=entry.id,
                note_id=member.note_id,
                user_id=owner,
                revision=member.revision,
                created_by=member.created_by,
                content_sha256=member.content_sha256,
                deleted_at=now,
            )
        )
    db.add(
        NoteTrashOperation(
            entry_id=entry.id,
            user_id=owner,
            kind="TRASH",
            idempotency_key=body.idempotency_key,
            request_sha256=request_sha,
        )
    )
    db.commit()
    return entry


def restore(
    db: Session, owner: uuid.UUID, entry_id: uuid.UUID, body: NoteTrashRestoreRequest
) -> NoteTrashEntry:
    request_sha = _sha({"entry_id": entry_id, **body.model_dump()})
    existing = _replay(db, owner, body.idempotency_key, "RESTORE", request_sha)
    if existing:
        return existing
    entry = get_entry(db, owner, entry_id)
    db.scalar(select(User).where(User.id == owner).with_for_update())
    db.scalar(
        select(Paper).where(Paper.id == entry.paper_id, Paper.user_id == owner).with_for_update()
    )
    existing = _replay(db, owner, body.idempotency_key, "RESTORE", request_sha)
    if existing:
        return existing
    db.refresh(entry)
    if entry.state != "TRASHED" or entry.version != body.expected_version:
        raise DomainError(
            "NOTE_TRASH_VERSION_CHANGED", "Recycle-bin state changed; reload before restoring", 409
        )
    members = list(
        db.scalars(
            select(NoteTrashMember).where(
                NoteTrashMember.entry_id == entry.id, NoteTrashMember.user_id == owner
            )
        )
    )
    for member in members:
        note = db.get(PaperResearchNote, member.note_id)
        if note is not None and note.analysis_job_id is not None:
            require_not_permanently_deleted(db, owner, note.analysis_job_id)
    for member in members:
        changed = db.scalar(
            update(ResearchEntity)
            .where(
                ResearchEntity.id == member.note_id,
                ResearchEntity.user_id == owner,
                ResearchEntity.deleted_at == member.deleted_at,
            )
            .values(deleted_at=None)
            .returning(ResearchEntity.id)
        )
        if changed is None:
            db.rollback()
            raise DomainError(
                "NOTE_RESTORE_CONFLICT",
                "A note has a different deletion marker; no notes were restored",
                409,
            )
    entry.state, entry.version, entry.restored_at = "RESTORED", entry.version + 1, datetime.now(UTC)
    db.add(
        NoteTrashOperation(
            entry_id=entry.id,
            user_id=owner,
            kind="RESTORE",
            idempotency_key=body.idempotency_key,
            request_sha256=request_sha,
        )
    )
    db.commit()
    return entry
