from app.domain.venue_fields import ReferenceVenueFieldProvider
from app.providers.reference_manager.zotero_venue_fields import ratings_from_fields


class ZoteroVenueFieldAdapter:
    def ratings(self, fields: dict[str, str]) -> list[dict[str, object]]:
        return ratings_from_fields(fields)


def get_reference_venue_field_provider() -> ReferenceVenueFieldProvider:
    return ZoteroVenueFieldAdapter()
