"""Make ``nicegui.run.io_bound`` run its callback inside the caller's context.

NiceGUI keeps the current request, and so ``app.storage.user``, in a ContextVar.
``run.io_bound`` uses ``loop.run_in_executor``, which does not copy context, so
every call resolved no account and fell back to the primary account's folder: a
registered account's background loads and saves read and wrote the primary
account's collections. Copying the context fixes every call site at once.
"""

from __future__ import annotations

import contextvars
import functools

_MARKER = '_openyugi_context_aware'


def install_context_aware_io_bound(run=None) -> None:
    if run is None:
        from nicegui import run
    if getattr(run.io_bound, _MARKER, False):
        return
    original = run.io_bound

    @functools.wraps(original)
    async def io_bound(callback, *args, **kwargs):
        context = contextvars.copy_context()
        return await original(functools.partial(context.run, callback, *args, **kwargs))

    setattr(io_bound, _MARKER, True)
    run.io_bound = io_bound
