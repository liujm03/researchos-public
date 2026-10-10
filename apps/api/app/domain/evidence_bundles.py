"""Pure internal evidence package port: no research execution or network authority."""

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class EvidenceFile:
    path: str
    content: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RenderedEvidenceBundle:
    files: tuple[EvidenceFile, ...]
    content: bytes
    sha256: str
    size_bytes: int


class EvidenceBundleRenderer(Protocol):
    def render(self, snapshot: dict[str, Any]) -> RenderedEvidenceBundle: ...
    def pack(self, files: tuple[EvidenceFile, ...]) -> RenderedEvidenceBundle: ...


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def csv_literal(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def bib_escape(value: Any) -> str:
    text = " ".join(str(value).split())
    return "".join(
        {
            "\\": r"\textbackslash{}",
            "{": r"\{",
            "}": r"\}",
            "%": r"\%",
            "&": r"\&",
            "_": r"\_",
            "#": r"\#",
        }.get(c, c)
        for c in text
    )


def evidence_payloads(snapshot: dict[str, Any]) -> dict[str, str]:
    statements = snapshot.get("claims")
    if not isinstance(statements, list) or not 1 <= len(statements) <= 20:
        raise ValueError("Select 1 to 20 exact claim revisions")
    markdown = [
        "# 内部科研主张与证据",
        "技术来源核验、本人判断与科学有效性是不同状态；本包不表示已实验、验证或投稿。",
        "",
    ]
    metrics = io.StringIO(newline="")
    writer = csv.writer(metrics)
    writer.writerow(
        [
            "claim_id",
            "revision_sha256",
            "relation",
            "result_id",
            "metric",
            "value",
            "unit",
            "split",
            "evaluation_protocol",
            "protocol_sha256",
            "dataset_sha256",
            "config_sha256",
            "git_commit",
            "source_origin",
            "source_sha256",
        ]
    )
    for item in statements:
        markdown.extend(
            [
                "## " + item["title"],
                item["text"],
                "",
                "### 适用条件",
                item["conditions"],
                "### 局限",
                item["limitations"],
                "### 评价标准",
                item["evaluation_criteria"],
                "",
                "本人判断：" + item["scientific_state"],
                "缺口：" + ", ".join(item["gaps"]),
                "",
            ]
        )
        for evidence in item["evidence"]:
            markdown.extend(
                [
                    "### " + evidence["relation"] + " / " + evidence["source_kind"],
                    evidence["rationale"],
                    "来源origin：" + evidence["origin"],
                    "源SHA：" + evidence["source_sha256"],
                    "",
                ]
            )
            if evidence["exact_quote"] is not None:
                markdown.extend(
                    ["#### AI派生原笔记摘录（不是作者原话核验）", evidence["exact_quote"], ""]
                )
            if evidence["observation"] is not None:
                markdown.extend(["#### 本人观察（未独立验证）", evidence["observation"], ""])
            if evidence["source_kind"] == "RESULT_METRIC":
                values = [
                    item["claim_id"],
                    item["sha256"],
                    evidence["relation"],
                    evidence["result_id"],
                    evidence["metric_name"],
                    evidence["metric_value"],
                    evidence["metric_unit"],
                    evidence["metric_split"],
                    evidence["evaluation_protocol"],
                    evidence["protocol_sha256"],
                    evidence["dataset_sha256"],
                    evidence["source_facts"].get("config_sha256"),
                    evidence["source_facts"].get("git_commit"),
                    evidence["origin"],
                    evidence["source_sha256"],
                ]
                writer.writerow(
                    [
                        value if isinstance(value, (float, int)) else csv_literal(value)
                        for value in values
                    ]
                )
            if evidence["source_kind"] == "RESULT_ARTIFACT":
                markdown.append("附件仅保留固定身份和哈希；本包未复制源附件字节。\n")
    references = snapshot.get("references", [])
    bib = [
        "% Stored metadata only; format/official identity/claim support need separate verification."
    ]
    for reference in references:
        identity = str(reference["paper_id"])
        if not re.fullmatch(r"[0-9a-f-]{36}", identity):
            raise ValueError("Invalid reference identity")
        fields = []
        for key in ("title", "year", "doi", "url"):
            if reference.get(key) is not None:
                fields.append("  " + key + " = {" + bib_escape(reference[key]) + "}")
        if reference.get("authors"):
            fields.append(
                "  author = {"
                + " and ".join(bib_escape(name) for name in reference["authors"])
                + "}"
            )
        bib.append("@misc{paper_" + identity.replace("-", "") + ",\n" + ",\n".join(fields) + "\n}")
    texts = {
        "README.md": "# ResearchOS 内部写作证据包\n\n原主张/版本、支持与反证、指标/协议及本人审阅见evidence.json。claims.md是可浏览原文。\n\n源PDF/模型/数据集和artifact字节不在此包，source_artifact_bytes_included=false。引用仅存元数据，未替代原文支撑核验。\n本包不运行AI/研究代码，不授执行、投稿或公开权限。\n",
        "claims.md": "\n".join(markdown),
        "evidence.json": json_text(snapshot),
        "metrics.csv": metrics.getvalue(),
        "references.bib": "\n\n".join(bib) + "\n",
        "references.json": json_text(references),
    }
    return texts
