from app.domain.reference_manager import ReferenceCatalogPage, ReferenceItem


def catalog_page(
    items: tuple[ReferenceItem, ...],
    *,
    raw_count: int,
    source_total: str | None,
    limit: int,
    start: int,
) -> ReferenceCatalogPage:
    total = int(source_total) if source_total and source_total.isdigit() else None
    if total is not None and total < start + raw_count:
        total = None
    # Advance by source rows, not the number of papers left after filtering.
    # A page consisting entirely of standalone notes still has a next page.
    next_start = start + raw_count if raw_count >= limit else None
    if total is not None and start + raw_count >= total:
        next_start = None
    return ReferenceCatalogPage(items, raw_count, total, next_start)
