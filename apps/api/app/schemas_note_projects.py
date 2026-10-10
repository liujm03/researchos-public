"""Versioned mutable classification, never changes note content or human review."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_literature_context import LiteratureProjectOut


class NoteProjectContextOut(BaseModel):
    note_id: uuid.UUID
    paper_id: uuid.UUID
    classification_version: int
    projects: list[LiteratureProjectOut]
    mode: Literal["NOTE", "INHERITED_NOTE", "PAPER", "UNCLASSIFIED"]


class NoteProjectReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    project_ids: list[uuid.UUID] = Field(max_length=100)
