"""Tell the page when its save was refused because the collection changed elsewhere.

Every page saves through ``run.io_bound``, so wrapping it once covers them all: the
user sees why the change was not kept and the page reloads with the current data.
"""

from __future__ import annotations

import contextlib
import functools
import logging

from src.core.collection_sync import StaleCollectionError

logger = logging.getLogger(__name__)
_MARKER = '_openyugi_stale_notice'


def _notify_and_reload() -> None:
    from nicegui import ui

    ui.notify(str(StaleCollectionError()), type='warning', timeout=6000)
    ui.timer(2.0, ui.navigate.reload, once=True)


def install_stale_save_notice(run=None, on_stale=_notify_and_reload) -> None:
    if run is None:
        from nicegui import run
    if getattr(run.io_bound, _MARKER, False):
        return
    original = run.io_bound

    @functools.wraps(original)
    async def io_bound(callback, *args, **kwargs):
        try:
            return await original(callback, *args, **kwargs)
        except StaleCollectionError:
            try:
                on_stale()
            except Exception:  # no page to tell (background task, closed tab)
                logger.warning('A stale save was refused with no page to notify', exc_info=True)
            raise

    setattr(io_bound, _MARKER, True)
    run.io_bound = io_bound


def current_page():
    """The page whose handler is running, or None outside one."""
    from nicegui import ui

    try:
        return ui.context.client
    except RuntimeError:
        return None


@contextlib.contextmanager
def page_context(page):
    """Run UI calls of a background task inside ``page`` (tasks start without one)."""
    if page is None:
        yield
    else:
        with page:
            yield
