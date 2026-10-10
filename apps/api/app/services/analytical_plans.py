"""Freeze the original PDF, canonical skill and destination before owner consent."""

import asyncio
import hashlib
import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.analytical_notes import ReadingPlanOut, ReadingSourceFileOut
from app.domain.note_output import NoteOutputProvider
from app.domain.pdf_reading import PDFVisualProvider, ReadingSkillProvider
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.models_analytical import PaperReadingApprovalPlan
from app.providers.registry import (
    ai_provider_descriptor,
    note_output_provider,
    pdf_visual_provider,
    reading_skill_provider,
    storage_provider,
)
from app.services import reading_source_bindings
from app.services.paper_analysis import _payload_hash
from app.services.papers import get_paper
from app.services.pdf_reading import PDF_BATCH_PAGES, _attachment, _read_verified


def _component(value: str, *, title: bool = False) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if title:
        normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized).rstrip(". ")[:180]
    if (
        not normalized
        or normalized in {".", ".."}
        or normalized.endswith((".", " "))
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', normalized)
    ):
        raise DomainError("INVALID_COLLECTION", "Collection must be one safe directory name", 422)
    if normalized.split(".", 1)[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *[f"COM{i}" for i in range(1, 10)],
        *[f"LPT{i}" for i in range(1, 10)],
    }:
        raise DomainError("INVALID_COLLECTION", "Reserved directory/file name", 422)
    return normalized


def plan_payload(plan: PaperReadingApprovalPlan) -> dict[str, Any]:
    payload = {
        key: getattr(plan, key)
        for key in (
            "title",
            "paper_version",
            "sha256",
            "page_count",
            "collection",
            "model_key",
            "reasoning_effort",
            "skill_key",
            "skill_version",
            "skill_instructions",
            "skill_sha256",
            "template_text",
            "template_sha256",
            "render_version",
            "output_root",
            "output_path",
            "existing_file_sha256",
        )
    } | {
        "user_id": str(plan.user_id),
        "paper_id": str(plan.paper_id),
        "attachment_id": str(plan.attachment_id),
    }
    if plan.source_manifest_sha256 is not None:
        payload.update(
            source_manifest_sha256=plan.source_manifest_sha256,
            source_binding_version=plan.source_binding_version,
        )
    if plan.note_output_contract != "PAPER_ANALYSIS_V1":
        payload["note_output_contract"] = plan.note_output_contract
    return payload


def plan_out(plan: PaperReadingApprovalPlan, db: Session | None = None) -> ReadingPlanOut:
    return ReadingPlanOut(
        id=plan.id,
        paper_id=plan.paper_id,
        attachment_id=plan.attachment_id,
        title=plan.title,
        page_count=plan.page_count,
        sha256=plan.sha256,
        model_key=plan.model_key,
        reasoning_effort=plan.reasoning_effort,
        skill_key=plan.skill_key,
        skill_version=plan.skill_version,
        skill_sha256=plan.skill_sha256,
        template_sha256=plan.template_sha256,
        note_output_contract=plan.note_output_contract,
        output_root=plan.output_root,
        output_path=plan.output_path,
        existing_file_sha256=plan.existing_file_sha256,
        plan_sha256=plan.plan_sha256,
        created_at=plan.created_at,
        source_manifest_sha256=plan.source_manifest_sha256,
        source_binding_version=plan.source_binding_version,
        source_files=[
            ReadingSourceFileOut.model_validate(
                {
                    "path": row.path,
                    "role": row.role,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                }
            )
            for row in reading_source_bindings.sources(db, plan)
        ]
        if db is not None
        else [],
        writing_stage="WHOLE_PDF_WRITE_NOTE"
        if plan.page_count <= PDF_BATCH_PAGES
        else "READ_ALL_PAGES_THEN_WRITE_NOTE",
        page_batches=[
            {
                "part_index": index,
                "pages": list(range(start, min(plan.page_count + 1, start + PDF_BATCH_PAGES))),
            }
            for index, start in enumerate(range(1, plan.page_count + 1, PDF_BATCH_PAGES), 1)
        ],
    )


async def preview_reading_plan(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    collection: str,
    *,
    storage: StorageProvider | None = None,
    skills: ReadingSkillProvider | None = None,
    visual: PDFVisualProvider | None = None,
    output: NoteOutputProvider | None = None,
) -> PaperReadingApprovalPlan:
    paper = get_paper(db, user_id, paper_id)
    record = _attachment(db, user_id, paper_id, attachment_id)
    collection = _component(collection)
    relative_path = f"{collection}/{_component(paper.title, title=True)}.md"
    skill = await asyncio.to_thread((skills or reading_skill_provider()).load)
    if (
        skill.key != "zotero-analytical-writer"
        or not skill.template_text
        or not skill.template_sha256
        or hashlib.sha256(skill.template_text.encode()).hexdigest() != skill.template_sha256
        or hashlib.sha256(skill.instructions.encode()).hexdigest() != skill.sha256
    ):
        raise DomainError(
            "READING_SKILL_INVALID", "Canonical Analytical Writer/template receipt is invalid", 503
        )
    content = await _read_verified(
        record, storage or storage_provider(record.storage_provider), record.sha256
    )
    renderer = visual or pdf_visual_provider()
    count = await asyncio.to_thread(renderer.page_count, content, max_pages=None)
    if count < 1:
        raise DomainError("PDF_UNREADABLE", "Original PDF has no readable pages", 422)
    root = get_settings().analytical_note_root
    destination = output or note_output_provider(root)
    current = await asyncio.to_thread(destination.inspect, relative_path)
    plan = PaperReadingApprovalPlan(
        id=uuid.uuid4(),
        user_id=user_id,
        paper_id=paper_id,
        attachment_id=record.id,
        title=paper.title,
        paper_version=paper.version,
        sha256=record.sha256,
        page_count=count,
        collection=collection,
        model_key=ai_provider_descriptor().model_key
        or get_settings().codex_model
        or "unconfigured",
        reasoning_effort=get_settings().codex_reasoning_effort,
        skill_key=skill.key,
        skill_version=skill.version,
        skill_instructions=skill.instructions,
        skill_sha256=skill.sha256,
        template_text=skill.template_text,
        template_sha256=skill.template_sha256,
        note_output_contract="CANONICAL_MARKDOWN_V2",
        render_version=renderer.render_version,
        output_root=root,
        output_path=relative_path,
        existing_file_sha256=current.sha256,
        plan_sha256="",
    )
    db.add(plan)
    db.flush()
    reading_source_bindings.freeze(db, plan, skill.source_files)
    plan.plan_sha256 = _payload_hash(plan_payload(plan))
    db.commit()
    db.refresh(plan)
    return plan


async def approved_plan(
    db: Session,
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    plan_id: uuid.UUID,
    expected_sha256: str,
    *,
    output: NoteOutputProvider | None = None,
) -> PaperReadingApprovalPlan:
    plan = db.scalar(
        select(PaperReadingApprovalPlan).where(
            PaperReadingApprovalPlan.id == plan_id, PaperReadingApprovalPlan.user_id == user_id
        )
    )
    if plan is None or plan.paper_id != paper_id or plan.attachment_id != attachment_id:
        raise DomainError("NOT_FOUND", "Owned reading approval plan not found", 404)
    if plan.plan_sha256 != expected_sha256 or _payload_hash(plan_payload(plan)) != plan.plan_sha256:
        raise DomainError("READING_PLAN_CHANGED", "Approved reading plan hash changed", 409)
    reading_source_bindings.validate(plan, reading_source_bindings.sources(db, plan))
    if (
        plan.model_key
        != (ai_provider_descriptor().model_key or get_settings().codex_model or "unconfigured")
        or plan.reasoning_effort != get_settings().codex_reasoning_effort
    ):
        raise DomainError(
            "READING_PLAN_CHANGED", "Configured model/reasoning changed; approve a new plan", 409
        )
    paper = get_paper(db, user_id, paper_id)
    record = _attachment(db, user_id, paper_id, attachment_id)
    if (
        paper.version != plan.paper_version
        or paper.title != plan.title
        or record.sha256 != plan.sha256
    ):
        raise DomainError("READING_PLAN_CHANGED", "Paper/PDF changed after approval preview", 409)
    state = await asyncio.to_thread(
        (output or note_output_provider(plan.output_root)).inspect, plan.output_path
    )
    if state.sha256 != plan.existing_file_sha256:
        raise DomainError(
            "NOTE_OUTPUT_CHANGED", "Destination note changed after approval preview", 409
        )
    return plan
