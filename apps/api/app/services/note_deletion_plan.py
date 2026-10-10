"""Owner-scoped dependency and file manifest for irreversible note deletion."""

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.db import Base
from app.errors import DomainError
from app.models import (
    Attachment,
    CanonicalAnalyticalNote,
    NoteReviewAction,
    Paper,
    PaperAnalysisJob,
    PaperReadingApproval,
    PaperReadingApprovalPlan,
    PaperResearchNote,
    ResearchNoteEvidence,
    ResearchNoteSection,
)
from app.models_note_trash import NoteTrashEntry, NoteTrashMember
from app.providers import registry
from app.schemas_note_deletion import (
    NoteDeletionBlockerOut,
    NoteDeletionFileOut,
    NoteDeletionPreviewOut,
)
from app.schemas_note_trash import NoteTrashMemberOut
from app.services.note_trash import _content, _sha, settings_out


@dataclass
class DeletionPlan:
    preview: NoteDeletionPreviewOut
    notes: list[PaperResearchNote]
    canonicals: list[CanonicalAnalyticalNote]
    attachments: list[Attachment]
    trash_ids: list[uuid.UUID]
    files: list[dict[str, Any]]
    family_key: str


def family(db: Session, owner: uuid.UUID, target: uuid.UUID) -> list[PaperResearchNote]:
    note = db.scalar(
        select(PaperResearchNote).where(
            PaperResearchNote.id == target, PaperResearchNote.user_id == owner
        )
    )
    if note is None:
        raise DomainError("NOT_FOUND", "精读笔记不存在或已永久删除。", 404)
    if note.analysis_job_id:
        rows = list(
            db.scalars(
                select(PaperResearchNote)
                .where(
                    PaperResearchNote.user_id == owner,
                    PaperResearchNote.paper_id == note.paper_id,
                    PaperResearchNote.analysis_job_id == note.analysis_job_id,
                )
                .order_by(PaperResearchNote.revision)
                .execution_options(populate_existing=True)
            )
        )
    else:
        # Include the connected legacy revision family, without joining other papers.
        all_rows = list(
            db.scalars(
                select(PaperResearchNote)
                .where(
                    PaperResearchNote.user_id == owner, PaperResearchNote.paper_id == note.paper_id
                )
                .limit(1001)
            )
        )
        selected = {note.id}
        for _ in range(1001):
            old = len(selected)
            for row in all_rows:
                if row.id in selected and row.parent_note_id:
                    selected.add(row.parent_note_id)
                if row.parent_note_id in selected:
                    selected.add(row.id)
            if old == len(selected):
                break
        rows = sorted((n for n in all_rows if n.id in selected), key=lambda n: n.revision)
    if not rows or len(rows) > 1000:
        raise DomainError("NOTE_DELETION_BLOCKED", "精读版本范围超过安全上限。", 409)
    if any(n.user_id != owner or n.paper_id != note.paper_id for n in rows):
        raise DomainError("NOTE_DELETION_BLOCKED", "精读版本归属不一致。", 409)
    return rows


def dependency_blockers(
    db: Session,
    owner: uuid.UUID,
    notes: list[PaperResearchNote],
    canonicals: list[CanonicalAnalyticalNote],
    attachments: list[Attachment],
    trash_ids: list[uuid.UUID],
) -> list[NoteDeletionBlockerOut]:
    ids = {n.id for n in notes}
    canonical_ids = {n.id for n in canonicals}
    attachment_ids = {a.id for a in attachments}
    sections = set(
        db.scalars(select(ResearchNoteSection.id).where(ResearchNoteSection.note_id.in_(ids)))
    )
    targets = {
        "paper_research_notes": ids,
        "canonical_analytical_notes": canonical_ids,
        "research_entities": ids,
        "research_note_sections": sections,
        "attachments": attachment_ids,
        "note_trash_entries": set(trash_ids),
    }
    allowed = {
        "paper_research_notes",
        "research_note_sections",
        "research_note_evidence",
        "note_review_actions",
        "note_project_classifications",
        "note_projects",
        "inbox_items",
        "entity_tags",
        "note_trash_entries",
        "note_trash_members",
        "note_trash_operations",
        "canonical_analytical_notes",
        "literature_ingest_jobs",
    }
    messages = {
        "idea_sources": ("这篇精读已被科研灵感引用，关联资料保留，当前不能永久删除。", "/ideas"),
        "research_brief_canonical_sources": (
            "这篇精读已进入冻结任务书，需先处理对应课题资料。",
            "/projects",
        ),
        "claim_evidence": ("这篇精读被科研主张或稿件证据引用，不能连带删除其他资料。", "/projects"),
        "paper_reproduction_canonical_sources": (
            "这篇精读已进入复现准备资料，需先处理关联任务。",
            "/ai-tasks",
        ),
        "paper_reproduction_contexts": ("精读版本被既有复现准备上下文引用。", "/ai-tasks"),
    }
    found: set[str] = set()
    result: list[NoteDeletionBlockerOut] = []
    for table in Base.metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            for element in constraint.elements:
                values = targets.get(element.column.table.name)
                if element.column.name != "id" or not values:
                    continue
                query = select(func.count()).select_from(table).where(element.parent.in_(values))
                if table.name in allowed:
                    if table.name == "paper_research_notes":
                        query = query.where(table.c.id.not_in(ids))
                    elif table.name == "canonical_analytical_notes":
                        query = query.where(table.c.id.not_in(canonical_ids))
                    elif table.name == "note_trash_entries":
                        query = query.where(table.c.id.not_in(trash_ids))
                    elif table.name == "note_trash_members":
                        query = query.where(
                            or_(table.c.entry_id.not_in(trash_ids), table.c.note_id.not_in(ids))
                        )
                    else:
                        continue
                count = db.scalar(query) or 0
                if count and table.name not in found:
                    found.add(table.name)
                    message, href = messages.get(
                        table.name,
                        (
                            f"存在受保护的关联记录（{table.name}，{count}条），请先处理关联资料。",
                            None,
                        ),
                    )
                    result.append(
                        NoteDeletionBlockerOut(
                            code="REFERENCED_CONTENT", message=message, href=href
                        )
                    )
    for attachment in attachments:
        associated = [c for c in canonicals if c.attachment_id == attachment.id]
        if not associated or any(
            c.sha256 != attachment.sha256 or len(c.markdown.encode()) != attachment.size_bytes
            for c in associated
        ):
            result.append(
                NoteDeletionBlockerOut(
                    code="SOURCE_INVALID", message="笔记镜像身份与生成记录不一致，未授权删除。"
                )
            )
            continue
        if db.scalar(
            select(Attachment.id).where(
                Attachment.storage_provider == attachment.storage_provider,
                Attachment.object_key == attachment.object_key,
                Attachment.id.not_in(attachment_ids),
            )
        ):
            result.append(
                NoteDeletionBlockerOut(
                    code="SHARED_FILE", message="笔记镜像文件仍由其他附件记录使用。"
                )
            )
    return result


async def build_plan(db: Session, owner: uuid.UUID, target: uuid.UUID) -> DeletionPlan:
    if not settings_out(db, owner).enabled:
        raise DomainError("NOTE_DELETION_DISABLED", "请先在设置中开启生成内容删除。", 409)
    notes = family(db, owner, target)
    first = notes[0]
    jobs = {n.analysis_job_id for n in notes if n.analysis_job_id}
    canonicals = (
        list(
            db.scalars(
                select(CanonicalAnalyticalNote)
                .where(
                    CanonicalAnalyticalNote.user_id == owner,
                    CanonicalAnalyticalNote.job_id.in_(jobs),
                )
                .execution_options(populate_existing=True)
            )
        )
        if jobs
        else []
    )
    attachments = list(
        db.scalars(
            select(Attachment).where(
                Attachment.user_id == owner,
                Attachment.id.in_([n.attachment_id for n in canonicals if n.attachment_id]),
            )
        )
    )
    trash_ids = list(
        db.scalars(
            select(NoteTrashEntry.id).where(
                NoteTrashEntry.user_id == owner,
                or_(
                    NoteTrashEntry.note_id.in_([n.id for n in notes]),
                    exists(
                        select(NoteTrashMember.note_id).where(
                            NoteTrashMember.entry_id == NoteTrashEntry.id,
                            NoteTrashMember.note_id.in_([n.id for n in notes]),
                        )
                    ),
                ),
            )
        )
    )
    blockers = dependency_blockers(db, owner, notes, canonicals, attachments, trash_ids)
    if jobs and db.scalar(
        select(PaperAnalysisJob.id).where(
            PaperAnalysisJob.id.in_(jobs),
            PaperAnalysisJob.user_id == owner,
            PaperAnalysisJob.status.in_(["QUEUED", "ANALYZING", "RETRY_WAIT", "RUNNING"]),
        )
    ):
        blockers.append(
            NoteDeletionBlockerOut(
                code="NOTE_READING_ACTIVE",
                message="精读仍在运行，请先取消或等待结束。",
                href="/ai-tasks",
            )
        )
    if any(n.export_status == "SAVING" for n in canonicals):
        blockers.append(
            NoteDeletionBlockerOut(
                code="NOTE_PUBLICATION_ACTIVE",
                message="笔记文件正在保存，请待保存结束或核查结果后删除。",
            )
        )
    files: list[dict[str, Any]] = []
    file_out: list[NoteDeletionFileOut] = []
    seen: set[tuple[str, str]] = set()

    async def add_file(
        kind: str,
        root: str,
        path: str,
        sha: str,
        size: int = 0,
        storage_provider: str | None = None,
    ) -> None:
        key = (os.path.normcase(os.path.abspath(root)), os.path.normcase(path))
        if key in seen:
            return
        seen.add(key)
        try:
            provider = registry.generated_file_deletion_provider(
                root, "storage" if kind == "NOTE_MIRROR" else "markdown"
            )
            state = await asyncio.to_thread(provider.inspect, path)
            if state.exists and state.sha256 != sha:
                blockers.append(
                    NoteDeletionBlockerOut(
                        code="GENERATED_FILE_CHANGED",
                        message="生成文件已被修改，未删除该文件，请先核对："
                        + str(Path(root) / path),
                    )
                )
            size = state.size_bytes if state.exists else size
            file_out.append(
                NoteDeletionFileOut(
                    kind=kind,
                    path=str(Path(root) / path),
                    sha256=sha,
                    size_bytes=size,
                    exists=state.exists,
                )
            )
            files.append(
                {
                    "kind": kind,
                    "root_path": root,
                    "relative_path": path,
                    "storage_provider": storage_provider,
                    "sha256": sha,
                    "size_bytes": size,
                }
            )
        except DomainError as error:
            blockers.append(
                NoteDeletionBlockerOut(
                    code=error.code, message="无法安全核对生成文件：" + error.message
                )
            )

    selected_ids = {c.id for c in canonicals}
    for canonical in canonicals:
        plan = db.get(PaperReadingApprovalPlan, canonical.plan_id)
        approved = db.scalar(
            select(PaperReadingApproval.job_id).where(
                PaperReadingApproval.user_id == owner,
                PaperReadingApproval.job_id == canonical.job_id,
                PaperReadingApproval.plan_id == canonical.plan_id,
            )
        )
        bound_path = (
            os.path.normcase(os.path.abspath(str(Path(plan.output_root) / plan.output_path)))
            if plan
            else None
        )
        if (
            plan is None
            or plan.user_id != owner
            or approved is None
            or bound_path != os.path.normcase(os.path.abspath(canonical.output_path))
        ):
            blockers.append(
                NoteDeletionBlockerOut(code="SOURCE_INVALID", message="缺少可确认的文件生成来源。")
            )
            continue
        # Any other managed canonical sharing the path or revision hash blocks physical deletion.
        if db.scalar(
            select(CanonicalAnalyticalNote.id).where(
                CanonicalAnalyticalNote.id.not_in(selected_ids),
                or_(
                    CanonicalAnalyticalNote.output_path == canonical.output_path,
                    CanonicalAnalyticalNote.sha256 == canonical.sha256,
                ),
            )
        ):
            blockers.append(
                NoteDeletionBlockerOut(
                    code="SHARED_FILE",
                    message="生成路径或历史文件仍属于其他精读，请先处理共享精读。",
                )
            )
        await add_file(
            "NOTE_CURRENT",
            plan.output_root,
            plan.output_path,
            canonical.sha256,
            len(canonical.markdown.encode()),
        )
        await add_file(
            "NOTE_REVISION",
            plan.output_root,
            f".researchos-revisions/{canonical.sha256[:2]}/{canonical.sha256}.md",
            canonical.sha256,
        )
    for attachment in attachments:
        if attachment.mime_type != "text/plain" or attachment.storage_provider != "local":
            blockers.append(
                NoteDeletionBlockerOut(
                    code="FILE_PROVIDER_UNAVAILABLE",
                    message="此笔记镜像不属于可安全删除的本地文本存储。",
                )
            )
            continue
        root = registry.generated_storage_deletion_root()
        await add_file(
            "NOTE_MIRROR",
            root,
            attachment.object_key,
            attachment.sha256,
            attachment.size_bytes,
            attachment.storage_provider,
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
    paper = db.get(Paper, first.paper_id)
    facts = {
        "paper_title": paper.title if paper else "",
        "reviews": [
            (str(r.id), r.action, r.comment, str(r.reviewed_at))
            for r in db.scalars(
                select(NoteReviewAction)
                .where(NoteReviewAction.note_id.in_([n.id for n in notes]))
                .order_by(NoteReviewAction.id)
            )
        ],
        "evidence": [
            (str(e.id), e.evidence_text, e.locator)
            for e in db.scalars(
                select(ResearchNoteEvidence)
                .join(
                    ResearchNoteSection, ResearchNoteSection.id == ResearchNoteEvidence.section_id
                )
                .where(ResearchNoteSection.note_id.in_([n.id for n in notes]))
                .order_by(ResearchNoteEvidence.id)
            )
        ],
        "members": [m.model_dump(mode="json") for m in members],
        "notes": [
            {"id": str(n.id), "review": n.review_status, "updated": str(n.updated_at)}
            for n in notes
        ],
        "canonical": [
            {
                "id": str(c.id),
                "sha": c.sha256,
                "attachment": str(c.attachment_id),
                "export": c.export_status,
            }
            for c in canonicals
        ],
        "files": [f.model_dump(mode="json") for f in file_out],
        "blockers": [b.model_dump() for b in blockers],
    }
    preview = NoteDeletionPreviewOut(
        note_id=target,
        paper_id=first.paper_id,
        paper_title=paper.title if paper else "",
        reading_job_id=first.analysis_job_id,
        preview_sha256=_sha(facts),
        members=members,
        files=file_out,
        blockers=blockers,
        can_delete=not blockers,
    )
    family_key = (
        "job:" + str(first.analysis_job_id) if first.analysis_job_id else "note:" + str(first.id)
    )
    return DeletionPlan(preview, notes, canonicals, attachments, trash_ids, files, family_key)
