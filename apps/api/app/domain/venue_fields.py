from typing import Protocol


class ReferenceVenueFieldProvider(Protocol):
    def ratings(self, fields: dict[str, str]) -> list[dict[str, object]]: ...
