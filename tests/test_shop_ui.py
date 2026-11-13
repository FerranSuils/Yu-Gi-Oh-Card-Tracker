from pathlib import Path

import pytest

from src.core.account_profile import AccountProfile, load_profile, save_profile
from src.core.pricing_models import PriceQuote, PrintingPrice
from src.core.sales_models import Discount
from src.core.shop_models import BuylistRules
from src.services.shop.consignment import ConsignmentError
from tests.test_sales_services import find, shop  # noqa: F401  (fixture)
from tests.test_shop_buylist import RAGAVAN, desk  # noqa: F401  (fixture)


# --- navigation and routes -------------------------------------------------------------------

def test_back_office_pages_only_show_in_shop_mode():
    from src.ui.layout import menu_routes, nav_items

    plain = dict((route, label) for label, route in nav_items(AccountProfile()))
    assert not {'/clientes', '/compras', '/consigna'} & set(plain)
    shop_nav = dict((route, label) for label, route in nav_items(AccountProfile(shop_mode=True)))
    assert (shop_nav['/clientes'], shop_nav['/compras'], shop_nav['/consigna']) == ('Clientes', 'Compras', 'Consigna')
    assert menu_routes(shop_nav)[:6] == ['/', '/tpv', '/ventas', '/compras', '/clientes', '/consigna']


def test_only_the_kiosk_is_public():
    from src.services.auth_middleware import is_public_path

    assert is_public_path('/kiosko/' + 'a' * 32)
    for private in ('/kiosko', '/clientes', '/compras', '/consigna', '/kiosko-admin/x'):
        assert not is_public_path(private)


def test_routes_are_registered():
    main = Path('main.py').read_text(encoding='utf-8')
    for route in ("@ui.page('/clientes')", "@ui.page('/compras')", "@ui.page('/consigna')",
                  "@ui.page('/kiosko/{token}')"):
        assert route in main


def test_icons_are_self_hosted():
    from src.ui.buylist import ICONS as buying
    from src.ui.consignment import ICONS as consigning
    from src.ui.customers import ICONS as customers
    from src.ui.kiosk import ICONS as kiosk

    for name in {*buying, *consigning, *customers, *kiosk}:
        assert Path('static/icons', f'{name}.svg').is_file(), name


# --- the profile -----------------------------------------------------------------------------

def test_the_profile_keeps_the_buying_rules(tmp_path):
    assert AccountProfile().buylist == BuylistRules()
    profile = AccountProfile(buylist=BuylistRules(cash_percent=40, credit_percent=55, min_offer_cents=25))
    save_profile(profile, str(tmp_path))
    assert load_profile(str(tmp_path)).buylist == profile.buylist


# --- customers with cards on consignment -----------------------------------------------------

def test_a_customer_with_cards_on_consignment_cannot_be_removed(desk):  # noqa: F811
    consignment = desk.book.open(desk.ana.id, 'magic', 'magic.json', 20)
    with pytest.raises(ConsignmentError) as error:
        desk.book.remove_customer(desk.ana.id)
    assert 'consigna' in str(error.value).lower()
    assert desk.customers.get(desk.ana.id) is not None
    desk.book.close(consignment.id)
    desk.book.remove_customer(desk.ana.id)
    assert desk.customers.get(desk.ana.id) is None


# --- an account's desk without anybody signed in ---------------------------------------------

def test_the_desk_reads_the_account_it_is_given(shop):  # noqa: F811
    from src.services.shop.desk import desk_for

    desk = desk_for(str(shop.root))  # noqa: F811
    assert len(desk.inventory.items(['yugioh', 'magic'])) == 4
    assert desk.inventory.collections('yugioh') == ['vitrina.json']
    assert desk.inventory.collections('magic') == ['magic.json']
    assert desk.inventory.collections('pokemon') == []
    ana = desk.customers.add('Ana')
    desk.customers.post(ana.id, 'credit', 5000, 'Regalo')
    ragavan = find(desk.inventory.items(['magic']), 'Ragavan').model_copy(update={'quantity': 1})
    sale = desk.checkout.charge([ragavan], Discount(), 'credit', 'EUR', None, ana.id)
    assert sale.total_cents == 4000 and desk.customers.balance(ana.id, 'credit') == 1000
    assert find(shop.inventory.items(['magic']), 'Ragavan').quantity == 1
    order = desk.orders.add('Marta', [find(desk.inventory.items(['yugioh']), 'Dark Magician')])
    assert [o.id for o in desk.orders.open()] == [order.id]
    assert desk.purchases.all() == [] and desk.book.all() == []


def test_two_accounts_have_separate_desks(shop, tmp_path):  # noqa: F811
    from src.services.shop.desk import desk_for

    other = tmp_path / 'users' / 'bob'
    other.mkdir(parents=True)
    assert desk_for(str(other)).inventory.items(['yugioh', 'magic']) == []
    assert len(desk_for(str(shop.root)).inventory.items(['yugioh', 'magic'])) == 4


# --- what the shop offers for a card ---------------------------------------------------------

class Prices:
    def __init__(self, prices):
        self.prices = prices

    def get(self, printing_id):
        return self.prices.get(printing_id)


def test_offers_list_every_finish_the_shop_would_buy():
    from src.services.shop.buylist import offers

    source = Prices({'p1': PrintingPrice(normal=PriceQuote(trend=10.0), foil=PriceQuote(trend=40.0))})
    rows = offers(RAGAVAN, source, BuylistRules())
    assert [(row.finish, row.market_cents, row.cash_cents, row.credit_cents) for row in rows] == [
        ('nonfoil', 1000, 500, 650), ('foil', 4000, 2000, 2600)]
    assert rows[0].printing.printing_id == 'p1'
    played = offers(RAGAVAN, source, BuylistRules(), condition='Played')
    assert [(row.cash_cents, row.credit_cents) for row in played] == [(300, 390), (1200, 1560)]


def test_no_price_or_too_cheap_means_no_offer():
    from src.services.shop.buylist import offers

    assert offers(RAGAVAN, Prices({}), BuylistRules()) == []
    assert offers(RAGAVAN, None, BuylistRules()) == []
    cheap = Prices({'p1': PrintingPrice(normal=PriceQuote(trend=0.1))})
    assert offers(RAGAVAN, cheap, BuylistRules(min_offer_cents=50)) == []
