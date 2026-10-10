"""Conservative geometric text ordering, independent of the PDF vendor API."""

from collections.abc import Callable
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class LayoutItem:
    x0: float
    top: float
    x1: float
    bottom: float
    text: str | None = None  # Images/rules constrain cuts but are never invented as text.
    upright: bool = True
    font_size: float = 0.0
    bold_fraction: float = 0.0


@dataclass(frozen=True)
class LayoutLine:
    x0: float
    top: float
    x1: float
    bottom: float
    text: str
    font_size: float = 0.0
    bold_fraction: float = 0.0


@dataclass(frozen=True)
class PageLayout:
    lines: tuple[LayoutLine, ...]
    needs_review: bool


def _gaps(intervals: list[tuple[float, float]], minimum: float) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    end = ordered[0][1]
    gaps: list[tuple[float, float]] = []
    for start, next_end in ordered[1:]:
        if start - end >= minimum:
            gaps.append((end, start))
        end = max(end, next_end)
    return sorted(gaps, key=lambda gap: gap[1] - gap[0], reverse=True)


def _line_groups(words: list[LayoutItem]) -> list[list[LayoutItem]]:
    if not words:
        return []
    # Bottom coordinates let small superscripts/subscripts remain beside their text.
    height = median(word.bottom - word.top for word in words)
    tolerance = max(2.0, height * 0.45)
    groups: list[list[LayoutItem]] = []
    baseline = 0.0
    for word in sorted(words, key=lambda item: (item.bottom, item.x0, item.top)):
        if not groups or word.bottom - baseline > tolerance:
            groups.append([word])
            baseline = word.bottom
        else:
            groups[-1].append(word)
    return groups


def _as_lines(items: list[LayoutItem], gutter: float) -> list[LayoutLine]:
    lines: list[LayoutLine] = []
    for group in _line_groups([item for item in items if item.text is not None]):
        fragments: list[list[LayoutItem]] = []
        for word in sorted(group, key=lambda item: item.x0):
            if not fragments or word.x0 - fragments[-1][-1].x1 >= gutter:
                fragments.append([word])
            else:
                fragments[-1].append(word)
        for fragment in fragments:
            lines.append(
                LayoutLine(
                    x0=min(word.x0 for word in fragment),
                    top=min(word.top for word in fragment),
                    x1=max(word.x1 for word in fragment),
                    bottom=max(word.bottom for word in fragment),
                    text=" ".join(word.text for word in fragment if word.text),
                    font_size=median(word.font_size for word in fragment),
                    bold_fraction=sum(
                        word.bold_fraction * len(word.text or "") for word in fragment
                    )
                    / max(1, sum(len(word.text or "") for word in fragment)),
                )
            )
    return lines


def _column_starts(items: list[LayoutItem], gutter: float, width: float) -> list[float]:
    groups: list[list[float]] = []
    for x0 in sorted(line.x0 for line in _as_lines(items, gutter)):
        if not groups or x0 - groups[-1][0] > width * 0.04:
            groups.append([x0])
        else:
            groups[-1].append(x0)
    return [median(group) for group in groups if len(group) >= 3]


def order_page(
    items: list[LayoutItem], *, width: float, is_section_heading: Callable[[LayoutLine], bool]
) -> PageLayout:
    """Read columns inside horizontal bands, leaving ambiguous geometry flagged.

    A cut must be an actual empty strip across the whole current region, including
    image/rule boxes. Full-width headings and images therefore block a page-wide
    column cut: horizontal bands are cut first until column strips are possible.
    Independent column baselines never have to align. This is text ordering, not a
    structural interpretation of captions, tables, equations or diagrams.
    """
    words = [item for item in items if item.text is not None]
    if not words:
        return PageLayout((), False)
    height = median(word.bottom - word.top for word in words)
    gutter = max(9.0, width * 0.018, height * 1.2)
    band_gap = max(5.0, height * 0.8)
    needs_review = any(not word.upright for word in words)
    items = list(items)
    initial_lines = _as_lines(items, gutter)
    column_starts = _column_starts(items, gutter, width)
    if len(column_starts) >= 2:
        for line in initial_lines:
            if not is_section_heading(line):
                continue
            if min(abs(line.x0 - start) for start in column_starts) <= width * 0.04:
                continue
            center = (line.x0 + line.x1) / 2
            if not line.x0 < width / 2 < line.x1 or abs(center - width / 2) > width * 0.08:
                continue
            if any(
                neighbor is not line and abs(neighbor.top - line.top) <= height * 0.5
                for neighbor in initial_lines
            ):
                continue
            # Short centered spanning headings can leave whitespace on both sides.
            # Their isolated row still separates bands; do not attach them to a column.
            items.append(LayoutItem(0, line.top, width, line.bottom))

    def visit(region: list[LayoutItem], depth: int) -> list[LayoutLine]:
        nonlocal needs_review
        text_items = [item for item in region if item.text is not None]
        if not text_items:
            return []
        text_top = min(item.top for item in text_items)
        text_bottom = max(item.bottom for item in text_items)
        # Rules/images at the region's outer edge cannot obstruct its inner columns.
        region = [
            item
            for item in region
            if item.text is not None or (item.bottom > text_top and item.top < text_bottom)
        ]
        if depth >= 24:
            needs_review = True
            return _as_lines(region, gutter)
        horizontal_gaps = _gaps([(item.top, item.bottom) for item in region], band_gap)
        for start, end in horizontal_gaps:
            if end - start < max(18.0, height * 2.5):
                continue
            above = [item for item in region if item.bottom <= start]
            below = [item for item in region if item.top >= end]
            above_starts = _column_starts(above, gutter, width)
            below_starts = _column_starts(below, gutter, width)
            if len(above_starts) == len(below_starts) == 2:
                if any(
                    abs(a - b) > width * 0.05
                    for a, b in zip(above_starts, below_starts, strict=False)
                ):
                    # Front matter and body may have different gutter positions even
                    # when short lines leave a coincidental page-wide empty strip.
                    needs_review = True
                    return visit(above, depth + 1) + visit(below, depth + 1)
        for start, end in _gaps([(item.x0, item.x1) for item in region], gutter):
            left = [item for item in region if item.x1 <= start]
            right = [item for item in region if item.x0 >= end]
            # A title/phrase with wide word spacing is not evidence of columns.
            if all(
                len(_line_groups([item for item in side if item.text is not None])) >= 3
                for side in (left, right)
            ):
                needs_review = True
                return visit(left, depth + 1) + visit(right, depth + 1)
        if horizontal_gaps:
            start, end = horizontal_gaps[0]
            above = [item for item in region if item.bottom <= start]
            below = [item for item in region if item.top >= end]
            return visit(above, depth + 1) + visit(below, depth + 1)
        lines = _as_lines(region, gutter)
        # Retain a warning for side-by-side fragments that lacked a supported cut.
        if any(
            abs(left.top - right.top) <= height * 0.5 and right.x0 - left.x1 >= gutter
            for left, right in zip(lines, lines[1:], strict=False)
        ):
            needs_review = True
        return lines

    return PageLayout(tuple(visit(items, 0)), needs_review)
