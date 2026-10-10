"""Portable, owner-scoped views over the full JSON research export.

The caller must pass export_user_data(db, owner); this module never queries an
unscoped table or invents absent bibliographic fields.
"""

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import defaultdict
from decimal import Decimal
from typing import Any

from app.db import Base
from app.services.portability import json_safe

ExportData = dict[str, Any]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True)
    return str(json_safe(value))


def _csv_cell(value: Any) -> str:
    text = _safe_text(value)
    if not isinstance(value, (int, float, Decimal)) and text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    if text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def _zip(files: dict[str, bytes], *, source: ExportData, format_name: str) -> bytes:
    manifest = {
        "format": format_name,
        "schema_version": source["schema_version"],
        "exported_at": str(json_safe(source["exported_at"])),
        "source_manifest": json_safe(source["manifest"]),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        )
    return buffer.getvalue()


def export_csv_zip(source: ExportData) -> bytes:
    files: dict[str, bytes] = {}
    for name, rows in sorted(source["tables"].items()):
        table = Base.metadata.tables.get(name)
        if table is None:
            raise ValueError(f"Export table has no schema: {name}")
        fields = [column.name for column in table.columns]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: tuple(_safe_text(item.get(key)) for key in fields)):
            writer.writerow({key: _csv_cell(row.get(key)) for key in fields})
        files[f"tables/{name}.csv"] = output.getvalue().encode("utf-8")
    return _zip(files, source=source, format_name="csv-tables")


def _one_line(value: Any) -> str:
    return re.sub(r"\s+", " ", _safe_text(value)).strip()


def _block(value: Any) -> str:
    return _safe_text(value).strip() or "（未记录）"


def _fence(value: str, language: str = "") -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", value)), default=0)
    marker = "`" * max(3, longest + 1)
    return f"{marker}{language}\n{value.rstrip()}\n{marker}"


def _metadata_line(label: str, value: Any) -> str:
    return f"- {label}: {_one_line(value) or '（未记录）'}"


def _index(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(row[key])].append(row)
    return result


def _bibliography(source: ExportData) -> list[dict[str, Any]]:
    tables = source["tables"]
    venues = {str(row["id"]): row for row in tables["venues"]}
    authors = {str(row["id"]): row for row in tables["authors"]}
    positions = _index(tables["paper_authors"], "paper_id")
    result = []
    for paper in sorted(tables["papers"], key=lambda row: str(row["id"])):
        ordered = sorted(positions.get(str(paper["id"]), []), key=lambda row: row["position"])
        names = [
            _safe_text(authors[str(link["author_id"])]["display_name"])
            for link in ordered
            if str(link["author_id"]) in authors
        ]
        venue = venues.get(str(paper["venue_id"])) if paper.get("venue_id") else None
        result.append({"paper": paper, "authors": names, "venue": venue})
    return result


def export_markdown_zip(source: ExportData) -> bytes:
    tables = source["tables"]
    files: dict[str, bytes] = {
        "README.md": (
            b"# ResearchOS Markdown export\n\n"
            b"Readable owner data with stable ResearchOS IDs. Attachments are not included; "
            b"use a complete database and attachment backup for restoration.\n"
        )
    }
    questions = _index(tables["research_questions"], "project_id")
    milestones = _index(tables["milestones"], "project_id")
    for project in tables["research_projects"]:
        project_id = str(project["id"])
        lines = [
            f"# {_one_line(project['name'])}", "",
            _metadata_line("ResearchOS ID", project_id),
            _metadata_line("状态", project.get("status")),
            _metadata_line("Pipeline", project.get("pipeline_stage")),
            _metadata_line("上级课题 ID", project.get("parent_project_id")), "",
        ]
        for label, field in (
            ("概述", "summary"), ("问题", "problem"), ("动机", "motivation"),
            ("研究缺口", "research_gap"), ("方法", "method_overview"),
        ):
            lines.extend([f"## {label}", "", _block(project.get(field)), ""])
        lines.extend(["## 研究问题", ""])
        lines.extend(
            f"- `{row['id']}` {_one_line(row['question'])}"
            for row in sorted(questions.get(project_id, []), key=lambda row: row["sort_order"])
        )
        lines.extend(["", "## 里程碑", ""])
        lines.extend(
            f"- `{row['id']}` {_one_line(row['title'])} ({_one_line(row.get('status'))})"
            for row in sorted(milestones.get(project_id, []), key=lambda row: row["sort_order"])
        )
        files[f"projects/{project_id}.md"] = ("\n".join(lines).rstrip() + "\n").encode("utf-8")

    notes = _index(tables["paper_notes"], "paper_id")
    readings = {str(row["paper_id"]): row for row in tables["paper_readings"]}
    sources = _index(tables["paper_sources"], "paper_id")
    for entry in _bibliography(source):
        paper = entry["paper"]
        paper_id = str(paper["id"])
        venue = entry["venue"]
        reading = readings.get(paper_id)
        lines = [
            f"# {_one_line(paper['title'])}", "",
            _metadata_line("ResearchOS ID", paper_id),
            _metadata_line("作者", "; ".join(entry["authors"])),
            _metadata_line("年份", paper.get("year")),
            _metadata_line("来源", venue["name"] if venue else None),
            _metadata_line("DOI", paper.get("doi")),
            _metadata_line("arXiv", paper.get("arxiv_id")),
            _metadata_line("阅读状态", reading.get("reading_status") if reading else None),
            "", "## 摘要", "", _block(paper.get("abstract")), "",
            "## 外部来源", "",
        ]
        lines.extend(
            f"- `{row['provider_key']}` / `{row['provider_id']}` (v{row.get('source_version')})"
            for row in sources.get(paper_id, [])
        )
        lines.extend(["", "## 阅读笔记", ""])
        for note in notes.get(paper_id, []):
            lines.extend([
                f"### {_one_line(note.get('title')) or '笔记'} · `{note['id']}`", "",
                _block(note.get("body_markdown")), "",
            ])
        files[f"papers/{paper_id}.md"] = ("\n".join(lines).rstrip() + "\n").encode("utf-8")

    sections = _index(tables["research_note_sections"], "note_id")
    evidence = _index(tables["research_note_evidence"], "section_id")
    for note in tables["paper_research_notes"]:
        note_id = str(note["id"])
        lines = [
            f"# 结构化论文笔记 `{note_id}`", "",
            _metadata_line("Paper ID", note.get("paper_id")),
            _metadata_line("修订版", note.get("revision")),
            _metadata_line("证据范围", note.get("analysis_scope")),
            _metadata_line("分析模式", note.get("analysis_mode")),
            _metadata_line("审核状态", note.get("review_status")),
            "", "## 摘要", "", _block(note.get("summary")), "",
        ]
        for section in sections.get(note_id, []):
            lines.extend([
                f"## {_one_line(section['section_key'])}", "",
                _metadata_line("来源类型", section.get("origin_type")),
                _metadata_line("审核状态", section.get("review_status")),
                "", _block(section.get("body_markdown")), "",
            ])
            for quote in evidence.get(str(section["id"]), []):
                lines.append(
                    f"- 证据 `{quote['id']}` · {_one_line(quote.get('source_section'))} "
                    f"p.{_one_line(quote.get('source_page'))}: {_one_line(quote.get('evidence_text'))}"
                )
            lines.append("")
        files[f"research-notes/{note_id}.md"] = ("\n".join(lines).rstrip() + "\n").encode("utf-8")

    for journal in tables["research_journals"]:
        day = str(journal["journal_date"])
        lines = [f"# 科研日志 {day}", "", _metadata_line("日期", day), ""]
        for label, field in (
            ("今天完成", "completed"), ("今天阅读", "papers_read"),
            ("今天实验", "experiments"), ("今天学习", "learning"),
            ("遇到问题", "problems"), ("新 Idea", "new_ideas"),
            ("明天计划", "tomorrow_plan"),
        ):
            lines.extend([f"## {label}", "", _block(journal.get(field)), ""])
        files[f"journals/{day}.md"] = ("\n".join(lines).rstrip() + "\n").encode("utf-8")

    for task in tables["tasks"]:
        task_id = str(task["id"])
        lines = [
            f"# {_one_line(task['title'])}", "",
            _metadata_line("ResearchOS ID", task_id),
            _metadata_line("课题 ID", task.get("project_id")),
            _metadata_line("类别", task.get("category")),
            _metadata_line("状态", task.get("status")),
            _metadata_line("截止时间", task.get("due_at")),
            "", "## 描述", "", _block(task.get("description")), "",
        ]
        files[f"tasks/{task_id}.md"] = ("\n".join(lines)).encode("utf-8")

    for task in tables["codex_tasks"]:
        task_id = str(task["id"])
        lines = [
            f"# {_one_line(task['title'])}", "",
            _metadata_line("ResearchOS ID", task_id),
            _metadata_line("类型", task.get("kind")),
            _metadata_line("模型", task.get("model_key")),
            _metadata_line("状态", task.get("status")),
            _metadata_line("工作区 ID", task.get("workspace_id")),
            "", "## 任务说明", "", _block(task.get("prompt")), "",
            "## 最终回复", "", _block(task.get("final_response")), "",
        ]
        if task.get("diff_patch"):
            lines.extend(["## 代码补丁", "", _fence(str(task["diff_patch"]), "diff"), ""])
        files[f"codex-tasks/{task_id}.md"] = ("\n".join(lines)).encode("utf-8")
    return _zip(files, source=source, format_name="markdown")


def _bibtex_escape(value: Any) -> str:
    text = _one_line(value)
    replacements = {
        "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}",
        "&": r"\&", "%": r"\%", "_": r"\_", "#": r"\#", "$": r"\$",
    }
    return "".join(replacements.get(char, char) for char in text)


def export_bibtex(source: ExportData) -> str:
    entries = []
    for row in _bibliography(source):
        paper = row["paper"]
        venue = row["venue"]
        kind = "article" if venue and venue["type"] == "journal" else (
            "inproceedings" if venue and venue["type"] == "conference" else "misc"
        )
        fields: list[tuple[str, Any]] = [("title", paper["title"])]
        if row["authors"]:
            fields.append(("author", " and ".join(row["authors"])))
        if paper.get("year") is not None:
            fields.append(("year", paper["year"]))
        if venue:
            field = "journal" if kind == "article" else "booktitle" if kind == "inproceedings" else "howpublished"
            fields.append((field, venue["name"]))
        for field, source_key in (
            ("doi", "doi"), ("url", "url"), ("eprint", "arxiv_id"),
            ("abstract", "abstract"),
        ):
            if paper.get(source_key):
                fields.append((field, paper[source_key]))
        content = ",\n".join(f"  {name} = {{{_bibtex_escape(value)}}}" for name, value in fields)
        entries.append(f"@{kind}{{researchos_{str(paper['id']).replace('-', '')},\n{content}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def _ris_line(tag: str, value: Any) -> str:
    return f"{tag}  - {_one_line(value)}\n"


def export_ris(source: ExportData) -> str:
    records = []
    for row in _bibliography(source):
        paper = row["paper"]
        venue = row["venue"]
        record = _ris_line("TY", "JOUR" if venue and venue["type"] == "journal" else (
            "CONF" if venue and venue["type"] == "conference" else "GEN"
        ))
        record += _ris_line("ID", paper["id"])
        record += _ris_line("TI", paper["title"])
        for author in row["authors"]:
            record += _ris_line("AU", author)
        if paper.get("year") is not None:
            record += _ris_line("PY", paper["year"])
        if venue:
            record += _ris_line("JO" if venue["type"] == "journal" else "T2", venue["name"])
        for tag, key in (("DO", "doi"), ("UR", "url"), ("AB", "abstract")):
            if paper.get(key):
                record += _ris_line(tag, paper[key])
        records.append(record + "ER  - \n")
    return "\n".join(records)
