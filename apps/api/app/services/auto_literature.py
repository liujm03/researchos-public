"""Owner-opted periodic Zotero sync using the durable per-paper ingest queue."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.reference_manager import ReferenceItem, ReferenceManagerProvider
from app.errors import DomainError
from app.models import AnalysisSettings
from app.services.literature_ingest import enqueue_ingest
from app.services.zotero_sync import SyncResult, sync_zotero

FAST_CONTINUATION_DELAY = timedelta(minutes=1)


def _record_attempt(
    db: Session,
    user_id: uuid.UUID,
    *,
    error: str | None,
    has_more: bool = False,
) -> None:
    policy = db.get(AnalysisSettings, user_id)
    if policy is None:
        return
    db.refresh(policy)
    policy.auto_sync_last_run_at = datetime.now(UTC)
    policy.auto_sync_last_error = error[:2000] if error else None
    if has_more and policy.auto_sync_zotero:
        policy.auto_sync_next_run_at = datetime.now(UTC) + FAST_CONTINUATION_DELAY
    db.commit()


async def process_due_auto_sync(
    db: Session, provider: ReferenceManagerProvider | None
) -> SyncResult | None:
    """Claim at most one due schedule, then sync a bounded batch.

    The schedule claim commits before network I/O. Each changed item's source
    import and downstream ingest job are saved in the same per-item savepoint.
    """
    now = datetime.now(UTC)
    policy = db.scalar(
        select(AnalysisSettings)
        .where(
            AnalysisSettings.auto_sync_zotero.is_(True),
            or_(
                AnalysisSettings.auto_sync_next_run_at.is_(None),
                AnalysisSettings.auto_sync_next_run_at <= now,
            ),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if policy is None:
        return None
    user_id = policy.user_id
    interval = policy.auto_sync_interval_minutes
    if not 5 <= interval <= 1440 or not 1 <= policy.max_papers_per_sync <= 1000:
        policy.auto_sync_last_error = "Invalid Zotero automation interval or paper limit"
        policy.auto_sync_last_run_at = now
        policy.auto_sync_next_run_at = now + timedelta(hours=1)
        db.commit()
        return None
    copy_pdf = policy.auto_copy_pdf
    max_items = policy.max_papers_per_sync
    policy.auto_sync_next_run_at = now + timedelta(minutes=interval)
    db.commit()

    if provider is None:
        _record_attempt(db, user_id, error="Zotero provider is disabled or unavailable")
        return None

    async def queue_changed(session: Session, item: ReferenceItem) -> None:
        if not copy_pdf:
            return
        await enqueue_ingest(
            session,
            user_id,
            provider,
            item.key,
            copy_pdf=copy_pdf,
            request_analysis=False,
            analysis_mode="STANDARD",
            expected_source_version=item.version,
            commit=False,
        )

    try:
        result = await sync_zotero(
            db,
            user_id,
            provider,
            max_items=max_items,
            on_content_change=queue_changed if copy_pdf else None,
        )
    except DomainError as exc:
        db.rollback()
        _record_attempt(db, user_id, error=f"{exc.code}: {exc.message}")
        return None
    except Exception:
        db.rollback()
        _record_attempt(db, user_id, error="Zotero automatic sync failed; inspect worker logs")
        return None
    error = None
    if result.errors:
        first = result.errors[0]
        error = f"{result.failed} Zotero item(s) failed: {first.get('error', 'unknown error')}"
    elif result.status == "FAILED":
        error = "Zotero sync failed; inspect sync job"
    _record_attempt(db, user_id, error=error, has_more=result.has_more)
    return result
