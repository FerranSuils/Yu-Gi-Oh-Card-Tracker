import asyncio
import contextvars
from pathlib import Path

import types

from src.core.io_context import install_context_aware_io_bound

probe: contextvars.ContextVar[str | None] = contextvars.ContextVar('probe', default=None)


async def _executor_without_context(callback, *args, **kwargs):
    # Same behaviour as NiceGUI's io_bound: run_in_executor does not copy context.
    return await asyncio.get_running_loop().run_in_executor(None, lambda: callback(*args, **kwargs))


def _fake_run_module():
    return types.SimpleNamespace(io_bound=_executor_without_context)


def test_io_bound_sees_the_callers_context():
    # NiceGUI keeps the request (and so app.storage.user) in a ContextVar. Without this,
    # worker threads resolved the primary account and read/wrote its collections.
    run = _fake_run_module()

    async def scenario():
        probe.set('kkdbb')
        before = await run.io_bound(probe.get)
        install_context_aware_io_bound(run)
        return before, await run.io_bound(probe.get)

    assert asyncio.run(scenario()) == (None, 'kkdbb')


def test_install_is_idempotent():
    run = _fake_run_module()
    install_context_aware_io_bound(run)
    first = run.io_bound
    install_context_aware_io_bound(run)
    assert run.io_bound is first


def test_main_installs_it_before_pages():
    source = Path('main.py').read_text(encoding='utf-8')
    assert 'install_context_aware_io_bound()' in source
    assert source.index('install_context_aware_io_bound()') < source.index("@ui.page('/login')")
