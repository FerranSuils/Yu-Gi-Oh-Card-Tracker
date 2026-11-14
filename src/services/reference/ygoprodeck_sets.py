"""YGOPRODeck set list (public JSON API) as the working source of release dates.

``cardsets.php`` lists every TCG set with its release date, including sets
announced for the future, so it provides "próximos lanzamientos" and the set
novelties that cardcluster.es cannot provide to a non-browser client.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Callable, Optional

from src.services.reference.errors import ParseError, SourceUnavailable
from src.services.reference.http import polite_get
from src.services.reference.store import ReferenceStore

SOURCE = 'ygoprodeck_sets'
URL = 'https://db.ygoprodeck.com/api/v7/cardsets.php'
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def parse_cardsets(payload) -> dict[str, dict]:
    """Normalise the API list into ``{set_code: {...}}`` or raise ParseError."""
    if not isinstance(payload, list) or not payload:
        raise ParseError('YGOPRODeck: se esperaba una lista no vacía de sets.')
    rows: dict[str, dict] = {}
    for item in payload:
        if not isinstance(item, dict) or not item.get('set_code') or not item.get('set_name'):
            raise ParseError(f'YGOPRODeck: set sin set_code/set_name: {str(item)[:80]!r}')
        tcg_date = item.get('tcg_date')
        if tcg_date is not None and not (isinstance(tcg_date, str) and _DATE.match(tcg_date)):
            raise ParseError(f'YGOPRODeck: fecha no válida {tcg_date!r} en {item["set_code"]}')
        count = item.get('num_of_cards')
        rows[str(item['set_code'])] = {
            'set_code': str(item['set_code']),
            'name': str(item['set_name']),
            'num_of_cards': count if isinstance(count, int) else None,
            'tcg_date': tcg_date,
            'image': item.get('set_image') if isinstance(item.get('set_image'), str) else None,
        }
    return rows


def refresh(store: ReferenceStore, get: Optional[Callable] = None) -> dict:
    """Download the set list and store it. Returns ``{'new': [...], 'changed': [...], 'same': [...]}``."""
    get = get or (lambda url, **kw: polite_get(url, 'db.ygoprodeck.com', **kw))
    response = get(URL, headers={'User-Agent': 'OpenYuGi/1.0'})
    if response.status_code != 200:
        raise SourceUnavailable(f'YGOPRODeck respondió HTTP {response.status_code}.')
    try:
        payload = response.json()
    except ValueError as exc:
        raise ParseError('YGOPRODeck: la respuesta no es JSON.') from exc
    return store.upsert_many(parse_cardsets(payload))


def upcoming(store: ReferenceStore, today: Optional[date] = None) -> list[dict]:
    """Sets with a release date today or later, soonest first."""
    cutoff = (today or date.today()).isoformat()
    sets = [r['data'] for r in store.all() if r['data'].get('tcg_date') and r['data']['tcg_date'] >= cutoff]
    return sorted(sets, key=lambda s: (s['tcg_date'], s['set_code']))


def recent_changes(store: ReferenceStore, since: Optional[datetime] = None, limit: int = 10) -> list[dict]:
    """Newest additions/changes with the current data attached: ``{at, kind, key, data, before?}``."""
    out = []
    for change in store.changes(since):
        record = store.get(change['key'])
        if record is None:
            continue
        out.append({**change, 'data': record['data']})
        if len(out) >= limit:
            break
    return out
