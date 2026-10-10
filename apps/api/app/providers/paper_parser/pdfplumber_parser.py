import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

import pdfplumber
from pdfplumber.page import Page

from app.domain.paper_parser import (
    ParsedBlockData,
    ParsedSectionData,
    ParseResult,
    ParseWarningData,
)
from app.errors import DomainError
from app.providers.paper_parser.headings import detect_headings, numbered_heading
from app.providers.paper_parser.layout import LayoutItem, LayoutLine, PageLayout, order_page


class PdfPlumberParser:
    parser_name = "pdfplumber"
    parser_version = "3"

    _numbering = re.compile(r"^(?:\d+(?:\.\d+)*|[IVXLCDM]+)(?:[.)]\s*|\s+)", re.I)

    _semantic_labels: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("abstract", re.compile(r"^(?:abstract|摘要)\s*[:：]?$", re.I)),
        (
            "introduction",
            re.compile(r"^(?:\d+(?:\.\d+)?[.\s]+)?(?:introduction|引言|绪论)\s*$", re.I),
        ),
        (
            "related_work",
            re.compile(r"^(?:related\s*work|相关工作)\s*$", re.I),
        ),
        (
            "method",
            re.compile(
                r"^(?:method(?:ology|s)?|approach|proposed\s*method|方法|模型方法)\s*$",
                re.I,
            ),
        ),
        (
            "experiments",
            re.compile(
                r"^(?:\d+(?:\.\d+)?[.\s]+)?(?:experiments?|experimental (?:results|setup)|实验|实验结果)\s*$",
                re.I,
            ),
        ),
        ("results", re.compile(r"^(?:\d+(?:\.\d+)?[.\s]+)?(?:results?|结果)\s*$", re.I)),
        ("discussion", re.compile(r"^(?:\d+(?:\.\d+)?[.\s]+)?(?:discussion|讨论)\s*$", re.I)),
        (
            "conclusion",
            re.compile(r"^(?:\d+(?:\.\d+)?[.\s]+)?(?:conclusions?|结论|总结)\s*$", re.I),
        ),
        (
            "references",
            re.compile(r"^(?:\d+(?:\.\d+)?[.\s]+)?(?:references|bibliography|参考文献)\s*$", re.I),
        ),
        (
            "back_matter",
            re.compile(
                r"^(?:CRediT authorship contribution statement|author contributions?|"
                r"data availability(?: statement)?|declaration of competing interests?|"
                r"conflicts? of interest(?: statement)?|acknowledg(?:e)?ments?|funding)\s*$",
                re.I,
            ),
        ),
    )

    @classmethod
    def _heading(cls, text: str) -> str | None:
        """Return an optional semantic tag; actual headings are detected separately."""
        if len(text) > 100:
            return None
        clean = " ".join(text.strip().split()).rstrip(":：").strip()
        clean = cls._numbering.sub("", clean)
        # Letterspaced publisher headings may be extracted as individual words.
        tokens = clean.split()
        if tokens and all(len(token) == 1 and token.isalpha() for token in tokens):
            clean = "".join(tokens)
        for key, pattern in cls._semantic_labels:
            if pattern.fullmatch(clean):
                return key
        return None

    @classmethod
    def _page_layout(cls, page: Page) -> PageLayout:
        items = [
            LayoutItem(
                x0=float(word["x0"]),
                top=float(word["top"]),
                x1=float(word["x1"]),
                bottom=float(word["bottom"]),
                text=" ".join(str(word["text"]).split()),
                upright=bool(word.get("upright", True)),
                font_size=median(float(char["size"]) for char in word["chars"]),
                bold_fraction=sum(
                    any(
                        weight in str(char["fontname"]).casefold()
                        for weight in ("bold", "demi", "black")
                    )
                    for char in word["chars"]
                )
                / max(1, len(word["chars"])),
            )
            for word in page.extract_words(x_tolerance=2, y_tolerance=2, return_chars=True)
            if str(word["text"]).strip()
        ]
        for obj in page.images:
            items.append(
                LayoutItem(
                    float(obj["x0"]), float(obj["top"]), float(obj["x1"]), float(obj["bottom"])
                )
            )
        # Publisher separators and full-width rules are explicit band boundaries.
        for obj in (*page.lines, *page.rects):
            if obj["x1"] - obj["x0"] >= page.width * 0.65 and obj["bottom"] - obj["top"] <= 3:
                items.append(
                    LayoutItem(
                        float(obj["x0"]), float(obj["top"]), float(obj["x1"]), float(obj["bottom"])
                    )
                )
        return order_page(
            items,
            width=float(page.width),
            is_section_heading=lambda line: (
                cls._heading(line.text) is not None
                or numbered_heading(line.text) is not None
                or line.bold_fraction >= 0.65
            ),
        )

    @classmethod
    def _margin_key(cls, line: LayoutLine, height: float) -> str | None:
        if line.bottom > height * 0.085 and line.top < height * 0.93:
            return None
        if cls._heading(line.text):
            return None
        if cls._numbering.match(line.text) and (
            line.text[0].isdigit()
            or line.bold_fraction >= 0.65
            or re.match(r"^[IVX]+[.)]?\s", line.text)
        ):
            return None
        return " ".join(line.text.casefold().split())

    def parse(self, path: Path, *, max_pages: int = 250) -> ParseResult:
        if max_pages <= 0:
            raise DomainError("VALIDATION_ERROR", "max_pages must be positive", 422)
        blocks: list[ParsedBlockData] = []
        warnings: list[ParseWarningData] = []
        section_text: dict[str, list[str]] = defaultdict(list)
        section_pages: dict[str, list[int]] = defaultdict(list)
        section_titles: dict[str, str] = {}
        section_semantics: dict[str, str | None] = {}
        section_levels: dict[str, int | None] = {}
        section_parents: dict[str, str | None] = {}
        section_order: list[str] = []
        hierarchy: list[tuple[int, str]] = []
        current_section = "text-0001"
        heading_index = 0
        try:
            with pdfplumber.open(path) as pdf:
                total_pages = len(pdf.pages)
                if total_pages > max_pages:
                    raise DomainError(
                        "PDF_TOO_LONG",
                        f"PDF has {total_pages} pages; configured limit is {max_pages}",
                        413,
                    )
                layouts = [self._page_layout(page) for page in pdf.pages]
                margin_counts: Counter[str] = Counter()
                for page, layout in zip(pdf.pages, layouts, strict=True):
                    margin_counts.update(
                        {
                            key
                            for line in layout.lines
                            if (key := self._margin_key(line, float(page.height))) is not None
                        }
                    )
                headings = detect_headings(layouts, semantic_key=self._heading)
                heading_continuations = {
                    (page_index, continuation_index)
                    for (page_index, _), heading in headings.items()
                    for continuation_index in heading.continuation_line_indices
                }
                for page_number, (page, layout) in enumerate(
                    zip(pdf.pages, layouts, strict=True), start=1
                ):
                    lines = layout.lines
                    if not lines:
                        warnings.append(
                            ParseWarningData("NO_TEXT", "No selectable text on page", page_number)
                        )
                        continue
                    if layout.needs_review:
                        warnings.append(
                            ParseWarningData(
                                "LAYOUT_UNVERIFIED",
                                "Geometric column/band ordering applied; complex layout and reading order still require review",
                                page_number,
                            )
                        )
                    for line_index, line in enumerate(lines):
                        if (page_number - 1, line_index) in heading_continuations:
                            continue
                        text = line.text
                        if not text:
                            continue
                        margin_key = self._margin_key(line, float(page.height))
                        if margin_key and margin_counts[margin_key] >= 2:
                            continue
                        if line.top >= page.height * 0.93 and re.fullmatch(r"\d{1,5}", text):
                            continue
                        actual_heading = headings.get((page_number - 1, line_index))
                        if actual_heading:
                            heading_index += 1
                            normalized = unicodedata.normalize("NFKC", actual_heading.title)
                            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
                            current_section = f"s-{heading_index:04d}-{digest}"
                            while hierarchy and hierarchy[-1][0] >= actual_heading.level:
                                hierarchy.pop()
                            section_titles[current_section] = actual_heading.title
                            section_semantics[current_section] = actual_heading.semantic_key
                            section_levels[current_section] = actual_heading.level
                            section_parents[current_section] = (
                                hierarchy[-1][1] if hierarchy else None
                            )
                            section_order.append(current_section)
                            hierarchy.append((actual_heading.level, current_section))
                            for _, key in hierarchy:
                                section_pages[key].append(page_number)
                            continue
                        if current_section not in section_order:
                            section_order.append(current_section)
                        blocks.append(
                            ParsedBlockData(
                                block_index=len(blocks),
                                page_number=page_number,
                                section_key=current_section,
                                text=text,
                            )
                        )
                        section_text[current_section].append(text)
                        if hierarchy:
                            for _, key in hierarchy:
                                section_pages[key].append(page_number)
                        else:
                            section_pages[current_section].append(page_number)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("PARSE_FAILED", "PDF could not be parsed", 422) from exc

        if not blocks:
            warnings.append(ParseWarningData("EMPTY_DOCUMENT", "No text was extracted"))
        sections = tuple(
            ParsedSectionData(
                section_key=key,
                title=section_titles.get(key),
                start_page=min(section_pages[key]) if section_pages[key] else None,
                end_page=max(section_pages[key]) if section_pages[key] else None,
                coverage_status="FOUND",
                text="\n".join(section_text[key]) if section_text[key] else None,
                semantic_key=section_semantics.get(key),
                heading_level=section_levels.get(key),
                parent_section_key=section_parents.get(key),
            )
            for key in section_order
        )
        if blocks and not heading_index:
            warnings.append(
                ParseWarningData(
                    "HEADINGS_UNVERIFIED",
                    "Text extracted, but no section headings could be reliably identified",
                )
            )
        warnings.append(
            ParseWarningData(
                "NON_TEXT_UNVERIFIED",
                "Figures, tables and equations have not been structurally verified by this parser",
            )
        )
        return ParseResult(
            page_count=total_pages,
            extracted_characters=sum(len(block.text) for block in blocks),
            status="COMPLETE"
            if blocks and heading_index and not any(w.code == "NO_TEXT" for w in warnings)
            else "PARTIAL",
            blocks=tuple(blocks),
            sections=sections,
            warnings=tuple(warnings),
        )
