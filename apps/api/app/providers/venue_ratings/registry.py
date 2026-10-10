from app.domain.venue_ratings import VenueRatingProvider
from app.providers.venue_ratings.catalog import OfficialVenueCatalog


def get_venue_rating_provider() -> VenueRatingProvider:
    """Local verified catalog today; a licensed adapter can replace this binding."""
    return OfficialVenueCatalog()
