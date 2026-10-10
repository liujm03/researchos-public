"""Frozen-source preparation for owner-started Codex paper reproduction tasks."""

import uuid
from dataclasses import dataclass
from typing import Literal

ReproductionStage = Literal["PLAN", "IMPLEMENT_CODE"]
ReproductionScope = Literal["METADATA_ONLY", "ABSTRACT_ONLY", "FULL_TEXT", "DERIVED_NOTE"]
MAX_CONTEXT_CHARACTERS = 30_000
MAX_PROMPT_CHARACTERS = 40_000
CANONICAL_CONTEXT_VERSION = "canonical-note-reproduction-v2"
MAX_CANONICAL_CHARACTERS = 512 * 1024
MAX_CANONICAL_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class NoteExcerptRange:
    start: int
    end: int


@dataclass(frozen=True)
class ReproductionSelection:
    stage: ReproductionStage
    source_scope: ReproductionScope
    goal: str
    note_id: uuid.UUID | None = None
    parsed_document_id: uuid.UUID | None = None
    section_ids: tuple[uuid.UUID, ...] = ()
    canonical_note_id: uuid.UUID | None = None
    expected_note_sha256: str | None = None
    selection_mode: Literal["FULL", "EXCERPTS"] = "FULL"
    excerpt_ranges: tuple[NoteExcerptRange, ...] = ()
