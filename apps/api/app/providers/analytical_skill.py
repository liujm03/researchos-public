"""Frozen installed Zotero Analytical Writer + the owner's canonical template."""

import hashlib
import os
import stat
from pathlib import Path

from app.domain.pdf_reading import ReadingSkillReceipt, ReadingSkillSource
from app.errors import DomainError

MAX_INSTRUCTION_BYTES = 256_000
REQUIRED_HEADINGS = (
    "基本信息",
    "一句话摘要",
    "研究对象",
    "研究方法",
    "数据来源",
    "研究结论",
    "关联精读笔记",
    "我的判断",
)


class ZoteroAnalyticalWriterSkillProvider:
    def __init__(self, skill_path: Path, template_path: Path) -> None:
        if ".." in skill_path.parts or ".." in template_path.parts:
            raise DomainError(
                "READING_SKILL_INVALID",
                "Use explicit skill and template paths without parent traversal",
                503,
            )
        # Preserve configured junction/symlink provenance until it is checked.
        self.skill_path = Path(os.path.abspath(skill_path))
        self.template_path = Path(os.path.abspath(template_path))

    def _chain(self, path: Path) -> tuple[tuple[int, int, int, int, int, int], ...]:
        result = []
        for part in (path, *path.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("linked source")
            if part == path and not stat.S_ISREG(info.st_mode):
                raise ValueError("not a regular file")
            if part != path and not stat.S_ISDIR(info.st_mode):
                raise ValueError("not a directory ancestor")
            result.append(
                (
                    info.st_dev,
                    info.st_ino,
                    info.st_size if part == path else 0,
                    info.st_mtime_ns if part == path else 0,
                    info.st_ctime_ns if part == path and os.name != "nt" else 0,
                    info.st_mode,
                )
            )
        return tuple(result)

    def _read(self, path: Path, role: str) -> ReadingSkillSource:
        try:
            before = self._chain(path)
            if not 0 < before[0][2] <= MAX_INSTRUCTION_BYTES:
                raise ValueError("size")
            fd = os.open(
                path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_size,
                    opened.st_mtime_ns,
                    opened.st_ctime_ns if os.name != "nt" else 0,
                    opened.st_mode,
                ) != before[0] or self._chain(path) != before:
                    raise ValueError("source changed before read")
                content = stream.read(MAX_INSTRUCTION_BYTES + 1)
                after = os.fstat(stream.fileno())
                if (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns if os.name != "nt" else 0,
                    after.st_mode,
                ) != before[0] or self._chain(path) != before:
                    raise ValueError("source changed while reading")
            if (
                not content
                or len(content) > MAX_INSTRUCTION_BYTES
                or len(content) != before[0][2]
                or b"\0" in content
            ):
                raise ValueError("size")
            # Keep BOM/CRLF in the provenance content so raw bytes are recoverable.
            return ReadingSkillSource(
                str(path),
                role,
                hashlib.sha256(content).hexdigest(),
                len(content),
                content.decode("utf-8"),
            )
        except (OSError, ValueError):
            raise DomainError(
                "READING_SKILL_UNAVAILABLE",
                "Required analytical writer skill or canonical template is unavailable",
                503,
            ) from None

    def load(self) -> ReadingSkillReceipt:
        template_source = self._read(self.template_path, "TEMPLATE")
        template = template_source.content.removeprefix("\ufeff")
        headings = tuple(
            line[3:].strip() for line in template.splitlines() if line.startswith("## ")
        )
        if headings != REQUIRED_HEADINGS:
            raise DomainError(
                "NOTE_TEMPLATE_INVALID",
                "Canonical deep-reading template section order is invalid",
                503,
            )
        fragments = []
        sources = []
        for name in (
            "SKILL.md",
            "references/research-grade-transfer-workflow.md",
            "references/model-figure-workflow.md",
        ):
            path = self.skill_path / name
            if not path.is_relative_to(self.skill_path):
                raise DomainError(
                    "READING_SKILL_INVALID",
                    "Analytical writer reference escapes its skill root",
                    503,
                )
            source = self._read(path, "INSTRUCTION")
            sources.append(source)
            fragments.append(f"## {name}\n{source.content.removeprefix(chr(0xFEFF))}")
        sources.append(template_source)
        if sum(source.size_bytes for source in sources) > MAX_INSTRUCTION_BYTES:
            raise DomainError(
                "READING_SKILL_INVALID",
                "Analytical writer source files exceed their bounded input size",
                503,
            )
        # Capture a coherent closure: reject edits between the individual reads.
        if any(self._read(Path(source.path), source.role) != source for source in sources):
            raise DomainError(
                "READING_SKILL_UNAVAILABLE",
                "Analytical writer source changed while capturing the instruction closure",
                503,
            )
        fragments.append(f"## 用户指定的唯一精读笔记模板\n{template}")
        fragments.append(
            "\n用户工作流约束：直接读取已批准的原始PDF所有页面；现有原始全文可作核查，但不得将摘要、整理稿或既有AI笔记替代PDF，缺MinerU缓存不能阻止直接阅读。遵循以上模板的YAML、章节顺序、字段标签和表格。最终文件由ResearchOS受控保存；禁止模型自行运行脚本、读其它文件、外联网、下载或训练。缺原文/图版/真实全文链接必须明确标未定位或deferred，不能伪造。"
        )
        instructions = "\n\n".join(fragments)
        if len(instructions.encode("utf-8")) > MAX_INSTRUCTION_BYTES:
            raise DomainError(
                "READING_SKILL_INVALID",
                "Analytical writer instructions exceed their bounded input size",
                503,
            )
        digest = hashlib.sha256(instructions.encode()).hexdigest()
        return ReadingSkillReceipt(
            "zotero-analytical-writer",
            f"content-{digest[:16]}",
            instructions,
            digest,
            (),
            template,
            hashlib.sha256(template.encode()).hexdigest(),
            tuple(sources),
        )
