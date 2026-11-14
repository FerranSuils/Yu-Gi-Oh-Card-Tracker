import json
from datetime import datetime, timedelta

import pytest

from src.services.reference.store import ReferenceStore


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 14, 10, 0, 0)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return ReferenceStore(tmp_path, 'demo', now=clock)


def test_upsert_new_changed_same(store, clock):
    assert store.upsert('A', {'x': 1}) == 'new'
    assert store.upsert('A', {'x': 1}) == 'same'
    clock.advance(days=1)
    assert store.upsert('A', {'x': 2}) == 'changed'
    rec = store.get('A')
    assert rec['source'] == 'demo' and rec['key'] == 'A'
    assert rec['data'] == {'x': 2}
    assert rec['fetched_at'] == '2026-11-15T10:00:00'
    assert rec['first_seen'] == '2026-11-14T10:00:00'


def test_same_refreshes_fetched_at_but_logs_no_change(store, clock):
    store.upsert('A', {'x': 1})
    clock.advance(hours=5)
    store.upsert('A', {'x': 1})
    assert store.get('A')['fetched_at'] == '2026-11-14T15:00:00'
    assert len(store.changes()) == 1


def test_persists_to_disk_atomically(tmp_path, clock):
    s = ReferenceStore(tmp_path, 'demo', now=clock)
    s.upsert('A', {'x': 1})
    path = tmp_path / 'demo' / 'records.json'
    assert json.loads(path.read_text('utf-8'))['A']['data'] == {'x': 1}
    assert [p.name for p in (tmp_path / 'demo').iterdir() if p.suffix == '.tmp'] == []
    again = ReferenceStore(tmp_path, 'demo', now=clock)
    assert again.get('A')['data'] == {'x': 1}
    assert again.upsert('A', {'x': 1}) == 'same'


def test_changes_history_since_and_before(store, clock):
    store.upsert('A', {'x': 1})
    clock.advance(days=2)
    store.upsert('A', {'x': 2})
    store.upsert('B', {'y': 1})
    all_ = store.changes()
    assert [(c['key'], c['kind']) for c in all_] == [('B', 'new'), ('A', 'changed'), ('A', 'new')]
    assert all_[1]['before'] == {'x': 1}
    recent = store.changes(since=datetime(2026, 11, 15))
    assert {c['key'] for c in recent} == {'A', 'B'} and len(recent) == 2


def test_history_is_capped(tmp_path, clock):
    s = ReferenceStore(tmp_path, 'demo', now=clock, max_changes=5)
    for i in range(12):
        s.upsert(f'k{i}', {'i': i})
    assert len(s.changes()) == 5
    assert s.changes()[0]['key'] == 'k11'


def test_all_and_len(store):
    store.upsert('A', 1)
    store.upsert('B', 2)
    assert {r['key'] for r in store.all()} == {'A', 'B'}
    assert len(store) == 2
    assert store.get('missing') is None


def test_upsert_many_summary(store):
    store.upsert('A', {'x': 1})
    summary = store.upsert_many({'A': {'x': 2}, 'B': {'y': 1}})
    assert summary == {'new': ['B'], 'changed': ['A'], 'same': []}


def test_rejects_unsafe_source_name(tmp_path):
    with pytest.raises(ValueError):
        ReferenceStore(tmp_path, '../evil')


def test_rejects_non_json_data(store):
    with pytest.raises(TypeError):
        store.upsert('A', {'x': object()})


def test_corrupt_file_is_not_silently_overwritten(tmp_path, clock):
    d = tmp_path / 'demo'
    d.mkdir()
    (d / 'records.json').write_text('{broken', 'utf-8')
    with pytest.raises(ValueError):
        ReferenceStore(tmp_path, 'demo', now=clock)
