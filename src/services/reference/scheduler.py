"""Daily refresh of the reference sources (started from main.py on app startup)."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.services.reference import cardcluster, ygoprodeck_sets
from src.services.reference.errors import ReferenceSourceError
from src.services.reference.store import DEFAULT_ROOT, ReferenceStore

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(hours=20)
CHECK_EVERY_SECONDS = 6 * 3600
PRIMARY_SOURCE = ygoprodeck_sets.SOURCE

ADAPTERS: dict[str, Callable[[ReferenceStore], dict]] = {
    ygoprodeck_sets.SOURCE: ygoprodeck_sets.refresh,
    cardcluster.SOURCE: cardcluster.refresh,
}


def refresh_all(root=DEFAULT_ROOT, adapters: Optional[dict] = None) -> dict:
    """Run every adapter; one failing source never stops the others. Blocking."""
    result: dict = {}
    for source, adapter in (adapters or ADAPTERS).items():
        try:
            result[source] = adapter(ReferenceStore(root, source))
        except ReferenceSourceError as exc:
            logger.warning('Referencia %s no actualizada: %s', source, exc)
            result[source] = {'error': str(exc)}
        except Exception as exc:  # network errors etc.; keep the loop alive
            logger.warning('Referencia %s falló: %s', source, type(exc).__name__)
            result[source] = {'error': f'{type(exc).__name__}'}
    return result


def is_due(root, now: Optional[datetime] = None) -> bool:
    """True when the primary source was never fetched or is older than MAX_AGE."""
    now = now or datetime.now()
    records = ReferenceStore(root, PRIMARY_SOURCE).all()
    if not records:
        return True
    newest = max(r['fetched_at'] for r in records)
    return now - datetime.fromisoformat(newest) > MAX_AGE


async def start_scheduler(root=DEFAULT_ROOT) -> None:
    """Background loop: refresh at startup if due, then re-check every few hours."""
    if os.environ.get('OPENYUGI_DISABLE_PRICE_SCHEDULER', '').lower() in {'1', 'true', 'yes'}:
        return

    async def loop():
        while True:
            try:
                if await asyncio.to_thread(is_due, root):
                    result = await asyncio.to_thread(refresh_all, root)
                    logger.info('Referencias actualizadas: %s', {k: (v if 'error' in v else {s: len(x) for s, x in v.items()}) for k, v in result.items()})
            except Exception:
                logger.exception('Error en el bucle de referencias')
            await asyncio.sleep(CHECK_EVERY_SECONDS)

    asyncio.get_running_loop().create_task(loop())
