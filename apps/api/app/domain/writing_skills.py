"""Professional writing instructions are actual frozen files, not a profile name."""

from typing import Protocol

from app.domain.research_planning import PlanningSkillReceipt

PROFILES = {
    "tech-paper-template": (
        "background",
        "limitations",
        "key_idea",
        "challenges",
        "method",
        "contributions",
    ),
    "research-paper-writing": (
        "abstract",
        "introduction",
        "related_work",
        "method",
        "proposed_method",
        "experiments",
        "results",
        "discussion",
        "conclusion",
    ),
    "pre-submission-reviewer": (
        "abstract",
        "introduction",
        "related_work",
        "method",
        "proposed_method",
        "experiments",
        "results",
        "discussion",
        "conclusion",
    ),
}


class WritingSkillProvider(Protocol):
    def load(
        self,
        profile: str,
        target: str,
        *,
        venue_style: str = "GENERIC",
        source_text: str = "",
        target_venue: str = "",
    ) -> PlanningSkillReceipt: ...
