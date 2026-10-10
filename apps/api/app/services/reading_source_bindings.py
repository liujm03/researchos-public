"""Actual used skill sources; never infer trust, runtime readiness or script access."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.pdf_reading import ReadingSkillSource
from app.errors import DomainError
from app.models_analytical import PaperReadingApprovalPlan
from app.models_reading_bindings import PaperReadingSkillFile
from app.services.paper_analysis import _payload_hash

VERSION = "original-pdf-files-v1"


def file_key(path: str, role: str) -> str:
    return _payload_hash({"path": path, "role": role})


def manifest_payload(rows: list[PaperReadingSkillFile]) -> list[dict[str, object]]:
    return [
        {
            "file_key_sha256": row.file_key_sha256,
            "path": row.path,
            "role": row.role,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
        }
        for row in sorted(rows, key=lambda item: item.file_key_sha256)
    ]


def sources(db: Session, plan: PaperReadingApprovalPlan) -> list[PaperReadingSkillFile]:
    return list(
        db.scalars(
            select(PaperReadingSkillFile)
            .where(
                PaperReadingSkillFile.plan_id == plan.id,
                PaperReadingSkillFile.user_id == plan.user_id,
            )
            .order_by(PaperReadingSkillFile.file_key_sha256)
        )
    )


def _invalid() -> None:
    raise DomainError(
        "READING_SOURCE_BINDING_CHANGED",
        "Frozen skill/template file evidence differs from the approved source binding",
        409,
    )


def validate(plan: PaperReadingApprovalPlan, rows: list[PaperReadingSkillFile]) -> None:
    if plan.source_manifest_sha256 is None:
        if rows or plan.source_binding_version is not None:
            _invalid()
        return
    if (
        plan.source_binding_version != VERSION
        or len(rows) != 4
        or _payload_hash({"files": manifest_payload(rows)}) != plan.source_manifest_sha256
    ):
        _invalid()
    if len({row.file_key_sha256 for row in rows}) != 4:
        _invalid()
    instructions: dict[str, str] = {}
    templates = []
    for row in rows:
        raw = row.content.encode("utf-8")
        if (
            row.user_id != plan.user_id
            or row.plan_id != plan.id
            or row.file_key_sha256 != file_key(row.path, row.role)
            or len(raw) != row.size_bytes
            or not raw
            or len(raw) > 256000
            or hashlib.sha256(raw).hexdigest() != row.sha256
        ):
            _invalid()
        content = row.content.removeprefix("\ufeff")
        if row.role == "TEMPLATE":
            templates.append(content)
        elif row.role == "INSTRUCTION":
            name = row.path.replace("\\", "/").split("/")[-1]
            if name in instructions:
                _invalid()
            instructions[name] = content
        else:
            _invalid()
    if len(templates) != 1 or templates[0] != plan.template_text:
        _invalid()
    names = {
        "SKILL.md": "SKILL.md",
        "research-grade-transfer-workflow.md": "references/research-grade-transfer-workflow.md",
        "model-figure-workflow.md": "references/model-figure-workflow.md",
    }
    if set(instructions) != set(names):
        _invalid()
    for name, relative in names.items():
        if f"## {relative}\n{instructions[name]}" not in plan.skill_instructions:
            _invalid()
    if f"## 用户指定的唯一精读笔记模板\n{templates[0]}" not in plan.skill_instructions:
        _invalid()


def freeze(
    db: Session, plan: PaperReadingApprovalPlan, receipt_files: tuple[ReadingSkillSource, ...]
) -> None:
    if not receipt_files:
        return
    rows = [
        PaperReadingSkillFile(
            plan_id=plan.id,
            user_id=plan.user_id,
            file_key_sha256=file_key(item.path, item.role),
            path=item.path,
            role=item.role,
            sha256=item.sha256,
            size_bytes=item.size_bytes,
            content=item.content,
        )
        for item in receipt_files
    ]
    plan.source_binding_version = VERSION
    plan.source_manifest_sha256 = _payload_hash({"files": manifest_payload(rows)})
    validate(plan, rows)
    db.add_all(rows)


def owned_plan(
    db: Session, owner: uuid.UUID, paper_id: uuid.UUID, plan_id: uuid.UUID
) -> PaperReadingApprovalPlan:
    plan = db.scalar(
        select(PaperReadingApprovalPlan).where(
            PaperReadingApprovalPlan.id == plan_id,
            PaperReadingApprovalPlan.user_id == owner,
            PaperReadingApprovalPlan.paper_id == paper_id,
        )
    )
    if plan is None:
        raise DomainError("NOT_FOUND", "Owned reading plan not found", 404)
    return plan
