from typing import Protocol


class ReferenceVenueCacheProvider(Protocol):
    def fields(self, publication_title: str) -> dict[str, str] | None: ...
