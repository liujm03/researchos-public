"""Read-only checks of persisted note text and frozen local source records.

No provider, PDF, filesystem, model or human-review write is performed here.
Passing checks prove local consistency, not a paper's scientific conclusions.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.analytical_contract import validate_analytical_markdown
from app.errors import DomainError
from app.models import (
    AnalysisInputSnapshot,
    Attachment,
    InboxItem,
    NoteReviewAction,
    PaperResearchNote,
    ResearchNoteSection,
)
from app.models_analytical import CanonicalAnalyticalNote
from app.schemas_note_checks import NoteAutoCheckOut, NoteAutoReviewOut, NoteCheckStatus
from app.services import canonical_reproduction
from app.services.analysis_worker import _request_from_snapshot
from app.services.current_reading import uses_current_reading_skill


def automatic_note_review(
    db: Session, note: PaperResearchNote, sections: list[ResearchNoteSection]
) -> NoteAutoReviewOut:
    """Compute the current projection without changing stored review state."""
    with db.no_autoflush:
        return _automatic_note_review(db, note, sections)


def _automatic_note_review(
    db: Session, note: PaperResearchNote, sections: list[ResearchNoteSection]
) -> NoteAutoReviewOut:
    checks: list[NoteAutoCheckOut] = []

    def add(key: str, label: str, status: NoteCheckStatus, detail: str) -> None:
        checks.append(NoteAutoCheckOut(key=key, label=label, status=status, detail=detail))

    populated = [item for item in sections if (item.body_markdown or "").strip()]
    add(
        "content",
        "笔记内容",
        "PASSED" if populated else "ATTENTION",
        "已有可阅读的笔记正文。" if populated else "笔记正文为空，需检查生成结果。",
    )
    inbox = db.scalar(
        select(InboxItem).where(InboxItem.user_id == note.user_id, InboxItem.note_id == note.id)
    )
    rejected = (
        note.review_status == "REJECTED"
        or any(item.review_status == "REJECTED" for item in sections)
        or (inbox is not None and inbox.status == "REJECTED")
    )
    add(
        "recorded_decisions",
        "已有处理意见",
        "ATTENTION" if rejected else "PASSED",
        "存在本人拒绝的内容，请查看反馈。"
        if rejected
        else "未发现已记录的拒绝决定；保留原人工审核历史。",
    )
    canonical = (
        db.scalar(
            select(CanonicalAnalyticalNote).where(
                CanonicalAnalyticalNote.user_id == note.user_id,
                CanonicalAnalyticalNote.job_id == note.analysis_job_id,
            )
        )
        if note.analysis_job_id is not None
        else None
    )
    if canonical is None:
        add(
            "source_integrity",
            "原始精读来源",
            "UNAVAILABLE",
            "旧版或手工笔记缺少完整的批准精读记录，不能自动核对来源与原文哈希。",
        )
        return _result(checks)
    try:
        material = canonical_reproduction.material(db, note.user_id, note.paper_id, canonical.id)
    except DomainError:
        add(
            "source_integrity",
            "原始精读来源",
            "ATTENTION",
            "已保存的笔记、批准计划、完整页范围、任务或来源附件记录不一致，需核查。",
        )
        return _result(checks)

    add(
        "source_integrity",
        "原始精读来源",
        "PASSED",
        "笔记哈希、本人批准、冻结输入、完整页范围和来源附件元数据一致；未重新读取 PDF 文件。",
    )
    add(
        "skill_provenance",
        "技能与模板来源",
        "PASSED" if material.plan.source_manifest_sha256 else "UNAVAILABLE",
        "冻结技能与模板文件内容、清单和哈希一致。"
        if material.plan.source_manifest_sha256
        else "此历史任务仅保留技能指令，缺少实际文件闭包记录。",
    )
    current_contract = uses_current_reading_skill(db, material.job)
    add(
        "reading_contract",
        "精读接口",
        "PASSED" if current_contract else "UNAVAILABLE",
        "记录符合当前唯一技能精读接口。"
        if current_contract
        else "此历史记录不属于当前完整技能精读接口，不自动补认其完整性。",
    )
    analytical = [item for item in populated if item.section_key == "analytical_note"]
    exact = (
        len(populated) == len(analytical) == 1 and analytical[0].body_markdown == canonical.markdown
    )
    human_revision = _human_revision(db, note)
    if not exact and not human_revision:
        add(
            "canonical_text",
            "笔记版本",
            "ATTENTION",
            "当前正文是人工修订或与保存的原技能输出不同；原版保留，请按需核对改动。",
        )
    else:
        add(
            "canonical_text",
            "笔记版本",
            "PASSED",
            "当前正文与保存的完整技能 Markdown 原字节一致。"
            if exact
            else "本人编辑记录与原批准来源关联已保留；当前修订正文独立检查，不视为原技能输出。",
        )
    try:
        snapshot = db.get(AnalysisInputSnapshot, material.job.id)
        assert snapshot is not None  # Already checked by the DB-only material gate.
        identity = _request_from_snapshot(snapshot).writer_identity
        body = analytical[0].body_markdown if len(analytical) == 1 else None
        if body is None:
            raise ValueError("Canonical section unavailable")
        validate_analytical_markdown(body, material.plan.template_text, identity)
    except (DomainError, ValueError, TypeError, KeyError):
        add(
            "structure",
            "精读格式",
            "ATTENTION",
            "当前正文不满足已批准的精读模板结构或稳定身份字段。",
        )
    else:
        add("structure", "精读格式", "PASSED", "当前正文的模板字段、章节和结构通过本地检查。")
    mirror = (
        db.scalar(
            select(Attachment).where(
                Attachment.id == canonical.attachment_id,
                Attachment.user_id == note.user_id,
                Attachment.deleted_at.is_(None),
            )
        )
        if canonical.attachment_id
        else None
    )
    saved = (
        canonical.export_status == "SAVED"
        and mirror is not None
        and mirror.sha256 == canonical.sha256
        and mirror.size_bytes == len(canonical.markdown.encode("utf-8"))
    )
    add(
        "saved_output",
        "保存记录",
        "PASSED" if saved else "ATTENTION",
        "已有成功保存回执与一致的备份附件元数据；未重新读取磁盘文件。"
        if saved
        else "笔记正文可阅读，但保存或备份记录未完成或存在异常，可查看保存详情。",
    )
    return _result(checks)


def _human_revision(db: Session, note: PaperResearchNote) -> bool:
    if note.parent_note_id is None or note.created_by != "AI_USER_EDITED":
        return False
    parent = db.scalar(
        select(PaperResearchNote).where(
            PaperResearchNote.id == note.parent_note_id,
            PaperResearchNote.user_id == note.user_id,
            PaperResearchNote.paper_id == note.paper_id,
            PaperResearchNote.analysis_job_id == note.analysis_job_id,
            PaperResearchNote.revision < note.revision,
        )
    )
    action = db.scalar(
        select(NoteReviewAction.id).where(
            NoteReviewAction.note_id == note.id,
            NoteReviewAction.reviewer_id == note.user_id,
            NoteReviewAction.reviewed_revision == note.revision,
            NoteReviewAction.action == "EDIT",
        )
    )
    return parent is not None and action is not None


def _result(checks: list[NoteAutoCheckOut]) -> NoteAutoReviewOut:
    status: NoteCheckStatus = (
        "ATTENTION"
        if any(item.status == "ATTENTION" for item in checks)
        else "UNAVAILABLE"
        if any(item.status == "UNAVAILABLE" for item in checks)
        else "PASSED"
    )
    labels = {
        "PASSED": "自动检查完成",
        "ATTENTION": "自动检查需注意",
        "UNAVAILABLE": "自动检查记录不足",
    }
    return NoteAutoReviewOut(status=status, label=labels[status], checks=checks)
