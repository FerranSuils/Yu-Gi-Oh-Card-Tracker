from datetime import datetime, timedelta, timezone

import pytest

from src.core.sales_models import SaleLine
from src.services.shop import kiosk
from src.services.shop.kiosk import KioskError, KioskOrders, fit_to_stock, shelf
from tests.test_sales_services import find, shop  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def fresh_index():
    kiosk.forget()
    yield
    kiosk.forget()


@pytest.fixture
def base(tmp_path):
    (tmp_path / 'users' / 'ana').mkdir(parents=True)
    (tmp_path / 'users' / 'bob').mkdir(parents=True)
    return tmp_path


def card(name='Dark Magician', quantity=1, cents=999, **fields):
    fields = {'collection': 'vitrina.json', 'card_id': '1', 'variant_id': 'v', **fields}
    return SaleLine(name=name, quantity=quantity, unit_cents=cents, **fields)


# --- the secret link -------------------------------------------------------------------------

def test_enabling_gives_a_long_random_token(base):
    token = kiosk.enable(str(base / 'users' / 'ana'))
    assert len(token) == 32 and int(token, 16) >= 0
    assert kiosk.token_of(str(base / 'users' / 'ana')) == token
    assert kiosk.token_of(str(base / 'users' / 'bob')) is None


def test_a_token_leads_to_its_own_account(base):
    ana = kiosk.enable(str(base / 'users' / 'ana'))
    bob = kiosk.enable(str(base / 'users' / 'bob'))
    main = kiosk.enable(str(base))
    assert kiosk.account_for(ana, str(base)) == str(base / 'users' / 'ana')
    assert kiosk.account_for(bob, str(base)) == str(base / 'users' / 'bob')
    assert kiosk.account_for(main, str(base)) == str(base)


@pytest.mark.parametrize('token', ['', 'x', '0' * 32, 'g' * 32, '../../etc', None, 'A' * 31, 5])
def test_unknown_or_malformed_tokens_lead_nowhere(base, token):
    kiosk.enable(str(base / 'users' / 'ana'))
    assert kiosk.account_for(token, str(base)) is None


def test_regenerating_kills_the_old_link(base):
    root = str(base / 'users' / 'ana')
    old = kiosk.enable(root)
    assert kiosk.account_for(old, str(base)) == root  # now cached
    new = kiosk.enable(root)
    assert new != old
    assert kiosk.account_for(old, str(base)) is None
    assert kiosk.account_for(new, str(base)) == root


def test_disabling_closes_the_kiosk(base):
    root = str(base / 'users' / 'ana')
    token = kiosk.enable(root)
    assert kiosk.account_for(token, str(base)) == root
    kiosk.disable(root)
    assert kiosk.token_of(root) is None
    assert kiosk.account_for(token, str(base)) is None


def test_guessing_does_not_rescan_the_disk_every_time(base, monkeypatch):
    kiosk.enable(str(base / 'users' / 'ana'))
    scans = []
    real = kiosk._scan

    def counting(folder):
        scans.append(folder)
        return real(folder)

    monkeypatch.setattr(kiosk, '_scan', counting)
    for guess in range(50):
        assert kiosk.account_for(f'{guess:032x}', str(base)) is None
    assert len(scans) == 1


def test_a_broken_kiosk_file_reads_as_closed(base):
    root = base / 'users' / 'ana'
    (root / 'shop').mkdir()
    (root / 'shop' / 'kiosk.json').write_text('{broken', encoding='utf-8')
    assert kiosk.token_of(str(root)) is None


# --- what the public sees --------------------------------------------------------------------

def test_the_shelf_only_shows_priced_stock(shop):  # noqa: F811
    names = [(line.name, line.condition) for line in shelf(shop.inventory.items(['yugioh', 'magic']))]
    assert ('Blue-Eyes White Dragon', 'Near Mint') in names
    assert ('Blue-Eyes White Dragon', 'Played') not in names  # no price
    assert len(names) == 3


def test_the_shelf_hides_where_the_cards_are_kept(shop):  # noqa: F811
    assert all(line.storage_location is None for line in shelf(shop.inventory.items(['yugioh'])))
    # ... and the original lines are untouched
    assert find(shop.inventory.items(['yugioh']), 'Blue-Eyes', condition='Near Mint').storage_location == 'Caja A'


# --- lists sent to the counter ---------------------------------------------------------------

def test_a_list_gets_a_four_digit_code(tmp_path):
    orders = KioskOrders(str(tmp_path))
    order = orders.add('  Marta  ', [card(quantity=2), card('Blue-Eyes')])
    assert order.name == 'Marta' and len(order.code) == 4 and order.code.isdigit()
    assert [o.id for o in orders.open()] == [order.id]
    assert orders.open()[0].lines[0].quantity == 2


def test_names_are_cleaned_and_cut(tmp_path):
    orders = KioskOrders(str(tmp_path))
    assert orders.add('x' * 90, [card()]).name == 'x' * 40
    assert orders.add('Ma\nr\tta\x00 <b>', [card()]).name == 'Ma r ta <b>'
    for bad in ('', '   ', None, '\n\t'):
        with pytest.raises(KioskError):
            orders.add(bad, [card()])


def test_lists_have_limits(tmp_path):
    orders = KioskOrders(str(tmp_path))
    with pytest.raises(KioskError):
        orders.add('Marta', [])
    with pytest.raises(KioskError):
        orders.add('Marta', [card()] * 61)
    with pytest.raises(KioskError):
        orders.add('Marta', [SaleLine(kind='custom', name='Fundas', unit_cents=500)])
    with pytest.raises(KioskError):
        orders.add('Marta', [card(cents=0)])
    with pytest.raises(KioskError):
        orders.add('Marta', [card(quantity=100)])
    assert orders.open() == []


def test_at_most_thirty_lists_wait_at_the_counter(tmp_path):
    orders = KioskOrders(str(tmp_path))
    codes = {orders.add(f'Cliente {n}', [card()]).code for n in range(30)}
    assert len(codes) == 30  # codes never repeat among waiting lists
    with pytest.raises(KioskError):
        orders.add('Uno más', [card()])
    orders.take(orders.open()[0].id)
    orders.add('Ahora sí', [card()])


def test_lists_expire_after_a_day(tmp_path):
    orders = KioskOrders(str(tmp_path))
    now = datetime.now(timezone.utc)
    old = orders.add('Ayer', [card()], now=now - timedelta(hours=25))
    fresh = orders.add('Hoy', [card()], now=now - timedelta(hours=23))
    assert [o.id for o in orders.open(now=now)] == [fresh.id]
    with pytest.raises(KioskError):
        orders.take(old.id, now=now)


def test_expired_lists_do_not_count_towards_the_limit(tmp_path):
    orders = KioskOrders(str(tmp_path))
    now = datetime.now(timezone.utc)
    for n in range(30):
        orders.add(f'Viejo {n}', [card()], now=now - timedelta(days=2))
    orders.add('Nuevo', [card()], now=now)
    assert [o.name for o in orders.open(now=now)] == ['Nuevo']


def test_taking_a_list_removes_it(tmp_path):
    orders = KioskOrders(str(tmp_path))
    order = orders.add('Marta', [card()])
    assert orders.take(order.id).name == 'Marta'
    assert orders.open() == []
    with pytest.raises(KioskError):
        orders.take(order.id)
    with pytest.raises(KioskError):
        orders.take('nope')


def test_a_broken_orders_file_is_not_overwritten(tmp_path):
    orders = KioskOrders(str(tmp_path))
    orders.add('Marta', [card()])
    path = tmp_path / 'shop' / 'kiosk_orders.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(KioskError):
        orders.add('Otra', [card()])
    assert path.read_text(encoding='utf-8') == '{broken'


# --- from the list to the ticket -------------------------------------------------------------

def test_the_ticket_takes_what_is_still_there(shop):  # noqa: F811
    items = shop.inventory.items(['yugioh', 'magic'])
    blue = find(items, 'Blue-Eyes', condition='Near Mint')
    wanted = [
        blue.model_copy(update={'quantity': 5, 'unit_cents': 1, 'storage_location': None}),  # only 3 left
        find(items, 'Ragavan').model_copy(update={'quantity': 1}),
        card('Gone Card', variant_id='zzz'),
    ]
    lines, short = fit_to_stock(wanted, items)
    assert [(line.name, line.quantity, line.unit_cents) for line in lines] == [
        ('Blue-Eyes White Dragon', 3, 2500), ('Ragavan, Nimble Pilferer', 1, 4000)]
    assert lines[0].storage_location == 'Caja A'  # the real pile, at today's price
    assert short == ['Blue-Eyes White Dragon (pedía 5, quedan 3)', 'Gone Card (ya no queda)']
