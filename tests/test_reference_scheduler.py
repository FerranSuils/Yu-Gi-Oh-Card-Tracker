from datetime import datetime, timedelta

from src.services.reference import scheduler
from src.services.reference.errors import SourceUnavailable
from src.services.reference.store import ReferenceStore


def test_refresh_all_isolates_errors(tmp_path):
    def ok(store):
        return {'new': ['A'], 'changed': [], 'same': []}

    def blocked(store):
        raise SourceUnavailable('bloqueado')

    result = scheduler.refresh_all(tmp_path, adapters={'good': ok, 'bad': blocked})
    assert result['good'] == {'new': ['A'], 'changed': [], 'same': []}
    assert result['bad'] == {'error': 'bloqueado'}


def test_is_due_when_never_fetched_or_stale(tmp_path):
    now = datetime(2026, 11, 14, 12)
    assert scheduler.is_due(tmp_path, now)
    store = ReferenceStore(tmp_path, 'ygoprodeck_sets', now=lambda: now - timedelta(hours=3))
    store.upsert('X', {})
    assert not scheduler.is_due(tmp_path, now)
    assert scheduler.is_due(tmp_path, now + timedelta(hours=30))
