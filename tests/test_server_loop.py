import asyncio
from pathlib import Path

from uvicorn.config import Config


def test_windows_server_uses_the_selector_loop():
    # The Proactor accept loop closes the listening socket on WinError 64,
    # which left production alive but deaf (IIS 502 on every page).
    source = Path('main.py').read_text(encoding='utf-8')
    assert "loop='asyncio:SelectorEventLoop' if sys.platform == 'win32' else 'auto'" in source


def test_uvicorn_resolves_the_selector_loop_string():
    factory = Config(app=None, loop='asyncio:SelectorEventLoop').get_loop_factory()
    assert factory is asyncio.SelectorEventLoop


def test_pages_survive_long_event_loop_stalls():
    # A card scan holds the interpreter for several seconds. With NiceGUI's default
    # 3 s reconnect timeout the socket ping (2 s) expires mid-scan, the client is
    # deleted and the scan page reloads while the PDF is still being processed.
    source = Path('main.py').read_text(encoding='utf-8')
    assert 'reconnect_timeout=120.0,' in source
