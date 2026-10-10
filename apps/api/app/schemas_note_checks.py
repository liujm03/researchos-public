"""Computed local checks are separate from historical human review decisions."""

from typing import Literal

from pydantic import BaseModel, Field

NoteCheckStatus = Literal["PASSED", "ATTENTION", "UNAVAILABLE"]


class NoteAutoCheckOut(BaseModel):
    key: str
    label: str
    status: NoteCheckStatus
    detail: str


class NoteAutoReviewOut(BaseModel):
    status: NoteCheckStatus
    label: str
    checks: list[NoteAutoCheckOut]
    scientifically_verified: Literal[False] = False
    human_review_required: Literal[False] = Field(
        default=False,
        description="Reading has no mandatory manual confirmation prerequisite; this is not scientific approval.",
    )
