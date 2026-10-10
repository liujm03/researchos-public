"""Read a selected installed skill through a bounded, deterministic port."""

import hashlib
from pathlib import Path

import yaml

from app.domain.pdf_reading import ReadingSkillReceipt
from app.errors import DomainError

MAX_SKILL_BYTES = 256_000
SELECTED_AXES = {
    "reading_purpose": ("replication",),
    "input_scope": ("full-paper",),
    "paper_type": ("general",),
    "extraction_focus": ("contribution", "method-pipeline", "equations", "experiments", "limitations", "reproducibility"),
    "output_depth": ("deep",),
}


class LocalReadingSkillProvider:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _read(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise DomainError("READING_SKILL_INVALID", "Skill reference escapes its configured root", 503)
        try:
            content = resolved.read_bytes()
            if len(content) > MAX_SKILL_BYTES:
                raise ValueError("size")
            return content.decode("utf-8-sig")
        except (OSError, ValueError):
            raise DomainError("READING_SKILL_UNAVAILABLE", "Required paper reading skill file is missing or invalid", 503) from None

    def load(self) -> ReadingSkillReceipt:
        skill = self.root / "ieee-paper-reader"
        manifest_text = self._read(skill / "manifest.yaml")
        try:
            manifest = yaml.safe_load(manifest_text)
            if not isinstance(manifest, dict) or manifest.get("name") != "ieee-paper-reader":
                raise ValueError("manifest")
            required = ["SKILL.md", *manifest["always_load"]]
            for axis, values in SELECTED_AXES.items():
                for value in values:
                    required.append(manifest["axes"][axis]["values"][value])
            required += ["../_shared/references/ieee-experiment-checklist.md", "../_shared/references/ieee-figure-table-standards.md"]
            if len(required) > 40 or any(not isinstance(name, str) for name in required):
                raise ValueError("references")
            version = str(manifest["version"])
            if not 0 < len(version) <= 80:
                raise ValueError("version")
        except (KeyError, TypeError, ValueError, yaml.YAMLError):
            raise DomainError("READING_SKILL_INVALID", "Reading skill manifest is invalid", 503) from None
        fragments = [f"## manifest.yaml\n{manifest_text}"]
        for name in dict.fromkeys(required):
            fragments.append(f"## {name}\n{self._read(skill / name)}")
        instructions = "\n\n".join(fragments)
        if len(instructions.encode("utf-8")) > MAX_SKILL_BYTES:
            raise DomainError("READING_SKILL_INVALID", "Selected skill exceeds instruction limit", 503)
        return ReadingSkillReceipt("ieee-paper-reader", version, instructions, hashlib.sha256(instructions.encode("utf-8")).hexdigest())
