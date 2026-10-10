"""Pure, exact Idea/quote handoff rendering from a frozen relational source snapshot."""

import hashlib
import json
import re
from typing import Any

_FIELDS = (
    "title",
    "content",
    "problem",
    "hypothesis",
    "method",
    "contribution",
    "difficulty",
    "novelty",
    "feasibility",
    "required_dataset",
    "required_hardware",
    "next_experiment",
    "review_note",
    "status",
)


def idea_source_file(source: dict[str, Any]) -> tuple[str, str]:
    identity = str(source.get("revision_id", ""))
    if not re.fullmatch(r"[0-9a-f-]{36}", identity):
        raise ValueError("Invalid Idea revision identity")
    snapshot = source.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("revision_id") != identity:
        raise ValueError("Idea snapshot identity differs")
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if digest != source.get("source_sha256") or digest != source.get("revision_sha256"):
        raise ValueError("Idea snapshot differs from approved SHA")
    fields, quotes = snapshot.get("fields"), snapshot.get("sources")
    if not isinstance(fields, dict) or not isinstance(quotes, list) or len(quotes) > 20:
        raise ValueError("Invalid Idea source fields")
    if snapshot.get("scientific_state") != "OWNER_REPORTED_NOT_SCIENTIFICALLY_VERIFIED":
        raise ValueError("Idea must retain its owner-reported scientific boundary")
    lines = [
        "# 冻结科研 Idea",
        f"Revision: {identity}",
        f"SHA-256: {digest}",
        "本人管理决定及AI派生精读摘录；不表示作者事实已验证、实验已执行或假设成立。",
        "",
    ]
    tag_names = snapshot.get("tags", [])
    if not isinstance(tag_names, list) or any(not isinstance(name, str) for name in tag_names):
        raise ValueError("Invalid frozen Idea tag labels")
    lines.extend(["## tags", json.dumps(tag_names, ensure_ascii=False), ""])
    selected_sections = source.get("selected_sections", "")
    if not isinstance(selected_sections, str):
        raise ValueError("Invalid selected Idea sections")
    lines.extend(["## 本人选入任务书的段落", selected_sections, ""])
    for key in _FIELDS:
        value = fields.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError("Idea field must be exact text or null")
        lines.extend(["## " + key, value if value is not None else "[未提供]", ""])
    for position, quote in enumerate(quotes, 1):
        if not isinstance(quote, dict) or not isinstance(quote.get("exact_quote"), str):
            raise ValueError("Invalid Idea source quote")
        facts = {key: value for key, value in quote.items() if key != "exact_quote"}
        lines.extend(
            [
                f"## 精读来源 {position}",
                "来源身份（原PDF仅绑定，本包只含选定笔记摘录）：",
                json.dumps(facts, ensure_ascii=False, sort_keys=True, indent=2),
                "",
                "### 原笔记 exact quote",
                quote["exact_quote"],
                "",
            ]
        )
    return "ideas/" + identity + ".md", "\n".join(lines)
