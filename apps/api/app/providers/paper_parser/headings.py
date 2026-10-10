"""Heading detection from the document's numbering and typography, not a fixed TOC."""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from statistics import median

from app.providers.paper_parser.layout import LayoutLine, PageLayout


@dataclass(frozen=True)
class HeadingInfo:
    title: str
    semantic_key: str | None
    level: int
    continuation_line_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    page_index: int
    line_index: int
    line: LayoutLine
    semantic_key: str | None
    numbering_kind: str | None
    level: int | None
    title: str
    continuation_line_indices: tuple[int, ...] = ()


_ARABIC = re.compile(r"^(\d+(?:\.\d+)*)(?:[.)]\s*|\s+)(\S.+)$")
_ROMAN = re.compile(r"^([IVXLCDM]{1,8})(?:[.)]\s*|\s+)(\S.+)$")
_LETTER = re.compile(r"^(?:\(([A-Z])\)|([A-Z])[.)])\s*(\S.+)$")
_CAPTION = re.compile(r"^(?:fig(?:ure)?\.?|table|equation|algorithm|图|表)\s*\d", re.I)


def numbered_heading(text: str) -> tuple[str, int | None, str] | None:
    if match := _ARABIC.fullmatch(text):
        return "arabic", len(match[1].split(".")), match[2]
    if match := _ROMAN.fullmatch(text):
        return "roman", 1, match[2]
    if match := _LETTER.fullmatch(text):
        return "letter", None, match[3]
    return None


def _title_like(text: str, *, prominent: bool) -> bool:
    if len(text) > 160 or len(text.split()) > 18 or len(text.strip()) < 2:
        return False
    if _CAPTION.match(text) or re.match(r"^\[\d+\]", text):
        return False
    if text.rstrip().endswith((".", ",", ";", "!")):
        return False
    if text.rstrip().endswith("?") and not prominent:
        return False
    # Ordinary numbered/bold sentences are not heading evidence by themselves.
    first = text.lstrip()[0]
    if first.isascii() and first.isalpha() and first.islower() and not prominent:
        return any(char.isupper() for char in text.split()[0])
    return True


def _tabular(line: LayoutLine, lines: tuple[LayoutLine, ...], body_size: float) -> bool:
    neighbors = [
        other
        for other in lines
        if other is not line
        and abs(other.top - line.top) <= 2
        and len(other.text.split()) <= 4
        and not other.text.rstrip().endswith((".", "!", "?"))
        and numbered_heading(other.text) is None
        and other.font_size >= line.font_size * 0.95
    ]
    if len(neighbors) >= 2:
        return True
    return any(
        other.bold_fraction < 0.5 and other.font_size <= body_size * 1.1 for other in neighbors
    )


def detect_headings(
    layouts: list[PageLayout], *, semantic_key: Callable[[str], str | None]
) -> dict[tuple[int, int], HeadingInfo]:
    font_weights: Counter[float] = Counter()
    for layout in layouts:
        for line in layout.lines:
            if line.font_size > 0:
                font_weights[round(line.font_size, 1)] += len(line.text)
    body_size = font_weights.most_common(1)[0][0] if font_weights else 10.0
    candidates: list[_Candidate] = []
    letter_scheme_active = False
    # Journal mastheads, author lines and paper titles before an actual abstract
    # belong to the source's introductory text region, not its section hierarchy.
    abstract_start = (
        next(
            (
                index
                for index, line in enumerate(layouts[0].lines)
                if semantic_key(line.text) == "abstract"
            ),
            None,
        )
        if layouts
        else None
    )
    for page_index, layout in enumerate(layouts):
        consumed: set[int] = set()
        for line_index, line in enumerate(layout.lines):
            if line_index in consumed:
                continue
            text = line.text.strip()
            numbered = numbered_heading(text)
            if page_index == 0 and abstract_start is not None and line_index < abstract_start:
                if numbered is None and line.bold_fraction < 0.65:
                    continue
            label = numbered[2] if numbered else text
            semantic = semantic_key(text)
            prominent = line.font_size >= body_size * 1.2
            bold = line.bold_fraction >= 0.65 and line.font_size >= body_size * 0.95
            spaced = all(len(token) == 1 and token.isalpha() for token in label.split())
            if not _title_like(label, prominent=prominent or semantic is not None or spaced):
                continue
            if semantic not in {"abstract", "back_matter"} and _tabular(
                line, layout.lines, body_size
            ):
                continue
            if numbered is not None and line.font_size < body_size * 0.85:
                continue
            if (
                numbered is not None
                and numbered[0] == "letter"
                and not (bold or prominent or letter_scheme_active or semantic)
            ):
                continue
            if numbered is None and not (prominent or bold or spaced or semantic):
                continue
            if numbered is None and line.font_size < body_size * 0.95:
                continue
            if semantic in {"references", "back_matter"}:
                letter_scheme_active = False
            elif numbered and numbered[0] in {"roman", "letter"}:
                letter_scheme_active = True
            title = line.text
            continuation_indices: list[int] = []
            previous = line
            if bold or prominent:
                for next_index in range(line_index + 1, min(line_index + 3, len(layout.lines))):
                    continuation = layout.lines[next_index]
                    first = continuation.text.lstrip()[:1]
                    if not first or not first.islower():
                        break
                    if (
                        abs(continuation.font_size - line.font_size) > 0.2
                        or abs(continuation.x0 - line.x0) > 20
                        or continuation.top - previous.bottom > max(4, line.font_size * 0.55)
                        or continuation.top < previous.bottom - 0.5
                        or (bold and continuation.bold_fraction < 0.65)
                        or not _title_like(continuation.text, prominent=True)
                        or numbered_heading(continuation.text)
                    ):
                        break
                    joined = f"{title}\n{continuation.text}"
                    if len(joined) > 200 or len(joined.split()) > 24:
                        break
                    title = joined
                    continuation_indices.append(next_index)
                    consumed.add(next_index)
                    previous = continuation
            candidates.append(
                _Candidate(
                    page_index,
                    line_index,
                    line,
                    semantic,
                    numbered[0] if numbered else None,
                    numbered[1] if numbered else None,
                    title,
                    tuple(continuation_indices),
                )
            )
    main_sizes = [candidate.line.font_size for candidate in candidates if candidate.level == 1]
    main_size = median(main_sizes) if main_sizes else None
    font_levels = sorted(
        {
            round(candidate.line.font_size, 1)
            for candidate in candidates
            if candidate.line.font_size > 0
        },
        reverse=True,
    )
    headings: dict[tuple[int, int], HeadingInfo] = {}
    numbered_parent_seen = False
    for candidate in candidates:
        if candidate.level is not None:
            level = candidate.level
            numbered_parent_seen = numbered_parent_seen or level == 1
        elif candidate.numbering_kind == "letter":
            level = 2 if numbered_parent_seen else 1
        elif candidate.semantic_key in {"abstract", "references", "back_matter"}:
            level = 1
        elif main_size is not None:
            level = 2 if candidate.line.font_size < main_size * 0.95 else 1
        else:
            # With no numbering, distinct heading font sizes supply the hierarchy.
            level = 1 + font_levels.index(round(candidate.line.font_size, 1))
        headings[(candidate.page_index, candidate.line_index)] = HeadingInfo(
            candidate.title,
            candidate.semantic_key,
            min(level, 6),
            candidate.continuation_line_indices,
        )
    return headings
