"""Source-backed venue indicators; rankings never qualify individual papers."""

from typing import Protocol


class VenueRatingProvider(Protocol):
    def lookup(self, name: str, venue_type: str) -> list[dict[str, object]]:
        """Return independently dated facts, or no facts for an unknown venue."""
        ...
