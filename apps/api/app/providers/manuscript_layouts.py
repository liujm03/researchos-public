"""Exact verified template resource selection and fixed document layouts."""

import hashlib
import re
from typing import Any

from app.domain.manuscripts import ManuscriptSourceRequest


def selection(request: ManuscriptSourceRequest) -> tuple[dict[str, Any], list[str]]:
    if request.font_profile not in {"ENGLISH", "CJK_COMPAT"}:
        raise ValueError("Unknown fixed font profile")
    if request.template is None:
        if request.variant not in {None, "INTERNAL"}:
            raise ValueError("Internal draft has no publisher variant")
        return {
            "key": "RESEARCHOS_INTERNAL_ARTICLE_V1",
            "family": "INTERNAL",
            "variant": "INTERNAL",
            "font_profile": request.font_profile,
            "options": [],
            "anonymous": False,
            "resource_files": [],
        }, ["INTERNAL_DRAFT_NOT_SUBMISSION_TEMPLATE"]
    template = request.template
    descriptor = template.descriptor
    private = descriptor.use_scope == "PRIVATE_AUTHOR_USE_ONLY"
    if private and (
        descriptor.resource_status != "PRIVATE_AUTHOR_RESOURCES_AVAILABLE_LICENSE_UNCONFIRMED"
        or not template.private_use_approved
        or descriptor.family != "CVPR"
        or descriptor.target_year != 2026
    ):
        raise ValueError(
            "CVPR private author-use needs exact resources and explicit owner scope approval"
        )
    if not private and descriptor.resource_status != "RESOURCE_AVAILABLE_NOT_VENUE_APPROVAL":
        raise ValueError("Selected template resources are unavailable or license-unverified")
    variant = next((v for v in descriptor.variants if v.key == request.variant), None)
    expected = {
        "IEEE": {"IEEEtran.cls", "IEEEtran.bst"},
        "ELSEVIER": {"elsarticle.cls", "elsarticle-num.bst"},
        "CVPR": {"cvpr.sty", "ieeenat_fullname.bst"},
    }
    if variant is None or descriptor.family not in expected or request.font_profile != "ENGLISH":
        raise ValueError("Select an available exact publisher variant and English font profile")
    if {file.path for file in template.files} != expected[descriptor.family] or len(
        template.files
    ) != 2:
        raise ValueError("Publisher template resource inventory differs")
    for file in template.files:
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]+\.(cls|sty|bst)", file.path)
            or hashlib.sha256(file.content).hexdigest() != file.sha256
            or not 0 < len(file.content) <= 1024 * 1024
        ):
            raise ValueError("Publisher template resource bytes differ")
    warnings = ["VENUE_REQUIREMENTS_AND_ANONYMITY_NEED_OWNER_REVIEW", "AUTHOR_INFORMATION_REQUIRED"]
    if any(not re.fullmatch(r"[a-z0-9]+", option) for option in variant.options):
        raise ValueError("Fixed template variant options are invalid")
    if descriptor.family == "CVPR":
        if (
            not private
            or variant.key not in {"REVIEW", "FINAL"}
            or (variant.key == "REVIEW" and variant.options != ("review",))
            or (variant.key == "FINAL" and variant.options != ())
            or variant.anonymous != (variant.key == "REVIEW")
        ):
            raise ValueError("Select an exact private CVPR review or final layout")
        if request.submission_id and not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", request.submission_id
        ):
            raise ValueError("Submission ID contains invalid characters")
        if variant.key == "REVIEW" and not request.submission_id:
            warnings.append("PAPER_ID_REQUIRED_PLACEHOLDER_ONLY")
        warnings.append("PRIVATE_AUTHOR_USE_ONLY_REDISTRIBUTION_LICENSE_UNCONFIRMED")
    return {
        "key": descriptor.key,
        "family": descriptor.family,
        "version": descriptor.version,
        "official_url": descriptor.official_url,
        "manifest_sha256": descriptor.manifest_sha256,
        "license": descriptor.license,
        "variant": variant.key,
        "options": variant.options,
        "anonymous": variant.anonymous,
        "font_profile": request.font_profile,
        "use_scope": descriptor.use_scope,
        "private_use_approved": template.private_use_approved,
        "target_year": descriptor.target_year,
        "permission_purpose": descriptor.permission_purpose,
        "submission_id": request.submission_id,
        "resource_files": [
            {"path": file.path, "sha256": file.sha256, "size_bytes": len(file.content)}
            for file in template.files
        ],
    }, warnings


def main_document(
    facts: dict[str, Any],
    title: str,
    includes: list[str],
    abstract: str | None,
    has_references: bool,
) -> str:
    # title and all section/caption text are already escaped by the renderer.
    family = facts["family"]
    options = ",".join(facts["options"])
    common = "\\usepackage{graphicx}\n\\usepackage{hyperref}\n"
    bibliography = (
        (
            "\n\\nocite{*}\n\\bibliographystyle{"
            + {
                "IEEE": "IEEEtran",
                "ELSEVIER": "elsarticle-num",
                "CVPR": "ieeenat_fullname",
                "INTERNAL": "plain",
            }[family]
            + "}\n\\bibliography{bibliography/references}\n"
        )
        if has_references
        else ""
    )
    content = "\n".join(includes)
    author = "Anonymous author(s)" if facts["anonymous"] else "Author information to be provided"
    if family == "CVPR":
        return (
            "\\documentclass[10pt,twocolumn,letterpaper]{article}\n\\usepackage"
            + ("[review]" if facts["variant"] == "REVIEW" else "")
            + "{cvpr}\n\\usepackage{times}\n"
            + common
            + "\\def\\paperID{"
            + (facts["submission_id"] or "00000")
            + "}\n\\def\\confName{CVPR}\n\\def\\confYear{"
            + str(facts["target_year"])
            + "}\n\\title{"
            + title
            + "}\n\\author{"
            + author
            + "}\n\\begin{document}\n\\maketitle\n"
            + (abstract or "")
            + content
            + bibliography
            + "\\end{document}\n"
        )
    if family == "IEEE":
        return (
            "\\documentclass["
            + options
            + "]{IEEEtran}\n"
            + common
            + "\\title{"
            + title
            + "}\n\\author{"
            + author
            + "}\n\\begin{document}\n\\maketitle\n"
            + (abstract or "")
            + content
            + bibliography
            + "\\end{document}\n"
        )
    if family == "ELSEVIER":
        return (
            "\\documentclass["
            + options
            + "]{elsarticle}\n\\usepackage{fontspec}\n\\setmainfont{Latin Modern Roman}\n"
            + common
            + "\\begin{document}\n\\begin{frontmatter}\n\\title{"
            + title
            + "}\n\\author{"
            + author
            + "}\n"
            + (abstract or "")
            + "\\end{frontmatter}\n"
            + content
            + bibliography
            + "\\end{document}\n"
        )
    font = "Noto Serif CJK SC" if facts["font_profile"] == "CJK_COMPAT" else "Latin Modern Roman"
    return (
        "\\documentclass[11pt]{article}\n\\usepackage{fontspec}\n\\setmainfont{"
        + font
        + "}\n"
        + common
        + "\\usepackage[margin=25mm]{geometry}\n\\title{"
        + title
        + "}\n\\author{ResearchOS internal draft}\n\\date{}\n\\begin{document}\n\\maketitle\n"
        + (abstract or "")
        + content
        + bibliography
        + "\\end{document}\n"
    )
