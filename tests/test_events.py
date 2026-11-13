import random

import pytest

from src.core.event_models import Event, Match, Player, Round
from src.services.events.store import EventError, EventStore
from src.services.events.swiss import pair, standings


def people(*names):
    return [Player(id=name.lower(), name=name) for name in names]


def played(*results):
    """One round from (a, b, result) triples; b '' is a bye."""
    return Round(matches=[Match(a=a, b=b, result=result) for a, b, result in results])


def faced(rounds):
    return [frozenset((m.a, m.b)) for r in rounds for m in r.matches if m.b]


# --- pairing ------------------------------------------------------------------------------------

def test_first_round_pairs_everybody_once():
    matches = pair(people('Ana', 'Berta', 'Carla', 'Dani'), [], random.Random(1))
    assert len(matches) == 2 and all(m.b and m.result == '' for m in matches)
    assert sorted(p for m in matches for p in (m.a, m.b)) == ['ana', 'berta', 'carla', 'dani']


def test_an_odd_field_gives_one_bye_that_counts_as_a_win():
    matches = pair(people('Ana', 'Berta', 'Carla'), [], random.Random(1))
    byes = [m for m in matches if not m.b]
    assert len(matches) == 2 and len(byes) == 1 and byes[0].result == 'a'


def test_the_bye_goes_to_the_last_player_who_has_not_had_one():
    players = people('Ana', 'Berta', 'Carla')
    first = played(('ana', 'berta', 'a'), ('carla', '', 'a'))          # ana 3, carla 3 (bye), berta 0
    matches = pair(players, [first], random.Random(1))
    (bye,) = [m for m in matches if not m.b]
    assert bye.a == 'berta'
    second = played(('ana', 'carla', 'a'), ('berta', '', 'a'))         # ana 6, carla 3, berta 3: both had a bye
    (bye,) = [m for m in pair(players, [first, second], random.Random(1)) if not m.b]
    assert bye.a == 'ana'                                               # the only one without it, even leading


def test_nobody_gets_two_byes_while_somebody_has_none():
    players = people('A', 'B', 'C', 'D', 'E')
    rounds, rng = [], random.Random(7)
    for _ in range(5):
        matches = pair(players, rounds, rng)
        for match in matches:
            match.result = match.result or rng.choice(['a', 'b', 'draw'])
        rounds.append(Round(matches=matches))
    byes = [m.a for r in rounds for m in r.matches if not m.b]
    assert sorted(byes) == ['a', 'b', 'c', 'd', 'e']


def test_players_meet_by_points_and_do_not_repeat_while_possible():
    players = people('Ana', 'Berta', 'Carla', 'Dani')
    first = played(('ana', 'berta', 'a'), ('carla', 'dani', 'a'))
    second = pair(players, [first], random.Random(3))
    assert {frozenset((m.a, m.b)) for m in second} == {frozenset(('ana', 'carla')), frozenset(('berta', 'dani'))}


def test_no_rematch_in_any_round_a_field_allows():
    players = people(*'ABCDEFGH')
    rounds, rng = [], random.Random(11)
    for _ in range(5):
        matches = pair(players, rounds, rng)
        for match in matches:
            match.result = rng.choice(['a', 'b', 'draw'])
        rounds.append(Round(matches=matches))
    assert len(faced(rounds)) == len(set(faced(rounds))) == 20


def test_a_rematch_is_allowed_only_when_there_is_no_other_way():
    players = people('Ana', 'Berta')
    first = played(('ana', 'berta', 'a'))
    (again,) = pair(players, [first], random.Random(1))
    assert {again.a, again.b} == {'ana', 'berta'}


def test_dropped_players_are_never_paired():
    players = people('Ana', 'Berta', 'Carla', 'Dani')
    players[1].dropped = True
    matches = pair(players, [], random.Random(1))
    assert 'berta' not in [p for m in matches for p in (m.a, m.b)]
    assert len(matches) == 2 and sum(1 for m in matches if not m.b) == 1


def test_pairing_a_big_field_does_not_hang():
    players = [Player(id=str(n), name=f'P{n}') for n in range(129)]
    rounds, rng = [], random.Random(5)
    for _ in range(8):
        matches = pair(players, rounds, rng)
        for match in matches:
            match.result = match.result or rng.choice(['a', 'b'])
        rounds.append(Round(matches=matches))
    assert all(len(r.matches) == 65 for r in rounds)


# --- standings ----------------------------------------------------------------------------------

def test_standings_give_three_one_and_nothing():
    event = Event(name='Liga', players=people('Ana', 'Berta', 'Carla', 'Dani'), rounds=[
        played(('ana', 'berta', 'a'), ('carla', 'dani', 'draw'))])
    table = {row.name: row for row in standings(event)}
    assert [table[n].points for n in ('Ana', 'Berta', 'Carla', 'Dani')] == [3, 0, 1, 1]
    assert (table['Ana'].wins, table['Berta'].losses, table['Carla'].draws) == (1, 1, 1)
    assert [row.name for row in standings(event)] == ['Ana', 'Carla', 'Dani', 'Berta']


def test_ties_break_on_the_opponents_win_rate_then_the_name():
    event = Event(name='Liga', players=people('Ana', 'Berta', 'Carla', 'Dani'), rounds=[
        played(('ana', 'berta', 'a'), ('carla', 'dani', 'a')),
        played(('ana', 'carla', 'a'), ('dani', 'berta', 'a'))])
    rows = standings(event)
    # carla (3) lost to ana (2-0, 100 %) and beat dani (1-1, 50 %): 75 %.  dani (3) lost to carla (50 %), beat berta (floor 33 %)
    assert [row.name for row in rows] == ['Ana', 'Carla', 'Dani', 'Berta']
    by = {row.name: row for row in rows}
    assert by['Carla'].opponents == pytest.approx(0.75) and by['Dani'].opponents == pytest.approx((0.5 + 1 / 3) / 2)


def test_a_bye_is_a_win_but_not_an_opponent():
    event = Event(name='Liga', players=people('Ana', 'Berta', 'Carla'), rounds=[
        played(('ana', 'berta', 'a'), ('carla', '', 'a'))])
    by = {row.name: row for row in standings(event)}
    assert by['Carla'].points == 3 and by['Carla'].opponents == 0 and by['Carla'].byes == 1
    assert [row.name for row in standings(event)] == ['Ana', 'Carla', 'Berta']   # ana has a real opponent rate


def test_unreported_matches_count_for_nothing_and_dropped_players_stay_listed():
    players = people('Ana', 'Berta')
    players[1].dropped = True
    event = Event(name='Liga', players=players, rounds=[played(('ana', 'berta', ''))])
    rows = standings(event)
    assert [row.points for row in rows] == [0, 0] and rows[1].dropped


# --- the book of events --------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return EventStore(str(tmp_path))


def running(store, *names, seed=1):
    event = store.create('Liga semanal', 'yugioh', '2026-11-20')
    for name in names:
        store.enter(event.id, name)
    return store.start(event.id, random.Random(seed))


def test_an_event_is_created_open_and_listed_newest_first(store):
    old = store.create('Liga', 'yugioh', '2026-11-01', fee_cents=500, capacity=8)
    new = store.create('  Presentación  ', 'magic', '2026-12-01')
    assert (old.status, old.fee_cents, old.capacity, new.name) == ('open', 500, 8, 'Presentación')
    assert [e.id for e in store.all()] == [new.id, old.id]
    assert store.get(old.id).name == 'Liga'


def test_creating_refuses_nonsense(store):
    for args in (('', 'yugioh', '2026-11-01'), ('Liga', 'yugioh', 'mañana'), ('Liga', 'yugioh', '2026-11-01', -1),
                 ('Liga', 'yugioh', '2026-11-01', 0, -3)):
        with pytest.raises(EventError):
            store.create(*args)
    assert store.all() == []


def test_players_enter_while_it_is_open_and_there_is_room(store):
    event = store.create('Liga', 'yugioh', '2026-11-20', capacity=2)
    store.enter(event.id, 'Ana', customer_id='c1')
    with pytest.raises(EventError, match='ya está'):
        store.enter(event.id, ' ana ')
    with pytest.raises(EventError, match='nombre'):
        store.enter(event.id, '  ')
    store.enter(event.id, 'Berta')
    with pytest.raises(EventError, match='lleno'):
        store.enter(event.id, 'Carla')
    event = store.start(event.id, random.Random(1))
    with pytest.raises(EventError, match='inscripciones'):
        store.enter(event.id, 'Dani')
    assert [(p.name, p.customer_id) for p in store.get(event.id).players] == [('Ana', 'c1'), ('Berta', '')]


def test_paid_is_marked_by_hand(store):
    event = store.create('Liga', 'yugioh', '2026-11-20', fee_cents=500)
    ana = store.enter(event.id, 'Ana').players[0]
    assert not ana.paid
    assert store.set_paid(event.id, ana.id, True).players[0].paid
    assert not store.set_paid(event.id, ana.id, False).players[0].paid


def test_dropping_before_the_start_takes_the_player_off_the_list(store):
    event = store.create('Liga', 'yugioh', '2026-11-20')
    ana = store.enter(event.id, 'Ana').players[0]
    assert store.drop(event.id, ana.id).players == []


def test_starting_needs_two_players_and_pairs_the_first_round(store):
    event = store.create('Liga', 'yugioh', '2026-11-20')
    store.enter(event.id, 'Ana')
    with pytest.raises(EventError, match='dos'):
        store.start(event.id)
    store.enter(event.id, 'Berta')
    event = store.start(event.id, random.Random(1))
    assert event.status == 'running' and len(event.rounds) == 1 and len(event.rounds[0].matches) == 1
    with pytest.raises(EventError):
        store.start(event.id)


def test_the_next_round_waits_for_every_result(store):
    event = running(store, 'Ana', 'Berta', 'Carla', 'Dani')
    with pytest.raises(EventError, match='Faltan'):
        store.next_round(event.id)
    store.report(event.id, 0, 'a')
    store.report(event.id, 1, 'draw')
    event = store.next_round(event.id, random.Random(2))
    assert len(event.rounds) == 2 and all(m.result == '' for m in event.rounds[1].matches)


def test_results_of_the_current_round_can_be_corrected_but_not_older_ones(store):
    event = running(store, 'Ana', 'Berta')
    store.report(event.id, 0, 'a')
    assert store.report(event.id, 0, 'b').rounds[0].matches[0].result == 'b'
    assert store.report(event.id, 0, '').rounds[0].matches[0].result == ''
    store.report(event.id, 0, 'draw')
    store.next_round(event.id, random.Random(1))
    event = store.report(event.id, 0, 'a')
    assert event.rounds[0].matches[0].result == 'draw' and event.rounds[1].matches[0].result == 'a'


def test_reporting_refuses_nonsense(store):
    event = running(store, 'Ana', 'Berta', 'Carla')
    bye = next(i for i, m in enumerate(event.rounds[0].matches) if not m.b)
    for table, result in ((bye, 'b'), (9, 'a'), (-1, 'a'), (1 - bye, 'gana')):
        with pytest.raises(EventError):
            store.report(event.id, table, result)


def test_a_player_dropped_mid_round_loses_the_open_match_and_is_not_paired_again(store):
    event = running(store, 'Ana', 'Berta', 'Carla', 'Dani')
    match = event.rounds[0].matches[0]
    store.drop(event.id, match.a)
    event = store.get(event.id)
    assert event.rounds[0].matches[0].result == 'b'
    assert next(p for p in event.players if p.id == match.a).dropped
    store.report(event.id, 1, 'a')
    event = store.next_round(event.id, random.Random(1))
    assert match.a not in [p for m in event.rounds[1].matches for p in (m.a, m.b)]
    assert sum(1 for m in event.rounds[1].matches if not m.b) == 1


def test_a_dropped_player_keeps_a_result_already_reported(store):
    event = running(store, 'Ana', 'Berta')
    store.report(event.id, 0, 'a')
    winner = event.rounds[0].matches[0].a
    assert store.drop(event.id, winner).rounds[0].matches[0].result == 'a'


def test_no_new_round_with_fewer_than_two_players_left(store):
    event = running(store, 'Ana', 'Berta')
    store.drop(event.id, event.players[0].id)
    with pytest.raises(EventError, match='dos'):
        store.next_round(event.id)


def test_finishing_waits_for_results_and_closes_the_event(store):
    event = running(store, 'Ana', 'Berta')
    with pytest.raises(EventError, match='Faltan'):
        store.finish(event.id)
    store.report(event.id, 0, 'a')
    assert store.finish(event.id).status == 'finished'
    for action in (lambda: store.report(event.id, 0, 'b'), lambda: store.next_round(event.id),
                   lambda: store.drop(event.id, event.players[0].id)):
        with pytest.raises(EventError):
            action()


def test_removing_an_event_and_asking_for_one_that_is_not_there(store):
    event = store.create('Liga', 'yugioh', '2026-11-20')
    store.remove(event.id)
    assert store.all() == [] and store.get(event.id) is None
    with pytest.raises(EventError, match='no existe'):
        store.enter(event.id, 'Ana')


def test_a_damaged_file_is_not_written_over(store, tmp_path):
    store.create('Liga', 'yugioh', '2026-11-20')
    path = tmp_path / 'shop' / 'events.json'
    path.write_text('{ roto', encoding='utf-8')
    with pytest.raises(EventError, match='events.json'):
        store.create('Otra', 'yugioh', '2026-11-21')
    assert path.read_text(encoding='utf-8') == '{ roto'


def test_rounds_have_a_ceiling(store):
    event = running(store, 'Ana', 'Berta')
    from src.services.events.store import MAX_ROUNDS

    for _ in range(MAX_ROUNDS - 1):
        store.report(event.id, 0, 'a')
        store.next_round(event.id, random.Random(1))
    store.report(event.id, 0, 'a')
    with pytest.raises(EventError, match='rondas'):
        store.next_round(event.id)


def test_a_player_dropped_by_mistake_can_come_back_for_the_next_round(store):
    event = running(store, 'Ana', 'Berta', 'Carla', 'Dani')
    gone = event.rounds[0].matches[0].a
    store.drop(event.id, gone)
    assert not next(p for p in store.drop(event.id, gone, dropped=False).players if p.id == gone).dropped
    store.report(event.id, 1, 'a')
    event = store.next_round(event.id, random.Random(1))
    assert gone in [p for m in event.rounds[1].matches for p in (m.a, m.b)]


def test_a_result_sent_from_a_screen_showing_an_older_round_is_refused(store):
    event = running(store, 'Ana', 'Berta', 'Carla', 'Dani')
    store.report(event.id, 0, 'a', 1)
    store.report(event.id, 1, 'draw', 1)
    store.next_round(event.id, random.Random(2))
    with pytest.raises(EventError, match='ronda'):
        store.report(event.id, 0, 'b', 1)
    event = store.report(event.id, 0, 'b', 2)
    assert event.rounds[0].matches[0].result == 'a' and event.rounds[1].matches[0].result == 'b'


def test_the_page_says_which_round_each_result_belongs_to():
    from pathlib import Path
    assert 'store.report, event.id, t, e.value or \'\', len(event.rounds)' in Path('src/ui/events.py').read_text(encoding='utf-8')
