from pathlib import Path

from src.core.account_profile import AccountProfile
from src.core.event_models import Event, Match, Player, Round


def test_events_show_in_shop_mode_only():
    from src.ui.layout import SHOP_ROUTES, nav_items

    assert '/eventos' not in dict((route, label) for label, route in nav_items(AccountProfile()))
    shop_nav = dict((route, label) for label, route in nav_items(AccountProfile(shop_mode=True)))
    assert shop_nav['/eventos'] == 'Eventos'
    assert '/eventos' in SHOP_ROUTES


def test_events_are_private_and_registered():
    from src.services.auth_middleware import is_public_path

    assert not is_public_path('/eventos')
    assert "@ui.page('/eventos')" in Path('main.py').read_text(encoding='utf-8')


def test_icons_are_self_hosted():
    from src.ui.events import ICONS

    assert ICONS
    for name in ICONS:
        assert Path('static/icons', f'{name}.svg').is_file(), name


def test_event_errors_are_read_out_to_the_person():
    from src.services.events.store import EventError
    from src.ui.shop_common import shop_failure

    assert shop_failure(EventError('El evento está lleno.'), 'otra cosa') == 'El evento está lleno.'


def test_an_event_is_summed_up_in_one_line():
    from src.ui.events import event_line

    event = Event(name='Liga', game='yugioh', date='2026-11-20', fee_cents=500, capacity=8,
                  players=[Player(name='Ana', paid=True), Player(name='Berta')])
    line = event_line(event, 'EUR')
    assert '20/11/2026' in line and '2 de 8' in line and '5,00' in line and '1 sin pagar' in line
    free = event_line(Event(name='Casual', date='2026-11-20'), 'EUR')
    assert 'Gratis' in free and '0 apuntados' in free and 'sin pagar' not in free


def test_a_table_offers_its_two_players_and_a_draw():
    from src.ui.events import result_options, table_text

    names = {'a1': 'Ana', 'b1': 'Berta'}
    assert result_options(Match(a='a1', b='b1'), names) == {'': 'Sin resultado', 'a': 'Gana Ana', 'b': 'Gana Berta',
                                                            'draw': 'Empate'}
    assert table_text(Match(a='a1', b='b1'), names) == 'Ana — Berta'
    assert table_text(Match(a='a1', result='a'), names) == 'Ana descansa (cuenta como victoria)'
    assert table_text(Match(a='zz', b='b1'), names) == '? — Berta'


def test_the_round_in_play_says_what_is_missing():
    from src.ui.events import round_status

    event = Event(name='Liga', status='running', players=[Player(id='a', name='Ana'), Player(id='b', name='Berta')],
                  rounds=[Round(matches=[Match(a='a', b='b')])])
    assert round_status(event) == 'Ronda 1 · falta 1 resultado'
    event.rounds[0].matches[0].result = 'a'
    assert round_status(event) == 'Ronda 1 · completa'
    assert round_status(Event(name='Liga')) == ''


def test_a_free_event_has_a_fee_of_nothing():
    import pytest

    from src.ui.events import fee_cents

    assert fee_cents('') == 0 and fee_cents('0') == 0 and fee_cents('2,50') == 250
    with pytest.raises(ValueError):
        fee_cents('gratis')
