import json
from datetime import date, datetime
from pathlib import Path

import pytest

from src.services.reference.store import ReferenceStore
from src.services.reference import cardcluster, ygoprodeck_sets
from src.services.reference.errors import SourceUnavailable, ParseError

FIX = Path(__file__).parent / 'fixtures'


class Resp:
    def __init__(self, status=200, text='', payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return self._payload


def fixture_text(name):
    return (FIX / name).read_bytes().decode('utf-8', errors='replace')


# ---- cardcluster -----------------------------------------------------------

def test_cardcluster_shield_challenge_is_reported_as_blocked(tmp_path):
    store = ReferenceStore(tmp_path, 'cardcluster')
    get = lambda url, **kw: Resp(403, fixture_text('cardcluster_shield_challenge.html'))
    with pytest.raises(SourceUnavailable, match='bloquea|desafío|challenge'):
        cardcluster.refresh(store, get=get)
    assert len(store) == 0


def test_cardcluster_spa_shell_has_no_extractable_data(tmp_path):
    store = ReferenceStore(tmp_path, 'cardcluster')
    get = lambda url, **kw: Resp(200, fixture_text('cardcluster_spa_shell.html'))
    with pytest.raises(SourceUnavailable, match='JavaScript'):
        cardcluster.refresh(store, get=get)
    assert len(store) == 0


def test_cardcluster_uses_polite_user_agent(tmp_path):
    seen = {}

    def get(url, **kw):
        seen.update(kw.get('headers', {}))
        return Resp(403, fixture_text('cardcluster_shield_challenge.html'))

    with pytest.raises(SourceUnavailable):
        cardcluster.refresh(ReferenceStore(tmp_path, 'cardcluster'), get=get)
    assert seen['User-Agent'] == 'OpenYuGi/1.0'


# ---- ygoprodeck sets -------------------------------------------------------

def sample():
    return json.loads((FIX / 'ygoprodeck_cardsets_sample.json').read_text('utf-8'))


def test_parse_cardsets_normalises():
    rows = ygoprodeck_sets.parse_cardsets(sample())
    assert 'GLVI' in rows
    assert rows['GLVI'] == {
        'set_code': 'GLVI', 'name': 'Glorious Victors', 'num_of_cards': 3,
        'tcg_date': '2026-12-03', 'image': 'https://images.ygoprodeck.com/images/sets/GLVI.jpg'}
    assert rows['NODT']['tcg_date'] is None


@pytest.mark.parametrize('bad', [{}, 'x', [], [{'foo': 1}], None])
def test_parse_cardsets_rejects_garbage(bad):
    with pytest.raises(ParseError):
        ygoprodeck_sets.parse_cardsets(bad)


def test_parse_cardsets_rejects_bad_date():
    with pytest.raises(ParseError):
        ygoprodeck_sets.parse_cardsets([{'set_name': 'A', 'set_code': 'A', 'tcg_date': '12/03/2026'}])


def test_refresh_stores_and_detects_changes(tmp_path):
    store = ReferenceStore(tmp_path, 'ygoprodeck_sets')
    data = sample()
    summary = ygoprodeck_sets.refresh(store, get=lambda url, **kw: Resp(200, payload=data))
    assert len(summary['new']) == len(data) and summary['changed'] == []
    data[-2]['tcg_date'] = '2027-01-01'  # a delayed release
    summary = ygoprodeck_sets.refresh(store, get=lambda url, **kw: Resp(200, payload=data))
    assert len(summary['changed']) == 1 and summary['new'] == []


def test_refresh_http_error_saves_nothing(tmp_path):
    store = ReferenceStore(tmp_path, 'ygoprodeck_sets')
    with pytest.raises(SourceUnavailable):
        ygoprodeck_sets.refresh(store, get=lambda url, **kw: Resp(503, text='down'))
    with pytest.raises(ParseError):
        ygoprodeck_sets.refresh(store, get=lambda url, **kw: Resp(200, payload={'error': 'x'}))
    assert len(store) == 0


def test_upcoming_sorted_and_recent_changes(tmp_path):
    store = ReferenceStore(tmp_path, 'ygoprodeck_sets', now=lambda: datetime(2026, 11, 14, 8))
    ygoprodeck_sets.refresh(store, get=lambda url, **kw: Resp(200, payload=sample()))
    up = ygoprodeck_sets.upcoming(store, today=date(2026, 11, 14))
    assert [s['set_code'] for s in up] == ['GLVI', 'MZMC']
    assert all(s['tcg_date'] >= '2026-11-14' for s in up)
    recent = ygoprodeck_sets.recent_changes(store, since=datetime(2026, 11, 1), limit=3)
    assert len(recent) == 3 and recent[0]['kind'] == 'new'
    assert recent[0]['data']['set_code']
