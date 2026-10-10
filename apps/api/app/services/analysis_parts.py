"""Deterministically divide frozen PDF text into section-local analysis requests."""

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.ai import SourceText


@dataclass(frozen=True)
class AnalysisPart:
    """One ordered source-text slice; index is one-based for job progress."""

    index: int
    section_key: str
    source_texts: tuple[SourceText, ...]
    character_count: int


def split_source_texts(
    source_texts: Iterable[SourceText], *, max_source_chars: int
) -> tuple[AnalysisPart, ...]:
    """Split by contiguous section and raw source-character budget.

    Text is copied verbatim, including whitespace. Oversized blocks are sliced
    without changing their section, page or block index. The budget applies to
    ``SourceText.text`` only; callers must separately reserve room for prompt,
    title, abstract and structured output.
    """
    if max_source_chars < 1:
        raise ValueError("max_source_chars must be positive")

    parts: list[AnalysisPart] = []
    current: list[SourceText] = []
    section_key: str | None = None
    character_count = 0

    def finish_part() -> None:
        nonlocal current, section_key, character_count
        if current:
            assert section_key is not None
            parts.append(
                AnalysisPart(
                    index=len(parts) + 1,
                    section_key=section_key,
                    source_texts=tuple(current),
                    character_count=character_count,
                )
            )
        current = []
        section_key = None
        character_count = 0

    for source in source_texts:
        if current and source.section_key != section_key:
            finish_part()

        if not source.text:
            section_key = source.section_key
            current.append(source)
            continue

        offset = 0
        while offset < len(source.text):
            if current and character_count == max_source_chars:
                finish_part()
            section_key = source.section_key
            end = min(len(source.text), offset + max_source_chars - character_count)
            fragment = (
                source
                if offset == 0 and end == len(source.text)
                else SourceText(
                    source.section_key,
                    source.text[offset:end],
                    source.page,
                    source.block_index,
                    source.title,
                    source.ancestor_titles,
                )
            )
            current.append(fragment)
            character_count += end - offset
            offset = end

    finish_part()
    return tuple(parts)
