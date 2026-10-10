"""Deterministic editable generic LaTeX; original Markdown remains authoritative.

This renderer never reads paths, calls a model, compiles or checks citations.
Markdown constructs unsupported by the fixed converter remain visible text and
are reported. Output is an internal article, not an IEEE submission template.
"""

import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath

from app.domain.latex_compilation import (
    LatexCompileRequest,
    LatexSourceFile,
    source_manifest_sha,
    validate_request,
)
from app.domain.manuscripts import (
    ManuscriptSourceFile,
    ManuscriptSourceProject,
    ManuscriptSourceRenderer,
    ManuscriptSourceRequest,
)
from app.providers.manuscript_layouts import main_document, selection
from app.providers.manuscript_tables import render_metric_tables


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file(path: str, value: str | bytes) -> ManuscriptSourceFile:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return ManuscriptSourceFile(path, raw, _sha(raw))


def escape(value: str) -> str:
    symbols = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(symbols.get(char, char) for char in value)


def _section_text(markdown: str) -> tuple[str, bool]:
    """Preserve content as escaped prose; heading/list formatting is explicit.

    Arbitrary TeX, HTML, image URLs and Markdown math are never executed by the
    converter. Author edits can add equations in the exported project later.
    """
    lines = []
    unsupported = bool(re.search(r"\$|```|!\[|\[[^\]]+\]\(|<[^>]+>|\|.*\|", markdown))
    for line in markdown.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            command = "subsection" if len(heading[1]) <= 2 else "subsubsection"
            lines.append("\\" + command + "*{" + escape(heading[2]) + "}")
        elif re.match(r"^\s*[-*+]\s+", line):
            text = re.sub(r"^\s*[-*+]\s+", "", line)
            lines.append(r"\noindent\textbullet{} " + escape(text) + r"\par")
        elif line.strip():
            lines.append(escape(line))
        else:
            lines.append("")
    return "\n".join(lines) + "\n", unsupported


class InternalManuscriptSourceRenderer(ManuscriptSourceRenderer):
    def render(self, request: ManuscriptSourceRequest) -> ManuscriptSourceProject:
        revision = request.revision
        title = revision["title"]
        sections = revision["sections"]
        if not isinstance(title, str) or not title.strip() or not isinstance(sections, list):
            raise ValueError("Invalid manuscript revision")
        if not 1 <= len(sections) <= 30 or len(request.figures) > 20:
            raise ValueError("Manuscript file bound exceeded")
        template_facts, warnings = selection(request)
        warnings.extend(
            [
                "CITATIONS_NOT_INDEPENDENTLY_VERIFIED",
                "REFERENCE_INDEX_NOT_VERIFIED_CONTEXTUAL_CITATIONS",
            ]
        )
        if request.font_profile == "ENGLISH" and any(
            re.search(r"[\u3400-\u9fff\U0001f300-\U0001faff]", str(s.get("markdown", "")))
            for s in sections
        ):
            warnings.append("ENGLISH_FONT_CJK_OR_EMOJI_CONTENT_REQUIRES_REVIEW")
        source = _json(
            {
                "revision": revision,
                "evidence": request.evidence_snapshots,
                "figure_provenance": request.figure_provenance,
                "table_provenance": request.table_provenance,
                "template_selection": template_facts,
                "tex_overrides": [
                    {"path": f.path, "sha256": f.sha256} for f in request.tex_overrides
                ],
            }
        )
        files = [
            _file("evidence/publication-revision.json", _json(revision)),
            _file("evidence/evidence-bundle.json", _json(request.evidence_snapshots)),
            _file("evidence/figure-provenance.json", _json(request.figure_provenance)),
            _file("evidence/table-provenance.json", _json(request.table_provenance)),
            _file("evidence/template-selection.json", _json(template_facts)),
        ]
        includes = []
        abstract = None
        keys = set()
        for section in sections:
            key, label, markdown = section["key"], section["title"], section["markdown"]
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or key in keys:
                raise ValueError("Invalid section identity")
            if not isinstance(markdown, str) or not isinstance(label, str):
                raise ValueError("Invalid section content")
            keys.add(key)
            files.append(_file("original/" + key + ".md", markdown))
            text, unsupported = _section_text(markdown)
            if unsupported:
                warnings.append("MANUAL_FORMAT_REVIEW: " + key)
            if section["kind"] == "MANUSCRIPT":
                path = "sections/" + key + ".tex"
                if key == "abstract":
                    files.append(_file(path, "\\begin{abstract}\n" + text + "\\end{abstract}\n"))
                    abstract = r"\input{" + path + "}" + "\n"
                else:
                    files.append(_file(path, r"\section{" + escape(label) + "}\n" + text))
                    includes.append(r"\input{" + path + "}")
        if not includes and abstract is None:
            warnings.append("NO_MANUSCRIPT_SECTIONS")
        for figure in request.figures:
            path = PurePosixPath(figure.path)
            if (
                not re.fullmatch(
                    r"figures/[a-z0-9][a-z0-9_-]{0,63}\.(png|jpg|jpeg|pdf)", figure.path
                )
                or path.is_absolute()
                or _sha(figure.content) != figure.sha256
                or not figure.content
                or len(figure.content) > 8 * 1024 * 1024
            ):
                raise ValueError("Invalid actual figure bytes or identity")
            magic = {
                ".png": b"\x89PNG\r\n\x1a\n",
                ".jpg": b"\xff\xd8\xff",
                ".jpeg": b"\xff\xd8\xff",
                ".pdf": b"%PDF-",
            }
            if not figure.content.startswith(magic[path.suffix]):
                raise ValueError("Figure MIME signature mismatch")
            files.append(figure)
            provenance = [
                item
                for item in request.figure_provenance
                if item.get("path") == figure.path and item.get("sha256") == figure.sha256
            ]
            if len(provenance) != 1:
                warnings.append("FIGURE_PROVENANCE_INCOMPLETE: " + figure.path)
            caption = provenance[0].get("caption", "") if len(provenance) == 1 else ""
            if not isinstance(caption, str) or len(caption) > 10000:
                raise ValueError("Figure caption must be bounded owner-provided text")
            if not caption.strip():
                warnings.append("FIGURE_CAPTION_REQUIRED: " + figure.path)
            if request.font_profile == "ENGLISH" and re.search(
                r"[\u3400-\u9fff\U0001f300-\U0001faff]", caption
            ):
                warnings.append("ENGLISH_FONT_CJK_OR_EMOJI_CONTENT_REQUIRES_REVIEW")
            includes.append(
                "\\begin{figure}[ht]\n\\centering\n\\includegraphics[width=0.9\\linewidth]{"
                + figure.path
                + "}\n\\caption{"
                + escape(caption)
                + "}\n\\end{figure}"
            )
        table_texts, table_includes, table_warnings = render_metric_tables(
            request.table_provenance, escape
        )
        files.extend(_file(path, text) for path, text in table_texts.items())
        includes.extend(table_includes)
        warnings.extend(table_warnings)
        bib_entries = []
        seen = set()
        for evidence in request.evidence_snapshots:
            for paper in evidence.get("references", []):
                identity = paper["paper_id"]
                if identity in seen:
                    continue
                if not re.fullmatch(r"[0-9a-fA-F-]{36}", identity):
                    raise ValueError("Invalid paper reference identity")
                seen.add(identity)
                if request.font_profile == "ENGLISH" and re.search(
                    r"[\u3400-\u9fff\U0001f300-\U0001faff]", _json(paper)
                ):
                    warnings.append("ENGLISH_FONT_CJK_OR_EMOJI_CONTENT_REQUIRES_REVIEW")
                fields = {
                    "title": paper["title"],
                    "year": str(paper.get("year") or ""),
                    "author": " and ".join(paper.get("authors", [])),
                    "doi": paper.get("doi") or "",
                    "url": paper.get("url") or "",
                }
                bib_entries.append(
                    "@misc{paper"
                    + identity.replace("-", "")
                    + ",\n"
                    + ",\n".join(
                        "  " + key + " = {" + escape(value) + "}"
                        for key, value in fields.items()
                        if value
                    )
                    + "\n}"
                )
        files.append(
            _file(
                "bibliography/references.bib",
                "% Stored metadata; unverified\n" + "\n\n".join(bib_entries),
            )
        )
        main = main_document(template_facts, escape(title), includes, abstract, bool(bib_entries))
        files.append(_file("main.tex", main))
        if request.template:
            files.extend(
                ManuscriptSourceFile(f.path, f.content, f.sha256) for f in request.template.files
            )
        if (
            len(request.tex_overrides) > 33
            or sum(len(f.content) for f in request.tex_overrides) > 4 * 1024 * 1024
        ):
            raise ValueError("Explicit TeX overrides exceed their bound")
        override_paths = set()
        override_records = []
        for override in request.tex_overrides:
            if (
                override.path in override_paths
                or not re.fullmatch(
                    r"main\.tex|sections/[a-z][a-z0-9_]{0,63}\.tex|bibliography/[a-z][a-z0-9_]{0,63}\.bib",
                    override.path,
                )
                or len(override.content) > 262144
                or _sha(override.content) != override.sha256
            ):
                raise ValueError(
                    "Only bounded explicit existing main/section/bibliography overrides are allowed"
                )
            override_paths.add(override.path)
            index = next((i for i, f in enumerate(files) if f.path == override.path), None)
            if index is None:
                raise ValueError("TeX override cannot create an unapproved new source file")
            override.content.decode("utf-8")
            old = files[index]
            original_path = "original/generated-tex/" + old.path + ".txt"
            files.append(_file(original_path, old.content))
            files[index] = override
            warnings.append("EXPLICIT_TEX_OVERRIDE: " + override.path)
            warnings.append("TEX_OVERRIDE_LAYOUT_AND_FONT_REQUIRE_OWNER_REVIEW")
            if request.font_profile == "ENGLISH" and re.search(
                r"[\u3400-\u9fff\U0001f300-\U0001faff]", override.content.decode("utf-8")
            ):
                warnings.append("ENGLISH_FONT_CJK_OR_EMOJI_CONTENT_REQUIRES_REVIEW")
            override_records.append(
                {
                    "path": override.path,
                    "generated_sha256": old.sha256,
                    "override_sha256": override.sha256,
                    "original_generated_path": original_path,
                }
            )
        files.append(_file("evidence/tex-overrides.json", _json(override_records)))
        warnings = list(dict.fromkeys(warnings))
        files.append(
            _file(
                "README.md",
                "# Editable manuscript source\n\nThis source project has not been compiled. "
                "The original Markdown and pre-override generated TeX are preserved in original/. "
                "Template: "
                + template_facts["key"]
                + "; variant: "
                + template_facts["variant"]
                + "; font profile: "
                + request.font_profile
                + ". "
                "The fixed isolated XeLaTeX compiler is required. "
                "No custom build script or shell escape is required. Use only the isolated ResearchOS compiler. "
                "Bibliography metadata is not a verified citation; do not submit before checking.\n\n"
                + "\n".join("- " + warning for warning in warnings)
                + "\n",
            )
        )
        if (
            len({f.path for f in files}) != len(files)
            or sum(len(f.content) for f in files) > 16 * 1024 * 1024
        ):
            raise ValueError("Source inventory duplicated or too large")
        inventory = [
            {"path": f.path, "sha256": f.sha256, "size_bytes": len(f.content)} for f in files
        ]
        source_sha = _sha((source + "\n" + _json(inventory)).encode())
        compile_inventory = self._compile_subset(tuple(files))
        compile_sha = source_manifest_sha(
            tuple(LatexSourceFile(f.path, f.content, f.sha256) for f in compile_inventory)
        )
        files.append(
            _file(
                "build/source-manifest.json",
                _json(
                    {
                        "source_sha256": source_sha,
                        "files": inventory,
                        "template": template_facts["key"],
                        "template_selection": template_facts,
                        "compile_files": [
                            {"path": f.path, "sha256": f.sha256, "size_bytes": len(f.content)}
                            for f in compile_inventory
                        ],
                        "compile_source_manifest_sha256": compile_sha,
                        "engine": "xelatex",
                        "compiled": False,
                    }
                ),
            )
        )
        if sum(len(f.content) for f in files) > 16 * 1024 * 1024:
            raise ValueError("Complete source including manifest exceeds its bound")
        return ManuscriptSourceProject(
            tuple(files), source_sha, tuple(warnings), template=template_facts["key"]
        )

    @staticmethod
    def _compile_subset(
        files: tuple[ManuscriptSourceFile, ...],
    ) -> tuple[ManuscriptSourceFile, ...]:
        selected = tuple(
            sorted(
                (
                    f
                    for f in files
                    if f.path == "main.tex"
                    or re.fullmatch(
                        r"(sections|tables)/[a-z][a-z0-9_]{0,63}\.tex|bibliography/[a-z][a-z0-9_]{0,63}\.bib|figures/[a-z0-9][a-z0-9_-]{0,63}\.(png|jpg|jpeg|pdf)|[A-Za-z0-9_-]+\.(cls|sty|bst)",
                        f.path,
                    )
                ),
                key=lambda f: f.path,
            )
        )
        converted = tuple(LatexSourceFile(f.path, f.content, f.sha256) for f in selected)
        validate_request(LatexCompileRequest(converted, source_manifest_sha(converted)))
        return selected

    def compile_files(self, project: ManuscriptSourceProject) -> tuple[ManuscriptSourceFile, ...]:
        selected = self._compile_subset(project.files)
        manifest_file = next(
            (f for f in project.files if f.path == "build/source-manifest.json"), None
        )
        if manifest_file is None or _sha(manifest_file.content) != manifest_file.sha256:
            raise ValueError("Source manifest is missing or its bytes differ")
        manifest = json.loads(manifest_file.content)
        inventory = [
            {"path": f.path, "sha256": f.sha256, "size_bytes": len(f.content)} for f in selected
        ]
        if (
            manifest["source_sha256"] != project.source_sha256
            or manifest["compile_files"] != inventory
            or manifest["compile_source_manifest_sha256"]
            != source_manifest_sha(
                tuple(LatexSourceFile(f.path, f.content, f.sha256) for f in selected)
            )
        ):
            raise ValueError("Compiler subset differs from the frozen source inventory")
        return selected

    def _validate_package(self, project: ManuscriptSourceProject, build_outputs: bool) -> None:
        files = {file.path: file for file in project.files}
        self.compile_files(project)
        source_manifest = json.loads(files["build/source-manifest.json"].content)
        source_inventory = source_manifest["files"]
        source_paths = [item["path"] for item in source_inventory]
        if len(source_paths) != len(set(source_paths)) or "README.md" not in source_paths:
            raise ValueError("Frozen source inventory is duplicated or incomplete")
        for item in source_inventory:
            if build_outputs and item["path"] == "README.md":
                continue
            file = files.get(item["path"])
            if file is None or item != {
                "path": file.path,
                "sha256": file.sha256,
                "size_bytes": len(file.content),
            }:
                raise ValueError("Package bytes differ from the frozen source inventory")
        allowed = {*source_paths, "build/source-manifest.json"}
        if not build_outputs:
            if project.compiled or set(files) != allowed:
                raise ValueError("Build output needs explicit compiled export mode")
            return
        allowed.update({"build/build-manifest.json", "build/build.log", "output/manuscript.pdf"})
        if set(files) - allowed or not {"build/build-manifest.json", "build/build.log"} <= set(
            files
        ):
            raise ValueError("Compiled export requires a complete exact build receipt and log")
        receipt = json.loads(files["build/build-manifest.json"].content)
        expected_inventory = [
            {"path": f.path, "sha256": f.sha256, "size_bytes": len(f.content)}
            for f in sorted(project.files, key=lambda f: f.path)
            if f.path != "build/build-manifest.json"
        ]
        status = receipt.get("status")
        pdf = files.get("output/manuscript.pdf")
        if (
            receipt.get("contract") != "researchos-document-build-v1"
            or receipt.get("source_sha256") != project.source_sha256
            or receipt.get("compile_source_sha256")
            != source_manifest["compile_source_manifest_sha256"]
            or receipt.get("template") != project.template
            or status not in {"READY", "FAILED", "UNAVAILABLE", "TIMED_OUT", "NEEDS_ATTENTION"}
            or project.compiled != (status == "READY")
            or receipt.get("engine") != project.engine
            or receipt.get("log_sha256") != files["build/build.log"].sha256
            or receipt.get("pdf_sha256") != (pdf.sha256 if pdf else None)
            or receipt.get("output_inventory") != expected_inventory
            or (status == "READY" and (pdf is None or receipt.get("exit_code") != 0))
        ):
            raise ValueError("Build receipt differs from the actual immutable output inventory")
        summary = files["README.md"].content.decode("utf-8")
        if f"Technical status: {status}." not in summary or project.source_sha256 not in summary:
            raise ValueError("Compiled README must report the actual status and source identity")

    def pack(self, project: ManuscriptSourceProject, *, build_outputs: bool = False) -> bytes:
        """Package exact files, never follow a local path or include extra files."""
        if len(project.files) > 200 or len({file.path for file in project.files}) != len(
            project.files
        ):
            raise ValueError("Invalid source inventory")
        if (
            sum(len(file.content) for file in project.files)
            > (40 if build_outputs else 16) * 1024 * 1024
        ):
            raise ValueError("Source archive exceeds bound")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(project.files, key=lambda f: f.path):
                path = PurePosixPath(file.path)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in file.path
                    or str(path) != file.path
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,239}", file.path)
                    or any(part in {"", ".", ".."} for part in file.path.split("/"))
                    or any(
                        part.split(".", 1)[0].upper()
                        in {
                            "CON",
                            "PRN",
                            "AUX",
                            "NUL",
                            *(f"COM{i}" for i in range(1, 10)),
                            *(f"LPT{i}" for i in range(1, 10)),
                        }
                        for part in path.parts
                    )
                    or _sha(file.content) != file.sha256
                ):
                    raise ValueError("Invalid source file")
                limit = 8 * 1024 * 1024
                if file.path == "output/manuscript.pdf":
                    if not build_outputs or not file.content.startswith(b"%PDF-"):
                        raise ValueError("PDF build output needs explicit compiled export mode")
                    limit = 16 * 1024 * 1024
                elif file.path == "build/build.log":
                    if not build_outputs:
                        raise ValueError("Build log needs explicit compiled export mode")
                    limit = 2 * 1024 * 1024
                if len(file.content) > limit:
                    raise ValueError("Source/output file exceeds its exact byte bound")
                info = zipfile.ZipInfo(file.path, (2026, 10, 8, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, file.content)
        self._validate_package(project, build_outputs)
        raw = output.getvalue()
        if len(raw) > (40 if build_outputs else 16) * 1024 * 1024:
            raise ValueError("Actual ZIP exceeds its exact byte bound")
        return raw
