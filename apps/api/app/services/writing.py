"""Professional original Markdown candidates; explicit owner adoption only."""

import hashlib
import json
import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.writing_skills import PROFILES
from app.errors import DomainError
from app.models import AnalysisSettings, CodexTask, Task
from app.models_writing import WritingCandidate, WritingOperation, WritingPlan, WritingSkillFile
from app.providers import registry
from app.schemas_codex_tasks import CodexTaskOut
from app.schemas_publications import PublicationPreview, PublicationRevise
from app.schemas_writing import (
    WritingAdopt,
    WritingAdoptionOut,
    WritingAdoptionSelection,
    WritingCandidateOut,
    WritingCreate,
    WritingImport,
    WritingIssueCreate,
    WritingIssueOut,
    WritingOptions,
    WritingPlanOut,
    WritingPreview,
    WritingProfileOut,
    WritingSelection,
    WritingSkillFileOut,
    WritingStart,
    WritingStyleOut,
)
from app.services import codex_tasks, evidence_bundles, publications
from app.services.claims import fail as fail
from app.services.common import register_entity
from app.services.research_briefs import digest


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def permission(db: Session, owner: uuid.UUID) -> None:
    if not get_settings().writing_enabled:
        raise fail("WRITING_DISABLED", "Professional writing is disabled on this host", 503)
    setting = db.scalar(
        select(AnalysisSettings)
        .where(AnalysisSettings.user_id == owner)
        .execution_options(populate_existing=True)
    )
    if setting is None or setting.cloud_scope != "FULL_TEXT":
        raise fail(
            "WRITING_FULLTEXT_PERMISSION_REQUIRED",
            "Writing derived manuscript/evidence requires current FULL_TEXT permission",
        )


def options() -> WritingOptions:
    settings = get_settings()
    styles = []
    for key, label in (
        ("GENERIC", "通用英文稿"),
        ("IEEE", "IEEE专业英文写作"),
        ("ELSEVIER", "Elsevier英文写作"),
        ("CVPR", "CVPR英文写作"),
    ):
        available = False
        style_detail = "专业表达指导；具体官方模板/投稿合规需另行核验。"
        if settings.writing_enabled:
            try:
                registry.writing_skill_provider().load(
                    "research-paper-writing", "proposed_method", venue_style=key
                )
                available = True
            except DomainError:
                style_detail = "实际专业Skill文件闭包尚未就绪；不能只凭风格名称启动。"
        styles.append(
            WritingStyleOut(key=key, label=label, available=available, detail=style_detail)
        )
    return WritingOptions(
        enabled=settings.writing_enabled,
        profiles=[WritingProfileOut(key=k, label=k, targets=list(v)) for k, v in PROFILES.items()],
        model_key=settings.codex_model,
        reasoning_effort=settings.codex_reasoning_effort,
        detail="稿件统一英文，风格绑定实际专业Skill；预览保存不调用AI，单独启动才输出原Markdown候选。风格指导不证明投稿模板合规。",
        styles=styles,
    )


def prepare(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    publication: uuid.UUID,
    selection: WritingSelection,
) -> tuple[WritingPreview, str]:
    permission(db, owner)
    parent = publications.get(db, owner, project, publication)
    rev = publications.revision(db, parent, selection.revision_id)
    detail = publications.revision_out(db, rev)
    if (
        rev.sha256 != selection.expected_revision_sha256
        or not detail.integrity_valid
        or not detail.context_current
        or parent.revision != rev.revision
    ):
        raise fail(
            "WRITING_SOURCE_CHANGED", "Select the current intact publication revision and sources"
        )
    target = next((s for s in detail.sections if s.key == selection.target_section_key), None)
    if (
        target is None
        or (selection.profile == "tech-paper-template" and target.kind != "SKELETON")
        or (selection.profile == "research-paper-writing" and target.kind != "MANUSCRIPT")
    ):
        raise fail("WRITING_TARGET_INVALID", "Select a compatible existing target section", 422)
    allowed = {s.bundle_id for s in detail.sources}
    if not set(selection.bundle_ids).issubset(allowed):
        raise fail(
            "WRITING_EVIDENCE_SCOPE",
            "Writing may only use selected publication evidence bundles",
            422,
        )
    sources = []
    for identity in selection.bundle_ids:
        row = evidence_bundles.get(db, owner, project, identity)
        source = evidence_bundles.out(db, row)
        if (
            not source.integrity_valid
            or not source.context_current
            or not publications.source_available(db, owner, row)
        ):
            raise fail("WRITING_EVIDENCE_CHANGED", "Selected writing evidence is no longer current")
        sources.append(
            {
                "bundle_id": str(row.id),
                "bundle_sha256": row.bundle_sha256,
                "snapshot_sha256": row.snapshot_sha256,
                "snapshot": row.snapshot,
                "current_sha256": publications.live_sources_sha(db, owner, project, row.snapshot),
            }
        )
    source_text = "\n".join([detail.title, selection.focus, *[s.markdown for s in detail.sections]])
    receipt = registry.writing_skill_provider().load(
        selection.profile,
        selection.target_section_key,
        venue_style=selection.venue_style,
        source_text=source_text,
        target_venue=detail.target_venue,
    )
    settings = get_settings()
    if (
        settings.codex_provider != "openai_codex_sdk"
        or settings.codex_model != "gpt-6-luna"
        or settings.codex_reasoning_effort != "max"
    ):
        raise fail("WRITING_MODEL_CONFIGURATION", "Owner writing model must be gpt-6-luna / max")
    # No unselected bundle or binding payload enters the cloud prompt.
    manuscript = {
        "id": str(rev.id),
        "sha256": rev.sha256,
        "title": detail.title,
        "target_venue": detail.target_venue,
        "sections": [s.model_dump(mode="json") for s in detail.sections],
    }
    snapshot = {
        "owner_id": str(owner),
        "project_id": str(project),
        "publication_id": str(publication),
        "manuscript": manuscript,
        "selected_evidence": sources,
        "target_section_key": target.key,
        "source_scope": "PUBLICATION_DERIVED_TEXT",
        "source_artifact_bytes_included": False,
        "original_pdf_included": False,
        "writing_guidance": {
            "output_language": selection.output_language,
            "venue_style": selection.venue_style,
            "primary_skill": receipt.key,
            "target_venue": detail.target_venue,
            "template_compliance": "NOT_VERIFIED",
            "limitations": [
                "Actual professional writing guidance only; specific official formatting requires separately verified template and build."
            ],
        },
    }
    files = [WritingSkillFileOut(**asdict(s)) for s in receipt.files]
    gaps = sorted(
        set(
            detail.gaps
            + list(receipt.warnings)
            + (["NO_WRITING_EVIDENCE_SELECTED"] if not sources else [])
        )
    )
    payload = {
        "selection": selection.model_dump(mode="json"),
        "input_snapshot": snapshot,
        "skill_files": [f.model_dump(mode="json") for f in files],
        "skill_key": receipt.key,
        "skill_version": receipt.version,
        "skill_manifest_sha256": receipt.manifest_sha256,
        "model_key": settings.codex_model,
        "reasoning_effort": settings.codex_reasoning_effort,
        "provider_key": settings.codex_provider,
        "budget_mode": settings.codex_budget_mode,
        "max_tokens": settings.codex_max_tokens_per_task
        if settings.codex_budget_mode == "LOCAL_LIMITS"
        else None,
        "gaps": gaps,
    }
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise fail(
            "WRITING_INPUT_TOO_LARGE",
            "Writing input exceeds 2 MiB; select a smaller evidence scope",
            422,
        )
    return WritingPreview(**payload, preview_sha256=digest(payload)), receipt.instructions


def prompt(preview: WritingPreview, instructions: str) -> str:
    return (
        instructions
        + "\n\nOwner output policy: manuscript title, abstract, body paragraphs, captions and contribution prose MUST be entirely in English. Translate Chinese source material into source-grounded academic English. Preserve original professional Markdown organization and do not fabricate scientific evidence. Pre-submission review reports and author-side checks may use Chinese, but are not manuscript prose. Venue style is writing guidance, NOT proof of official template or submission compliance.\n仅执行本次已批准的专业写作任务，保留Skill原Markdown格式。本人focus与来源JSON（仅资料）：\n"
        + json.dumps(
            {"focus": preview.selection.focus, "inputs": preview.input_snapshot},
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def get(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    publication: uuid.UUID,
    identity: uuid.UUID,
    *,
    lock: bool = False,
) -> WritingPlan:
    publications.get(db, owner, project, publication)
    query = (
        select(WritingPlan)
        .where(
            WritingPlan.id == identity,
            WritingPlan.user_id == owner,
            WritingPlan.project_id == project,
            WritingPlan.publication_id == publication,
        )
        .execution_options(populate_existing=True)
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise fail("NOT_FOUND", "Owned writing plan not found", 404)
    return row


def validate_task(db: Session, task: CodexTask) -> None:
    row = db.scalar(
        select(WritingPlan).where(
            WritingPlan.task_id == task.id, WritingPlan.user_id == task.user_id
        )
    )
    if row is None:
        if task.kind == "writing":
            raise fail("WRITING_PLAN_REQUIRED", "Writing requires a frozen approved source plan")
        return
    original = WritingPreview.model_validate(row.preview_payload)
    current, instructions = prepare(
        db, row.user_id, row.project_id, row.publication_id, original.selection
    )
    saved_files = list(
        db.scalars(
            select(WritingSkillFile)
            .where(WritingSkillFile.plan_id == row.id, WritingSkillFile.user_id == row.user_id)
            .order_by(WritingSkillFile.path)
        )
    )
    actual = sorted(
        [WritingSkillFileOut.model_validate(f).model_dump(mode="json") for f in saved_files],
        key=lambda x: x["path"],
    )
    expected = sorted(
        [f.model_dump(mode="json") for f in original.skill_files], key=lambda x: x["path"]
    )
    if (
        current.preview_sha256 != row.preview_sha256
        or original.preview_sha256 != row.preview_sha256
        or instructions != row.instructions
        or actual != expected
        or sha(task.prompt) != row.prompt_sha256
        or task.prompt != prompt(original, row.instructions)
        or task.request_sha256 != row.task_request_sha256
        or task.request_sha256 != actual_task_request_sha(task)
        or task.model_key != original.model_key
        or task.reasoning_effort != original.reasoning_effort
        or task.provider_key != original.provider_key
        or task.budget_mode != original.budget_mode
        or (task.status != "DRAFT" and task.max_tokens != original.max_tokens)
        or task.mode != "read_only"
        or task.kind != "writing"
        or task.related_project_id != row.project_id
    ):
        raise fail(
            "WRITING_APPROVAL_CHANGED",
            "Writing Skill, input, permission or task no longer matches approval",
        )


def actual_task_request_sha(task: CodexTask) -> str:
    value = {
        "title": task.title,
        "prompt": task.prompt,
        "kind": task.kind,
        "mode": task.mode,
        "workspace_id": task.workspace_id,
        "workspace_path": task.workspace_path_snapshot,
        "related_project_id": str(task.related_project_id) if task.related_project_id else None,
        "related_research_question_id": str(task.related_research_question_id)
        if task.related_research_question_id
        else None,
    }
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def detail(db: Session, row: WritingPlan) -> WritingPlanOut:
    task = codex_tasks.get_task(db, row.user_id, row.task_id)
    frozen = WritingPreview.model_validate(row.preview_payload)
    current, gaps = True, list(frozen.gaps)
    try:
        validate_task(db, task)
    except DomainError as error:
        current = False
        gaps.append(error.code)
    candidate = db.scalar(
        select(WritingCandidate).where(
            WritingCandidate.plan_id == row.id, WritingCandidate.user_id == row.user_id
        )
    )
    if candidate is not None and (
        sha(candidate.markdown) != candidate.sha256
        or candidate.sha256 != candidate.task_response_sha256
    ):
        current = False
        gaps.append("WRITING_CANDIDATE_INTEGRITY_INVALID")
    if candidate is not None:
        try:
            candidate_integrity(db, row)
        except DomainError as error:
            current = False
            gaps.append(error.code)
    actions = list(
        db.scalars(
            select(WritingOperation)
            .where(
                WritingOperation.plan_id == row.id,
                WritingOperation.user_id == row.user_id,
                WritingOperation.kind == "adopt",
            )
            .order_by(WritingOperation.created_at, WritingOperation.id)
        )
    )
    issue_rows = list(
        db.scalars(
            select(WritingOperation)
            .where(
                WritingOperation.plan_id == row.id,
                WritingOperation.user_id == row.user_id,
                WritingOperation.kind == "issue",
            )
            .order_by(WritingOperation.created_at, WritingOperation.id)
        )
    )
    return WritingPlanOut(
        id=row.id,
        project_id=row.project_id,
        publication_id=row.publication_id,
        revision_id=row.revision_id,
        task_id=row.task_id,
        created_at=row.created_at,
        preview=frozen,
        task=CodexTaskOut.model_validate(task),
        candidate=WritingCandidateOut.model_validate(candidate) if candidate else None,
        adoptions=[WritingAdoptionOut.model_validate(a) for a in actions],
        issues=[WritingIssueOut.model_validate(a) for a in issue_rows],
        context_current=current,
        gaps=sorted(set(gaps)),
    )


def lookup(
    db: Session, owner: uuid.UUID, project: uuid.UUID, publication: uuid.UUID, key: str
) -> WritingPlan:
    publications.get(db, owner, project, publication)
    row = db.scalar(
        select(WritingPlan).where(
            WritingPlan.user_id == owner,
            WritingPlan.publication_id == publication,
            WritingPlan.create_key == key,
        )
    )
    if row is None:
        raise fail("NOT_FOUND", "Owned writing capture not found", 404)
    return row


def create(
    db: Session, owner: uuid.UUID, project: uuid.UUID, publication: uuid.UUID, body: WritingCreate
) -> WritingPlan:
    publications.get(db, owner, project, publication, lock=True)
    request_sha = digest(body.model_dump(mode="json"))
    old = db.scalar(
        select(WritingPlan).where(
            WritingPlan.user_id == owner,
            WritingPlan.publication_id == publication,
            WritingPlan.create_key == body.idempotency_key,
        )
    )
    if old:
        if old.create_sha256 != request_sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Same writing key has different input")
        return old
    frozen, instructions = prepare(db, owner, project, publication, body.selection)
    if frozen.preview_sha256 != body.expected_preview_sha256:
        raise fail("WRITING_PREVIEW_CHANGED", "Writing sources/Skill changed since preview")
    if frozen.gaps and not body.acknowledge_gaps:
        raise fail("WRITING_GAPS_REQUIRE_ACK", "Acknowledge writing source gaps")
    workspaces = [w for w in codex_tasks.load_workspaces() if "read_only" in w.allowed_modes]
    if not workspaces:
        raise fail("WORKSPACE_NOT_ALLOWED", "Configure a read-only Codex workspace", 422)
    try:
        task = codex_tasks.create_task(
            db,
            owner,
            title="专业论文写作候选",
            prompt=prompt(frozen, instructions),
            kind="writing",
            mode="read_only",
            workspace_id=workspaces[0].id,
            idempotency_key="writing:" + str(uuid.uuid4()),
            related_project_id=project,
            related_research_question_id=None,
            commit=False,
            _writing_context=True,
        )
        task.reasoning_effort = frozen.reasoning_effort
        row = WritingPlan(
            id=uuid.uuid4(),
            user_id=owner,
            project_id=project,
            publication_id=publication,
            revision_id=body.selection.revision_id,
            task_id=task.id,
            create_key=body.idempotency_key,
            create_sha256=request_sha,
            preview_sha256=frozen.preview_sha256,
            preview_payload=frozen.model_dump(mode="json"),
            instructions=instructions,
            prompt_sha256=sha(task.prompt),
            task_request_sha256=task.request_sha256,
        )
        db.add(row)
        db.flush()
        for file in frozen.skill_files:
            db.add(
                WritingSkillFile(
                    plan_id=row.id,
                    user_id=owner,
                    project_id=project,
                    publication_id=publication,
                    **file.model_dump(),
                )
            )
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def operation(db: Session, row: WritingPlan, kind: str, body: Any) -> WritingOperation | None:
    old = db.scalar(
        select(WritingOperation).where(
            WritingOperation.plan_id == row.id,
            WritingOperation.kind == kind,
            WritingOperation.idempotency_key == body.idempotency_key,
        )
    )
    if old and old.request_sha256 != digest(body.model_dump(mode="json")):
        raise fail("IDEMPOTENCY_CONFLICT", "Same writing operation key has different input")
    return old


def record(row: WritingPlan, kind: str, body: Any, **kwargs: Any) -> WritingOperation:
    return WritingOperation(
        plan_id=row.id,
        user_id=row.user_id,
        project_id=row.project_id,
        publication_id=row.publication_id,
        kind=kind,
        idempotency_key=body.idempotency_key,
        request_sha256=digest(body.model_dump(mode="json")),
        **kwargs,
    )


def start(db: Session, row: WritingPlan, body: WritingStart) -> WritingPlan:
    row = get(db, row.user_id, row.project_id, row.publication_id, row.id, lock=True)
    if operation(db, row, "start", body):
        return row
    if body.expected_preview_sha256 != row.preview_sha256:
        raise fail(
            "WRITING_PREVIEW_CHANGED", "Start approval does not match frozen writing preview"
        )
    task = codex_tasks.get_task(db, row.user_id, row.task_id)
    validate_task(db, task)
    codex_tasks.start_task(db, row.user_id, row.task_id, _commit=False, _writing_context=True)
    db.add(record(row, "start", body))
    db.commit()
    return row


def import_result(
    db: Session, row: WritingPlan, body: WritingImport, *, _commit: bool = True
) -> WritingPlan:
    row = get(db, row.user_id, row.project_id, row.publication_id, row.id, lock=True)
    if operation(db, row, "import", body):
        return row
    task = codex_tasks.get_task(db, row.user_id, row.task_id)
    if (
        task.status != "COMPLETED"
        or not task.final_response
        or len(task.final_response.encode()) > 2 * 1024 * 1024
        or sha(task.final_response) != body.expected_response_sha256
    ):
        raise fail(
            "WRITING_RESULT_UNAVAILABLE", "An exact completed raw Markdown response is required"
        )
    existing = db.scalar(select(WritingCandidate).where(WritingCandidate.plan_id == row.id))
    if existing:
        if (
            existing.markdown != task.final_response
            or existing.sha256 != body.expected_response_sha256
            or sha(existing.markdown) != existing.sha256
        ):
            raise fail(
                "WRITING_CANDIDATE_CONFLICT",
                "Original candidate differs from this completed task receipt; preserve both facts for review",
            )
    else:
        db.add(
            WritingCandidate(
                plan_id=row.id,
                user_id=row.user_id,
                project_id=row.project_id,
                publication_id=row.publication_id,
                markdown=task.final_response,
                sha256=sha(task.final_response),
                task_response_sha256=sha(task.final_response),
                idempotency_key=body.idempotency_key,
                request_sha256=digest(body.model_dump(mode="json")),
            )
        )
    db.add(record(row, "import", body))
    if _commit:
        db.commit()
    else:
        db.flush()
    return row


def save_completed_candidate(db: Session, task: CodexTask) -> None:
    """Persist returned facts without re-reading live permissions or Skill files."""
    if task.kind != "writing" or task.status != "COMPLETED" or not task.final_response:
        return
    row = db.scalar(
        select(WritingPlan).where(
            WritingPlan.task_id == task.id, WritingPlan.user_id == task.user_id
        )
    )
    if row is None:
        raise fail("WRITING_PLAN_REQUIRED", "Completed writing task has no frozen plan")
    original = WritingPreview.model_validate(row.preview_payload)
    if (
        task.prompt != prompt(original, row.instructions)
        or sha(task.prompt) != row.prompt_sha256
        or task.request_sha256 != row.task_request_sha256
        or task.request_sha256 != actual_task_request_sha(task)
    ):
        raise fail(
            "WRITING_SOURCE_RECEIPT_CHANGED",
            "Original request facts changed; raw task response retained",
        )
    body = WritingImport(
        expected_response_sha256=sha(task.final_response),
        idempotency_key="worker:" + (task.worker_lease_id or str(task.id)),
    )
    import_result(db, row, body, _commit=False)


def adoption_preview(
    db: Session, row: WritingPlan, body: WritingAdoptionSelection
) -> PublicationPreview:
    if (
        WritingPreview.model_validate(row.preview_payload).selection.profile
        == "pre-submission-reviewer"
    ):
        raise fail(
            "WRITING_REVIEW_NOT_MANUSCRIPT",
            "Review findings belong in TODO issues, not manuscript replacement",
        )
    candidate_integrity(db, row)
    candidate = db.scalar(
        select(WritingCandidate).where(
            WritingCandidate.plan_id == row.id, WritingCandidate.user_id == row.user_id
        )
    )
    if (
        candidate is None
        or sha(candidate.markdown) != candidate.sha256
        or candidate.sha256 != body.expected_candidate_sha256
        or candidate.markdown[body.start_offset : body.end_offset] != body.exact_quote
        or body.end_offset - body.start_offset != len(body.exact_quote)
    ):
        raise fail(
            "WRITING_QUOTE_INVALID",
            "Choose exact Unicode text from the immutable writing candidate",
            422,
        )
    parent = publications.get(db, row.user_id, row.project_id, row.publication_id)
    latest = publications.latest(db, parent)
    if latest.sha256 != body.expected_publication_sha256:
        raise fail("PUBLICATION_REVISION_CHANGED", "Publication changed; reload before adopting")
    value = publications.fields(db, latest)
    target = WritingPreview.model_validate(row.preview_payload).selection.target_section_key
    section = next((s for s in value.sections if s.key == target), None)
    if section is None:
        raise fail("WRITING_TARGET_INVALID", "Target section no longer exists", 422)
    section.markdown = body.exact_quote
    section.status = "DRAFT"
    value.bindings = [b for b in value.bindings if b.section_key != target]
    return publications.preview(db, row.user_id, row.project_id, value)


def candidate_integrity(db: Session, row: WritingPlan) -> WritingCandidate:
    candidate = db.scalar(
        select(WritingCandidate).where(
            WritingCandidate.plan_id == row.id, WritingCandidate.user_id == row.user_id
        )
    )
    task = codex_tasks.get_task(db, row.user_id, row.task_id)
    original = WritingPreview.model_validate(row.preview_payload)
    payload = {
        k: v
        for k, v in original.model_dump(mode="json").items()
        if k
        not in {"preview_sha256", "source_scope", "no_tools", "scientific_execution_authorized"}
    }
    if (
        candidate is None
        or sha(candidate.markdown) != candidate.sha256
        or task.status != "COMPLETED"
        or task.final_response != candidate.markdown
        or sha(task.final_response) != candidate.task_response_sha256
        or digest(payload) != row.preview_sha256
        or task.prompt != prompt(original, row.instructions)
        or sha(task.prompt) != row.prompt_sha256
        or task.request_sha256 != row.task_request_sha256
        or task.request_sha256 != actual_task_request_sha(task)
        or task.model_key != original.model_key
        or task.reasoning_effort != original.reasoning_effort
        or task.provider_key != original.provider_key
        or task.budget_mode != original.budget_mode
        or task.max_tokens != original.max_tokens
    ):
        raise fail(
            "WRITING_CANDIDATE_INVALID",
            "Original completed task and candidate source receipt no longer match",
        )
    # Reading old facts remains possible; new adoption/issue decisions require a current grant.
    validate_task(db, task)
    # The original manuscript may have newer human edits, but its immutable sources must remain current.
    parent = publications.get(db, row.user_id, row.project_id, row.publication_id)
    source_revision = publications.revision(db, parent, row.revision_id)
    if not publications.revision_out(db, source_revision).context_current:
        raise fail(
            "WRITING_SOURCE_CHANGED",
            "Original writing evidence has changed; inspect the candidate before reuse",
        )
    return candidate


def adopt(db: Session, row: WritingPlan, body: WritingAdopt) -> WritingPlan:
    row = get(db, row.user_id, row.project_id, row.publication_id, row.id, lock=True)
    if operation(db, row, "adopt", body):
        return row
    preview = adoption_preview(db, row, body)
    if preview.preview_sha256 != body.expected_adoption_preview_sha256:
        raise fail("WRITING_ADOPTION_CHANGED", "Adoption preview changed; inspect sources again")
    parent = publications.revise(
        db,
        row.user_id,
        row.project_id,
        row.publication_id,
        PublicationRevise(
            **preview.fields.model_dump(),
            expected_revision_sha256=body.expected_publication_sha256,
            expected_preview_sha256=preview.preview_sha256,
            acknowledge_gaps=body.acknowledge_gaps,
            idempotency_key="writing-adopt:" + str(uuid.uuid5(row.id, body.idempotency_key)),
        ),
        _commit=False,
    )
    rev = publications.latest(db, parent)
    db.add(
        record(
            row,
            "adopt",
            body,
            publication_revision_id=rev.id,
            revision_sha256=rev.sha256,
            exact_quote=body.exact_quote,
            start_offset=body.start_offset,
            end_offset=body.end_offset,
        )
    )
    db.commit()
    return row


def create_issue(db: Session, row: WritingPlan, body: WritingIssueCreate) -> WritingPlan:
    row = get(db, row.user_id, row.project_id, row.publication_id, row.id, lock=True)
    if operation(db, row, "issue", body):
        return row
    if (
        WritingPreview.model_validate(row.preview_payload).selection.profile
        != "pre-submission-reviewer"
    ):
        raise fail(
            "WRITING_REVIEW_REQUIRED",
            "Only a professional pre-review candidate can create review issues",
        )
    candidate = candidate_integrity(db, row)
    if (
        candidate.sha256 != body.expected_candidate_sha256
        or candidate.markdown[body.start_offset : body.end_offset] != body.exact_quote
        or body.end_offset - body.start_offset != len(body.exact_quote)
    ):
        raise fail("WRITING_QUOTE_INVALID", "Issue must retain exact review candidate text", 422)
    parent = publications.get(db, row.user_id, row.project_id, row.publication_id, lock=True)
    rev = publications.latest(db, parent)
    if rev.sha256 != body.expected_publication_sha256:
        raise fail(
            "PUBLICATION_REVISION_CHANGED",
            "Reload the current publication before recording the issue",
        )
    if not body.title.strip():
        raise fail("WRITING_ISSUE_TITLE", "A nonblank issue title is required", 422)
    task = Task(
        id=register_entity(db, row.user_id, "task"),
        user_id=row.user_id,
        project_id=row.project_id,
        title=body.title,
        category=body.category,
        priority=body.priority,
        status="todo",
        description=f"预审候选问题（本人选定，非科学判定）\nPublication revision: {rev.id}\nWriting plan: {row.id}\nCandidate SHA-256: {candidate.sha256}\nSeverity: {body.severity}\n\n{body.exact_quote}",
    )
    db.add(task)
    db.flush()
    db.add(
        record(
            row,
            "issue",
            body,
            task_id=task.id,
            severity=body.severity,
            publication_revision_id=rev.id,
            revision_sha256=rev.sha256,
            exact_quote=body.exact_quote,
            start_offset=body.start_offset,
            end_offset=body.end_offset,
        )
    )
    db.commit()
    return row
