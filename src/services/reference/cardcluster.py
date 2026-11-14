"""cardcluster.es adapter.

Investigation (2026-11-14): cardcluster.es is a JavaScript single-page app
(empty ``<div id=root>``) behind a Bunny Shield JavaScript challenge that answers
403 to any non-browser client. It publishes no sitemap, RSS or JSON feed that can
be read without running its JavaScript, and getting past the challenge would be
circumventing an anti-bot measure, which this project does not do.

So ``refresh`` fetches the home page once, politely, and raises
``SourceUnavailable`` with a clear reason instead of guessing at a structure it
cannot see. It never stores anything unless real data can be extracted. If the
site ever offers a public feed, add the parser here (pure function + fixture).
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from src.services.reference.errors import SourceUnavailable
from src.services.reference.http import polite_get
from src.services.reference.store import ReferenceStore

SOURCE = 'cardcluster'
HOME_URL = 'https://cardcluster.es/'
_EMPTY_ROOT = re.compile(r'<div id=["\']?root["\']?>\s*</div>', re.I)


def classify(status: int, body: str) -> None:
    """Raise SourceUnavailable if the response carries no readable data."""
    lowered = body.lower()
    if status in (403, 429, 503) and ('bunny-shield' in lowered or 'establishing a secure connection' in lowered):
        raise SourceUnavailable(
            'cardcluster.es bloquea clientes sin navegador con un desafío JavaScript (Bunny Shield, HTTP '
            f'{status}); no se puede leer sin saltarse esa protección.')
    if status != 200:
        raise SourceUnavailable(f'cardcluster.es respondió HTTP {status}.')
    if _EMPTY_ROOT.search(body):
        raise SourceUnavailable(
            'cardcluster.es es una aplicación que requiere JavaScript: el HTML no contiene datos '
            'de lanzamientos ni novedades y no se ha encontrado un feed público.')
    raise SourceUnavailable('cardcluster.es devolvió una estructura no reconocida; no se guarda nada.')


def refresh(store: ReferenceStore, get: Optional[Callable] = None) -> dict:
    """Fetch cardcluster.es and store what can be extracted (currently nothing is extractable)."""
    get = get or (lambda url, **kw: polite_get(url, 'cardcluster.es', **kw))
    response = get(HOME_URL, headers={'User-Agent': 'OpenYuGi/1.0'})
    classify(response.status_code, response.text)
    raise AssertionError('unreachable')  # classify always raises until a parser exists
