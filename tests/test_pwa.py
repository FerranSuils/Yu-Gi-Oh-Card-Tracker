from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from src.services.auth_middleware import is_public_path
from src.ui import pwa


def _client():
    app = FastAPI()
    pwa.register_routes(app)
    return TestClient(app)


def test_the_manifest_says_how_the_app_installs():
    manifest = pwa.manifest()
    assert manifest['name'] == 'OpenYuGi'
    assert manifest['short_name'] == 'OpenYuGi'
    assert manifest['display'] == 'standalone'
    assert manifest['start_url'] == '/'
    assert manifest['scope'] == '/'
    assert manifest['background_color'] == '#f3ede2'
    assert manifest['theme_color'] == '#f3ede2'
    assert {icon['sizes'] for icon in manifest['icons']} == {'192x192', '512x512'}
    assert all(icon['type'] == 'image/png' for icon in manifest['icons'])


def test_every_icon_in_the_manifest_is_a_real_square_png_of_that_size():
    for icon in pwa.manifest()['icons']:
        assert icon['src'].startswith('/brand/')
        path = Path('static', icon['src'].lstrip('/'))
        assert path.is_file(), path
        with Image.open(path) as image:
            assert image.format == 'PNG'
            assert f'{image.width}x{image.height}' == icon['sizes']


def test_the_service_worker_keeps_nothing():
    worker = pwa.SERVICE_WORKER
    assert "addEventListener('fetch'" in worker
    assert 'caches' not in worker
    assert 'respondWith' not in worker


def test_every_page_links_the_manifest_and_registers_the_worker():
    head = pwa.HEAD_HTML
    assert '<link rel="manifest" href="/manifest.webmanifest">' in head
    assert '<meta name="theme-color"' in head
    assert 'apple-touch-icon' in head and '/brand/icon-192.png' in head
    assert "navigator.serviceWorker.register('/sw.js')" in head

    from src.ui import theme
    with patch.object(theme.ui, 'add_head_html') as add:
        theme.install_global_styles()
    assert any(call.args[0] == pwa.HEAD_HTML and call.kwargs.get('shared') is True for call in add.call_args_list)


def test_the_manifest_and_the_worker_are_served_to_anybody():
    assert is_public_path('/manifest.webmanifest')
    assert is_public_path('/sw.js')
    assert is_public_path('/brand/icon-192.png')
    client = _client()
    manifest = client.get('/manifest.webmanifest')
    assert manifest.status_code == 200
    assert manifest.headers['content-type'].startswith('application/manifest+json')
    assert manifest.json() == pwa.manifest()
    worker = client.get('/sw.js')
    assert worker.status_code == 200
    assert worker.headers['content-type'].startswith('application/javascript')
    assert worker.headers['cache-control'] == 'no-cache'
    assert worker.text == pwa.SERVICE_WORKER


def test_main_registers_the_routes():
    assert 'pwa.register_routes(app)' in Path('main.py').read_text(encoding='utf-8')
