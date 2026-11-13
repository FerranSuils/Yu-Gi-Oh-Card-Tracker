"""Installing the app on a phone or desktop: a manifest, two icons and a service worker that keeps nothing.

The worker exists only so browsers offer "install"; every request still goes to the server, so there is
no stale page and nothing of an account is ever left on a shared device.
"""

from __future__ import annotations

from fastapi import Response
from fastapi.responses import JSONResponse

PAPER = '#f3ede2'

SERVICE_WORKER = """// OpenYuGi: installable, never cached.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
"""

HEAD_HTML = f"""
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="{PAPER}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="OpenYuGi">
<link rel="apple-touch-icon" href="/brand/icon-192.png">
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', () => {{ navigator.serviceWorker.register('/sw.js').catch(() => {{}}); }});
}}
</script>
"""


def manifest() -> dict:
    return {
        'name': 'OpenYuGi',
        'short_name': 'OpenYuGi',
        'description': 'Colección, escáner y tienda de cartas coleccionables.',
        'lang': 'es',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'background_color': PAPER,
        'theme_color': PAPER,
        'icons': [
            {'src': '/brand/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
            {'src': '/brand/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'},
        ],
    }


def register_routes(app) -> None:
    @app.get('/manifest.webmanifest', include_in_schema=False)
    def web_manifest():
        return JSONResponse(manifest(), media_type='application/manifest+json')

    @app.get('/sw.js', include_in_schema=False)
    def service_worker():
        return Response(SERVICE_WORKER, media_type='application/javascript', headers={'Cache-Control': 'no-cache'})
