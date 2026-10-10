"""Canonical Zotero note output validation, independent of provider vendor details."""

import re

import yaml

from app.errors import DomainError

CANONICAL_HEADINGS = (
    "基本信息",
    "一句话摘要",
    "研究对象",
    "研究方法",
    "数据来源",
    "研究结论",
    "关联精读笔记",
    "我的判断",
)


class UniqueKeysLoader(yaml.SafeLoader):
    pass


def _mapping(loader: UniqueKeysLoader, node: yaml.MappingNode) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=False)
        if key in result:
            raise ValueError("Duplicate frontmatter key")
        result[key] = loader.construct_object(value_node, deep=False)
    return result


UniqueKeysLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def frontmatter(markdown: str) -> dict[str, object]:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", markdown, re.DOTALL)
    if match is None:
        raise DomainError("ANALYTICAL_NOTE_INVALID", "Canonical note has no YAML frontmatter", 422)
    try:
        value = yaml.load(match[1], Loader=UniqueKeysLoader)
    except (yaml.YAMLError, ValueError, TypeError):
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID", "Canonical note YAML is invalid or has duplicate keys", 422
        ) from None
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID", "Canonical note metadata is not a mapping", 422
        )
    return value


def _table_headers(markdown: str, *, required_only: bool = False) -> tuple[tuple[str, ...], ...]:
    """Read actual GFM header rows, excluding optional template subsections.

    A word such as '变量' in an optional figure table or a body row must not
    become the identity of an unrelated mandatory table.
    """
    lines = markdown.splitlines()
    headers: list[tuple[str, ...]] = []
    optional_level: int | None = None
    fence: str | None = None
    for index, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            marker = line[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is not None:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading is not None:
            level, title = len(heading[1]), heading[2]
            if optional_level is not None and level <= optional_level:
                optional_level = None
            if required_only and re.match(r"(?:2[A-E]\.|潜在问题 [23])", title):
                optional_level = level
        if optional_level is not None or not line.startswith("|") or index + 1 >= len(lines):
            continue
        separator = lines[index + 1].strip()
        if not separator.startswith("|"):
            continue
        cells = tuple(part.strip() for part in re.split(r"(?<!\\)\|", line.strip("|")))
        rules = tuple(part.strip() for part in separator.strip("|").split("|"))
        if len(cells) == len(rules) and all(re.fullmatch(r":?-{3,}:?", rule) for rule in rules):
            headers.append(cells)
    return tuple(headers)


def validate_analytical_markdown(
    markdown: str, template: str, identity: dict[str, object] | None = None
) -> None:
    if not markdown or len(markdown.encode("utf-8")) > 1_048_576:
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID", "Canonical note is empty or exceeds its output limit", 422
        )
    metadata, template_metadata = frontmatter(markdown), frontmatter(template)
    if set(metadata) != set(template_metadata):
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID",
            "Canonical note must preserve every template frontmatter field",
            422,
        )
    if metadata.get("type") != "literature-note":
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID", "Canonical note type differs from the template", 422
        )
    headings = tuple(line[3:].strip() for line in markdown.splitlines() if line.startswith("## "))
    if headings != CANONICAL_HEADINGS:
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID",
            "Canonical note section order differs from the owner's template",
            422,
        )
    if "### 方法概述" not in markdown or "### 方法分析" not in markdown:
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID", "Canonical note is missing required method structure", 422
        )
    expected_subsections = [
        line
        for line in template.splitlines()
        if line.startswith("#### ") and not re.match(r"#### (?:2[A-E]\.|潜在问题 [23])", line)
    ]
    if any(heading not in markdown for heading in expected_subsections):
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID",
            "Canonical note omitted a required template audit subsection",
            422,
        )
    actual_headers = _table_headers(markdown)
    missing_headers = [
        header
        for header in _table_headers(template, required_only=True)
        if header not in actual_headers
    ]
    if missing_headers:
        raise DomainError(
            "ANALYTICAL_NOTE_INVALID",
            "Canonical note omitted required template table fields",
            422,
            details={"missing_table_headers": [list(header) for header in missing_headers]},
        )
    for pattern in (
        r"\{\{[^}]+\}\}",
        r"<collection>",
        r"<zotero_key>",
        r"在此粘贴",
        r"<!--\s*条件块",
    ):
        if re.search(pattern, markdown):
            raise DomainError(
                "ANALYTICAL_NOTE_INVALID",
                "Canonical note retains an unused template placeholder",
                422,
            )
    for key in ("zotero_key", "pdf_key", "doi", "collection", "note_path", "fulltext_path"):
        if (
            identity is not None
            and key in identity
            and str(metadata.get(key) or "") != str(identity[key] or "")
        ):
            raise DomainError(
                "ANALYTICAL_NOTE_INVALID",
                "Canonical note changed an approved stable identity field",
                422,
                details={"field": key},
            )
    if re.search(r"!\[[^\]]*\]\([^)]+\)", markdown):
        # Asset validation/export is a separate boundary; a model cannot declare
        # that a figure file was extracted merely by emitting a Markdown link.
        raise DomainError(
            "ANALYTICAL_NOTE_ASSET_UNVERIFIED",
            "Figure assets must be verified before embedding in the saved note",
            422,
        )
