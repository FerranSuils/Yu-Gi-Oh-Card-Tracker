"""Once a day, invoices the 2 € upkeep on 31 December (and catches up through January if a run was missed)."""

from __future__ import annotations

import asyncio
import logging

from src.services.billing.service import billing_service

logger = logging.getLogger(__name__)
CHECK_EVERY_SECONDS = 6 * 3600
_task = None


async def _loop() -> None:
    while True:
        try:
            done = await asyncio.get_running_loop().run_in_executor(None, billing_service.run_year_end)
            if done:
                logger.info('Annual upkeep invoices created for %d accounts', len(done))
        except Exception:
            logger.exception('Annual invoicing failed')
        await asyncio.sleep(CHECK_EVERY_SECONDS)


def start_scheduler() -> None:
    global _task
    if billing_service.enabled and (_task is None or _task.done()):
        _task = asyncio.get_running_loop().create_task(_loop())
