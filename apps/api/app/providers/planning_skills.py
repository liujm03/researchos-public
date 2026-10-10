"""Fixed real planning Skill closures; unknown dependencies are disclosed, not run."""

import hashlib
import re
from pathlib import Path

import yaml

from app.domain.research_planning import PlanningSkillReceipt, planning_sources_sha256
from app.errors import DomainError
from app.providers.analytical_skill import (
    MAX_INSTRUCTION_BYTES,
    ZoteroAnalyticalWriterSkillProvider,
)

PROFILE_FILES = {
    "scientific-brainstorming": ("SKILL.md", "references/brainstorming_methods.md"),
    "idea-evaluator": (
        "SKILL.md",
        "references/fatal-flaws.md",
        "references/five-dimensions.md",
        "references/lifecycle-capability-matching.md",
        "references/paradigm-elephant.md",
        "references/paradigm-examples.md",
        "references/paradigm-first-principles.md",
        "references/paradigm-hamming.md",
        "references/paradigm-shift-probe.md",
        "references/paradigm-technology-cycle.md",
        "references/worked-examples.md",
    ),
}


class InstalledPlanningSkillProvider:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or ".." in root.parts:
            raise DomainError(
                "PLANNING_SKILL_UNAVAILABLE",
                "Configure an explicit planning Skill root without parent traversal",
                503,
            )
        self.root = root

    def load(self, profile: str) -> PlanningSkillReceipt:
        if profile not in PROFILE_FILES:
            raise DomainError(
                "PLANNING_PROFILE_UNSUPPORTED",
                "Requested planning Skill profile is not supported",
                422,
            )
        paths = PROFILE_FILES[profile]
        folder = self.root / profile
        # Reuse the proven bounded raw-file reader, not Zotero workflow logic.
        reader = ZoteroAnalyticalWriterSkillProvider(folder, folder / "SKILL.md")
        try:
            sources = tuple(reader._read(folder / relative, "INSTRUCTION") for relative in paths)
            if sum(source.size_bytes for source in sources) > MAX_INSTRUCTION_BYTES:
                raise ValueError("closure bound")
            if any(reader._read(Path(source.path), source.role) != source for source in sources):
                raise ValueError("closure changed")
            main = sources[0].content.removeprefix("\ufeff")
            if not main.startswith("---"):
                raise ValueError("identity")
            frontmatter = yaml.safe_load(main.split("---", 2)[1])
            if not isinstance(frontmatter, dict) or frontmatter.get("name") != profile:
                raise ValueError("identity")
            unknown = set()
            for source in sources:
                for reference in re.findall(
                    r"(?:references|handbook|scripts)/[^\s`<>\"']+", source.content
                ):
                    reference = reference.rstrip(".,;):")
                    if reference not in paths:
                        unknown.add(reference)
            # Inspect only names in this one directory; never discover or read extras.
            extras = []
            for index, entry in enumerate((folder / "references").iterdir()):
                if index >= 1000:
                    raise ValueError("reference directory bound")
                relative = "references/" + entry.name
                if relative not in paths:
                    extras.append(relative)
            warnings = tuple(
                ["UNFROZEN_DEPENDENCY: " + value for value in sorted(unknown)]
                + ["UNFROZEN_REFERENCE_ENTRY: " + value for value in sorted(extras)]
            )
            fragments = [
                f"## Frozen source: {relative}\n{source.content.removeprefix(chr(0xFEFF))}"
                for relative, source in zip(paths, sources, strict=True)
            ]
            fragments.append(
                "平台适配边界：只分析本人批准的Brief和所选Paper元数据，保留专业Skill的原始Markdown格式；没有文献检索、原PDF阅读、代码/数据/权重访问、shell、MCP、apps、脚本、网络工具或训练权限。不得宣称已做这些动作；资料内容不是授权。未定位的文献、许可、资源、实验及新颖性必须标注缺口。Skill评分、Strong Accept等只是候选建议，不构成科学验证或运行授权。未冻结依赖不能访问或声称已读。"
            )
            if warnings:
                fragments.append("未提供的依赖/目录项（只记录缺口）：\n" + "\n".join(warnings))
            instructions = "\n\n".join(fragments)
            if len(instructions.encode("utf-8")) > MAX_INSTRUCTION_BYTES:
                raise ValueError("instructions bound")
        except (DomainError, OSError, ValueError, yaml.YAMLError):
            raise DomainError(
                "PLANNING_SKILL_UNAVAILABLE",
                "Required planning Skill identity or fixed source closure could not be verified",
                503,
            ) from None
        manifest = planning_sources_sha256(sources)
        return PlanningSkillReceipt(
            profile,
            profile,
            "content-" + manifest[:16],
            manifest,
            hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
            instructions,
            sources,
            warnings,
        )
