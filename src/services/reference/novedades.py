"""View-model for the «Novedades» page: reads only from the local reference store."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from src.services.reference import ygoprodeck_sets
from src.services.reference.store import DEFAULT_ROOT, ReferenceStore

_MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
_KIND = {'new': 'Nuevo', 'changed': 'Cambio de datos'}


def format_date(iso: Optional[str]) -> str:
    if not iso:
        return 'Sin fecha'
    d = date.fromisoformat(iso)
    return f'{d.day} {_MONTHS[d.month - 1]} {d.year}'


def build_view(root=DEFAULT_ROOT, today: Optional[date] = None, recent_days: int = 30,
               limit: int = 12) -> dict:
    """Blocking (reads JSON files): call through run.io_bound from the UI."""
    today = today or date.today()
    store = ReferenceStore(root, ygoprodeck_sets.SOURCE)
    upcoming = []
    for s in ygoprodeck_sets.upcoming(store, today):
        upcoming.append({**s, 'date_label': format_date(s['tcg_date']),
                         'days_left': (date.fromisoformat(s['tcg_date']) - today).days})
    since = datetime.combine(today, datetime.min.time()) - timedelta(days=recent_days)
    recent = []
    for c in ygoprodeck_sets.recent_changes(store, since=since, limit=limit):
        recent.append({'at': c['at'], 'kind': c['kind'], 'set_code': c['data']['set_code'],
                       'name': c['data']['name'], 'tcg_date': c['data']['tcg_date'],
                       'date_label': format_date(c['data']['tcg_date']),
                       'label': _KIND.get(c['kind'], c['kind'])})
    records = store.all()
    last = max((r['fetched_at'] for r in records), default=None)
    return {'upcoming': upcoming, 'recent': recent, 'last_update': last}
