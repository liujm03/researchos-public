"""Run the optional Codex task worker: python -m app.codex_worker."""

import asyncio
import logging
from contextlib import suppress

from app.core.config import get_settings
from app.db import SessionLocal
from app.providers.codex.openai_codex_sdk import OpenAICodexSDKProvider
from app.services.codex_tasks import codex_capabilities
from app.services.codex_worker import (
    claim_next_codex_task,
    heartbeat_codex_task,
    process_codex_task,
    recover_stale_codex_tasks,
)
from app.services.configuration import ensure_production_ready

logger = logging.getLogger("researchos.codex_worker")


async def run() -> None:
    ensure_production_ready(get_settings())
    logging.basicConfig(level=logging.INFO)
    if get_settings().codex_provider != "openai_codex_sdk":
        logger.info("Codex provider disabled; worker exiting")
        return
    provider = OpenAICodexSDKProvider()
    logger.info("Codex worker started")
    while True:
        with SessionLocal() as db:
            recovered = recover_stale_codex_tasks(db)
            if recovered:
                logger.warning("Marked %s stale Codex tasks as unknown outcome", recovered)
        if not codex_capabilities()["available"]:
            await asyncio.sleep(10)
            continue
        with SessionLocal() as db:
            task = claim_next_codex_task(db)
            if task:
                heartbeat = asyncio.create_task(
                    heartbeat_codex_task(task.id, task.worker_lease_id or "")
                )
                try:
                    result = await process_codex_task(db, task.id, provider)
                finally:
                    heartbeat.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat
                logger.info("Codex task %s finished with %s", result.id, result.status)
            else:
                await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Codex worker stopped")
