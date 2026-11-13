"""Nightly price download and automatic repricing for every account.

Runs outside any request, so every path is an explicit account root and never
``account_root()``, which would resolve to the primary account.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Callable, Iterable, Optional

from src.core.account_profile import load_profile
from src.core.collection_sync import bump, path_lock
from src.core.game_collections import GameCollectionStore
from src.core.persistence import PersistenceManager

logger = logging.getLogger(__name__)

START_HOUR = 5
MAX_AGE = timedelta(hours=20)
CHECK_EVERY_SECONDS = 3600


def account_roots(base: str = 'data') -> list[str]:
    """The primary account's folder and every registered account's folder."""
    roots = [base]
    users = os.path.join(base, 'users')
    if os.path.isdir(users):
        roots += [os.path.join(users, name) for name in sorted(os.listdir(users))
                  if os.path.isdir(os.path.join(users, name))]
    return roots


def markets_in_use(roots: Iterable[str]) -> set[str]:
    return {'cardmarket'} | {load_profile(root).price_market for root in roots}


def _all_sources():
    from src.services.prices import sources

    return sources()


def _default_get_source(game: str, market: str):
    from src.services.prices import get_source

    return get_source(game, market)


def _is_stale(source, now: datetime) -> bool:
    updated = source.store.info().get('updated_at')
    if not updated:
        return True
    try:
        return now - datetime.fromisoformat(updated) > MAX_AGE
    except (TypeError, ValueError):
        return True


def due_sources(now: datetime, markets: set[str], all_sources=None) -> list:
    """Sources to download now: after 05:00, older than 20 h, and only for markets someone uses."""
    if now.hour < START_HOUR:
        return []
    candidates = _all_sources() if all_sources is None else all_sources
    return [s for s in candidates if s.market in markets and _is_stale(s, now)]


def _reprice(collection, get_source, game: str, market: str) -> bool:
    from src.services.repricing import apply, preview

    if not collection.for_sale or not collection.pricing_rule or not collection.pricing_rule.auto_apply:
        return False
    try:
        source = get_source(game, market)
    except KeyError:
        return False
    rows = preview(collection, source.get, collection.pricing_rule)
    return apply(collection, rows) > 0


def auto_reprice(root: str, get_source: Optional[Callable] = None) -> int:
    """Apply each 'a la venta' + 'aplicar cada día' rule in one account. Returns collections changed."""
    get_source = get_source or _default_get_source
    market = load_profile(root).price_market
    changed = 0

    ygo_dir = os.path.join(root, 'collections')
    if os.path.isdir(ygo_dir):
        persistence = PersistenceManager(data_dir=ygo_dir, decks_dir=os.path.join(root, 'decks'))
        for filename in persistence.list_collections():
            try:
                path = persistence.collection_path(filename)
                with path_lock(path):  # load→save without a page saving in between
                    collection = persistence.load_collection(filename)
                    if _reprice(collection, get_source, 'yugioh', market):
                        persistence.save_collection(collection, filename)
                        bump(path)  # open pages reload instead of saving an older copy
                        changed += 1
            except Exception as exc:
                logger.error('Auto reprice skipped %s/%s: %s', root, filename, exc)

    from src.services.catalog import game_ids

    store = GameCollectionStore(lambda: root)
    for game in game_ids():
        if game == 'yugioh':
            continue
        for filename in store.list(game):
            try:
                path = store.path(game, filename)
                with path_lock(path):
                    collection = store.load(game, filename)
                    if _reprice(collection, get_source, game, market):
                        store.save(game, collection, filename)
                        bump(path)
                        changed += 1
            except Exception as exc:
                logger.error('Auto reprice skipped %s/%s/%s: %s', root, game, filename, exc)
    return changed


def run_daily(now: datetime, base: str = 'data', all_sources=None,
              get_source: Optional[Callable] = None) -> dict:
    roots = account_roots(base)
    summary = {'refreshed': [], 'errors': {}, 'repriced': 0}
    for source in due_sources(now, markets_in_use(roots), all_sources):
        name = f'{source.game}-{source.market}'
        try:
            count = source.refresh()
            summary['refreshed'].append(name)
            logger.info('Prices %s refreshed: %s printings', name, count)
        except Exception as exc:
            summary['errors'][name] = str(exc)
            logger.error('Prices %s failed: %s', name, exc)
    if summary['refreshed']:
        for root in roots:
            try:
                summary['repriced'] += auto_reprice(root, get_source=get_source)
            except Exception as exc:
                logger.error('Auto reprice failed for %s: %s', root, exc)
    return summary


async def _loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_daily, datetime.now().astimezone())
        except Exception as exc:  # never let the loop die
            logger.error('Price scheduler error: %s', exc)
        await asyncio.sleep(CHECK_EVERY_SECONDS)


_task: Optional[asyncio.Task] = None


def start_scheduler() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop())
