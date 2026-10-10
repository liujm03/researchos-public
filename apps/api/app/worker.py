"""Durable single-process analysis worker.

Run separately from the API: python -m app.worker
"""

import asyncio
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.errors import DomainError
from app.models import User
from app.providers.paper_parser.pdfplumber_parser import PdfPlumberParser
from app.providers.registry import ai_provider, reference_manager, storage_provider
from app.services.analysis_worker import (
    process_next_analysis_job,
    process_next_local_finalization,
    recover_stale_analysis_jobs,
)
from app.services.archive_jobs import schedule_due
from app.services.archive_worker import process_next as process_next_archive_job
from app.services.auto_literature import process_due_auto_sync
from app.services.baseline_run_worker import process_next as process_next_baseline_run
from app.services.canonical_notes import process_due_canonical_publication
from app.services.configuration import ensure_production_ready
from app.services.literature_ingest import process_next_ingest_job
from app.services.parse_jobs import process_next_parse_job
from app.services.project_source_worker import process_next as process_next_source_job
from app.services.provisioning import process_next as process_next_provision_job
from app.services.repository_asset_worker import process_next as process_next_asset_job
from app.services.research_planning_worker import process_next as process_next_planning_job
from app.services.zotero_manual_sync import process_next_manual_sync_job

logger = logging.getLogger("researchos.worker")


async def run() -> None:
    ensure_production_ready(get_settings())
    logging.basicConfig(level=logging.INFO)
    parser = PdfPlumberParser()
    storage = storage_provider()
    try:
        provider = ai_provider()
        logger.info("AI provider active: %s/%s", provider.provider_key, provider.model_key)
    except DomainError:
        provider = None
        logger.info("AI provider unavailable; PDF parsing remains active")
    try:
        zotero = reference_manager()
    except DomainError:
        zotero = None
        logger.info("Zotero provider unavailable; ingest jobs will wait for configuration")
    logger.info("Research worker started")
    from app.services.manuscript_build_worker import run_worker as run_document_worker

    document_worker = asyncio.create_task(run_document_worker(), name="document-build-worker")
    # A separate coroutine/session keeps the bounded compiler thread from blocking other jobs.
    document_worker.add_done_callback(
        lambda task: logger.error("Document worker exited") if not task.cancelled() else None
    )
    while True:
        with SessionLocal() as db:
            try:
                owner_id = db.scalar(select(User.id))
                publication = (
                    await process_due_canonical_publication(db, owner_id)
                    if owner_id is not None
                    else None
                )
                recovered = recover_stale_analysis_jobs(db)
                if recovered:
                    logger.warning("Quarantined or requeued %s stale analysis jobs", recovered)
                ingest_job = await process_next_ingest_job(db, zotero, storage, parser)
                parse_job = (
                    await process_next_parse_job(db, parser, storage)
                    if ingest_job is None
                    else None
                )
                analysis_job = (
                    await process_next_local_finalization(db)
                    if ingest_job is None and parse_job is None
                    else None
                )
                if (
                    analysis_job is None
                    and ingest_job is None
                    and parse_job is None
                    and provider is not None
                ):
                    analysis_job = await process_next_analysis_job(db, provider)
                auto_sync_job = (
                    await process_due_auto_sync(db, zotero)
                    if ingest_job is None and parse_job is None and analysis_job is None
                    else None
                )
                manual_sync_job = (
                    await process_next_manual_sync_job(db, zotero)
                    if ingest_job is None
                    and parse_job is None
                    and analysis_job is None
                    and auto_sync_job is None
                    else None
                )
                archive_job = None
                provision_job = None
                planning_job = None
                asset_job = None
                source_job = None
                baseline_run_job = None
                if owner_id is not None and not any(
                    (
                        publication,
                        ingest_job,
                        parse_job,
                        analysis_job,
                        auto_sync_job,
                        manual_sync_job,
                    )
                ):
                    planning_job = await process_next_planning_job(db, owner_id)
                    if planning_job is None:
                        asset_job = await process_next_asset_job(db, owner_id, storage=storage)
                    if planning_job is None and asset_job is None:
                        source_job = await process_next_source_job(db, owner_id, storage=storage)
                    if planning_job is None and asset_job is None and source_job is None:
                        baseline_run_job = await process_next_baseline_run(
                            db, owner_id, storage=storage
                        )
                    if (
                        planning_job is None
                        and asset_job is None
                        and source_job is None
                        and baseline_run_job is None
                    ):
                        provision_job = await process_next_provision_job(db, owner_id)
                    if (
                        planning_job is None
                        and asset_job is None
                        and source_job is None
                        and baseline_run_job is None
                        and provision_job is None
                    ):
                        schedule_due(db, owner_id)
                        archive_job = await process_next_archive_job(db, owner_id)
            except Exception:
                logger.exception("Analysis worker iteration failed")
                ingest_job = None
                parse_job = None
                analysis_job = None
                auto_sync_job = None
                manual_sync_job = None
                publication = None
                archive_job = None
                provision_job = None
                planning_job = None
                asset_job = None
                source_job = None
                baseline_run_job = None
        completed = (
            publication
            or ingest_job
            or parse_job
            or analysis_job
            or auto_sync_job
            or manual_sync_job
            or archive_job
            or provision_job
            or planning_job
            or asset_job
            or source_job
            or baseline_run_job
        )
        if completed is None:
            await asyncio.sleep(3)
        else:
            logger.info(
                "Research job %s status=%s",
                getattr(completed, "id", getattr(completed, "job_id", "unknown")),
                getattr(completed, "status", getattr(completed, "export_status", "unknown")),
            )


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("AI worker stopped")
