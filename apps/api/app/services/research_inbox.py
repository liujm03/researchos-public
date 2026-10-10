import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import (
    InboxItem,
    NoteReviewAction,
    Paper,
    PaperResearchNote,
    ResearchEntity,
    ResearchNoteEvidence,
    ResearchNoteSection,
)
from app.services.common import register_entity


def get_note(
    db: Session, user_id: uuid.UUID, note_id: uuid.UUID, *, lock: bool = False
) -> PaperResearchNote:
    if lock:
        paper_id = db.scalar(
            select(PaperResearchNote.paper_id).where(
                PaperResearchNote.id == note_id, PaperResearchNote.user_id == user_id
            )
        )
        if paper_id:
            db.scalar(
                select(Paper.id)
                .where(Paper.id == paper_id, Paper.user_id == user_id)
                .with_for_update()
            )
    note = db.scalar(
        select(PaperResearchNote)
        .join(
            ResearchEntity,
            (ResearchEntity.id == PaperResearchNote.id) & (ResearchEntity.user_id == user_id),
        )
        .where(
            PaperResearchNote.id == note_id,
            PaperResearchNote.user_id == user_id,
            ResearchEntity.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if note is None:
        raise DomainError("NOT_FOUND", "Research note not found", 404)
    return note


def sections_for_note(db: Session, note_id: uuid.UUID) -> list[ResearchNoteSection]:
    return list(
        db.scalars(
            select(ResearchNoteSection)
            .where(ResearchNoteSection.note_id == note_id)
            .order_by(ResearchNoteSection.section_key)
        )
    )


def review_section(
    db: Session,
    user_id: uuid.UUID,
    note_id: uuid.UUID,
    section_key: str,
    action: str,
    *,
    comment: str | None = None,
    edited_body: str | None = None,
) -> PaperResearchNote:
    note = get_note(db, user_id, note_id, lock=True)
    section = db.scalar(
        select(ResearchNoteSection).where(
            ResearchNoteSection.note_id == note_id,
            ResearchNoteSection.section_key == section_key,
        )
    )
    if section is None:
        raise DomainError("NOT_FOUND", "Research note section not found", 404)
    if action in {"REJECT", "COMMENT"} and not comment:
        raise DomainError("VALIDATION_ERROR", "A reason or comment is required", 422)
    if action == "EDIT":
        if edited_body is None or not edited_body.strip():
            raise DomainError("VALIDATION_ERROR", "Edited text is required", 422)
        return _create_edited_revision(db, user_id, note, section_key, edited_body, comment)
    if action == "CONFIRM":
        section.review_status = "VERIFIED"
    elif action == "REJECT":
        section.review_status = "REJECTED"
    elif action != "COMMENT":
        raise DomainError("VALIDATION_ERROR", "Unknown review action", 422)
    if action != "COMMENT":
        note.review_status = "REVIEWING"
        note.updated_at = datetime.now(UTC)
    db.add(
        NoteReviewAction(
            id=uuid.uuid4(),
            note_id=note_id,
            section_id=section.id,
            reviewer_id=user_id,
            action=action,
            comment=comment,
            reviewed_revision=note.revision,
        )
    )
    inbox = db.scalar(select(InboxItem).where(InboxItem.note_id == note_id))
    if inbox and action != "COMMENT" and inbox.status == "PENDING":
        inbox.status = "REVIEWING"
    db.commit()
    db.refresh(note)
    return note


def verify_note(db: Session, user_id: uuid.UUID, note_id: uuid.UUID) -> PaperResearchNote:
    note = get_note(db, user_id, note_id, lock=True)
    reviewed = sections_for_note(db, note_id)
    content_sections = [item for item in reviewed if item.body_markdown]
    if not content_sections or any(item.review_status != "VERIFIED" for item in content_sections):
        raise DomainError("CONFLICT", "Every populated section must be confirmed", 409)
    note.review_status = "VERIFIED"
    note.updated_at = datetime.now(UTC)
    db.add(
        NoteReviewAction(
            id=uuid.uuid4(),
            note_id=note_id,
            reviewer_id=user_id,
            action="VERIFY_NOTE",
            reviewed_revision=note.revision,
        )
    )
    db.commit()
    db.refresh(note)
    return note


def _create_edited_revision(
    db: Session,
    user_id: uuid.UUID,
    old_note: PaperResearchNote,
    section_key: str,
    edited_body: str,
    comment: str | None,
) -> PaperResearchNote:
    revision = (
        db.scalar(
            select(func.max(PaperResearchNote.revision)).where(
                PaperResearchNote.paper_id == old_note.paper_id
            )
        )
        or 0
    ) + 1
    note_id = register_entity(db, user_id, "research_note")
    new_note = PaperResearchNote(
        id=note_id,
        user_id=user_id,
        paper_id=old_note.paper_id,
        analysis_job_id=old_note.analysis_job_id,
        parent_note_id=old_note.id,
        revision=revision,
        summary=old_note.summary,
        analysis_scope=old_note.analysis_scope,
        analysis_mode=old_note.analysis_mode,
        created_by="AI_USER_EDITED",
        review_status="REVIEWING",
    )
    db.add(new_note)
    db.flush()  # PostgreSQL enforces note parents before section/inbox FK inserts.
    for previous in sections_for_note(db, old_note.id):
        new_section_id = uuid.uuid4()
        is_edited = previous.section_key == section_key
        db.add(
            ResearchNoteSection(
                id=new_section_id,
                note_id=note_id,
                section_key=previous.section_key,
                body_markdown=edited_body if is_edited else previous.body_markdown,
                origin_type=previous.origin_type,
                review_status="UNREVIEWED" if is_edited else previous.review_status,
                uncertainty=previous.uncertainty,
            )
        )
        db.flush()  # Evidence and review actions reference this actual section.
        for evidence in db.scalars(
            select(ResearchNoteEvidence).where(ResearchNoteEvidence.section_id == previous.id)
        ):
            db.add(
                ResearchNoteEvidence(
                    id=uuid.uuid4(),
                    section_id=new_section_id,
                    claim_type=evidence.claim_type,
                    source_section=evidence.source_section,
                    source_page=evidence.source_page,
                    source_block_id=evidence.source_block_id,
                    evidence_text=evidence.evidence_text,
                    locator=evidence.locator,
                )
            )
        if is_edited:
            db.add(
                NoteReviewAction(
                    id=uuid.uuid4(),
                    note_id=note_id,
                    section_id=new_section_id,
                    reviewer_id=user_id,
                    action="EDIT",
                    comment=comment,
                    reviewed_revision=revision,
                )
            )
    old_inbox = db.scalar(select(InboxItem).where(InboxItem.note_id == old_note.id))
    if old_inbox and old_inbox.status in {"PENDING", "REVIEWING"}:
        old_inbox.status = "SUPERSEDED"
    db.add(
        InboxItem(
            id=uuid.uuid4(), user_id=user_id, item_type="AI_NOTE", note_id=note_id, status="PENDING"
        )
    )
    db.commit()
    db.refresh(new_note)
    return new_note


def decide_inbox(
    db: Session,
    user_id: uuid.UUID,
    inbox_id: uuid.UUID,
    action: str,
    comment: str | None = None,
) -> InboxItem:
    inbox = db.scalar(
        select(InboxItem).where(InboxItem.id == inbox_id, InboxItem.user_id == user_id)
    )
    if inbox is None:
        raise DomainError("NOT_FOUND", "Inbox item not found", 404)
    if inbox.status in {"ACCEPTED", "REJECTED", "SUPERSEDED"}:
        raise DomainError("CONFLICT", "Inbox item is already finalized", 409)
    note = get_note(db, user_id, inbox.note_id, lock=True)
    if action == "ACCEPT":
        if note.review_status != "VERIFIED":
            raise DomainError("CONFLICT", "Review every populated section before accepting", 409)
        inbox.status = "ACCEPTED"
    elif action == "REJECT":
        if not comment:
            raise DomainError("VALIDATION_ERROR", "A rejection reason is required", 422)
        inbox.status = "REJECTED"
        note.review_status = "REJECTED"
        db.add(
            NoteReviewAction(
                id=uuid.uuid4(),
                note_id=note.id,
                reviewer_id=user_id,
                action="REJECT_NOTE",
                comment=comment,
                reviewed_revision=note.revision,
            )
        )
    else:
        raise DomainError("VALIDATION_ERROR", "Unknown inbox decision", 422)
    inbox.reviewer_id = user_id
    inbox.reviewed_at = datetime.now(UTC)
    db.commit()
    db.refresh(inbox)
    return inbox
