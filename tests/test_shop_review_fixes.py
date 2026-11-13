"""Behaviour pinned after the review of the shop back office (customers, buylist, consignment, kiosk)."""

import pytest

from src.core.account_profile import AccountProfile, save_profile
from src.core.sales_models import Discount, OutOfStock, spoken
from src.core.shop_models import BuylistRules
from src.services.sales.checkout import SaleError
from src.services.shop import kiosk
from src.services.shop.buylist import BuyError, Offer, offer_cents
from src.services.shop.consignment import ConsignmentError
from src.services.shop.customers import CustomerError
from src.services.shop.kiosk import KioskClosed, KioskError, KioskOrders, Throttle, Visit
from tests.test_sales_services import find, qty, shop  # noqa: F401  (fixture)
from tests.test_shop_buylist import RAGAVAN, desk, ragavan  # noqa: F401  (fixture)
from tests.test_shop_kiosk import card

SECRET = r'C:\inetpub\data\users\ana\shop\ledger.json'


@pytest.fixture(autouse=True)
def fresh_index():
    kiosk.forget()
    yield
    kiosk.forget()


# --- the counter keeps control of the kiosk queue --------------------------------------------

def test_the_counter_can_discard_a_list(tmp_path):
    orders = KioskOrders(str(tmp_path))
    spam = orders.add('zzz', [card()])
    real = orders.add('Marta', [card()])
    orders.discard(spam.id)
    assert [o.id for o in orders.open()] == [real.id]
    with pytest.raises(KioskError):
        orders.discard(spam.id)


def test_looking_at_a_list_leaves_it_waiting(tmp_path):
    orders = KioskOrders(str(tmp_path))
    order = orders.add('Marta', [card()])
    assert orders.get(order.id).code == order.code
    assert [o.id for o in orders.open()] == [order.id]
    with pytest.raises(KioskError):
        orders.get('nope')


def test_a_visit_sends_at_most_three_lists():
    visit = Visit()
    for _ in range(3):
        visit.check()
        visit.sent()
    with pytest.raises(KioskError):
        visit.check()


def test_one_address_cannot_flood_the_counter():
    throttle = Throttle(limit=2, seconds=600)
    throttle.spend('shop-a|1.2.3.4', now=0)
    throttle.spend('shop-a|1.2.3.4', now=10)
    with pytest.raises(KioskError):
        throttle.spend('shop-a|1.2.3.4', now=20)
    throttle.spend('shop-a|5.6.7.8', now=20)   # somebody else is not affected
    throttle.spend('shop-a|1.2.3.4', now=601)  # the oldest one has aged out


# --- a closed kiosk stops working on pages already open --------------------------------------

def open_shop(root):
    save_profile(AccountProfile(shop_mode=True), str(root))
    return kiosk.enable(str(root))


def test_an_open_kiosk_passes_the_check(tmp_path):
    token = open_shop(tmp_path)
    kiosk.ensure_open(token, str(tmp_path))


def test_switching_the_kiosk_off_closes_open_pages(tmp_path):
    token = open_shop(tmp_path)
    kiosk.disable(str(tmp_path))
    with pytest.raises(KioskClosed):
        kiosk.ensure_open(token, str(tmp_path))


def test_a_new_link_closes_pages_opened_with_the_old_one(tmp_path):
    token = open_shop(tmp_path)
    fresh = kiosk.enable(str(tmp_path))
    with pytest.raises(KioskClosed):
        kiosk.ensure_open(token, str(tmp_path))
    kiosk.ensure_open(fresh, str(tmp_path))


def test_leaving_shop_mode_closes_open_pages(tmp_path):
    token = open_shop(tmp_path)
    save_profile(AccountProfile(shop_mode=False), str(tmp_path))
    with pytest.raises(KioskClosed):
        kiosk.ensure_open(token, str(tmp_path))


def test_closed_is_a_kiosk_error_a_visitor_can_read():
    assert issubclass(KioskClosed, KioskError)


# --- only words written for people reach the screen ------------------------------------------

def test_spoken_keeps_messages_written_for_people():
    assert spoken(CustomerError('Ese cliente no existe.'), 'x') == 'Ese cliente no existe.'
    assert spoken(SaleError('a'), 'x') == spoken(BuyError('a'), 'x') == spoken(KioskError('a'), 'x') == 'a'
    assert spoken(ConsignmentError('a'), 'x') == 'a'
    line = card()
    assert spoken(OutOfStock(line, 0), 'x') == str(OutOfStock(line, 0))


def test_spoken_hides_everything_else():
    assert spoken(OSError(13, 'Permission denied', SECRET), 'No se pudo guardar.') == 'No se pudo guardar.'
    assert spoken(CustomerError(''), 'No se pudo guardar.') == 'No se pudo guardar.'


def broken(*args, **kwargs):
    raise OSError(13, 'Permission denied', SECRET)


def test_a_failed_purchase_does_not_show_file_paths(desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(desk.customers, 'post', broken)
    with pytest.raises(BuyError) as error:
        desk.buying.buy([ragavan(1, paid=2600)], 'credit', 'EUR', customer_id=desk.ana.id)
    assert 'ledger.json' not in str(error.value) and 'inetpub' not in str(error.value)
    assert str(error.value) == 'No se pudo guardar la compra.'
    assert qty(desk, 'Ragavan') == 2


def test_a_failed_cancellation_does_not_show_file_paths(desk, monkeypatch):  # noqa: F811
    purchase = desk.buying.buy([ragavan(1, paid=2600)], 'credit', 'EUR', customer_id=desk.ana.id)
    monkeypatch.setattr(desk.customers, 'post', broken)
    with pytest.raises(BuyError) as error:
        desk.buying.cancel(purchase.id)
    assert str(error.value) == 'No se pudo anular la compra.'


def test_a_failed_credit_sale_does_not_show_file_paths(desk, monkeypatch):  # noqa: F811
    desk.customers.post(desk.ana.id, 'credit', 9000, 'Compra')
    line = find(desk.inventory.items(['yugioh', 'magic']), 'Ragavan').model_copy(update={'quantity': 1})
    monkeypatch.setattr(desk.customers, 'post', broken)
    with pytest.raises(SaleError) as error:
        desk.checkout.charge([line], Discount(), 'credit', 'EUR', customer_id=desk.ana.id)
    assert str(error.value) == 'No se pudo descontar el saldo de tienda.'
    assert qty(desk, 'Ragavan') == 2


def test_an_unreadable_balance_does_not_show_file_paths(desk, monkeypatch):  # noqa: F811
    line = find(desk.inventory.items(['yugioh', 'magic']), 'Ragavan').model_copy(update={'quantity': 1})
    monkeypatch.setattr(desk.customers, 'balance', broken)
    with pytest.raises(SaleError) as error:
        desk.checkout.charge([line], Discount(), 'credit', 'EUR', customer_id=desk.ana.id)
    assert 'inetpub' not in str(error.value) and str(error.value)


def test_messages_for_the_counter_still_come_through(desk):  # noqa: F811
    with pytest.raises(BuyError) as error:
        desk.buying.buy([ragavan(1)], 'credit', 'EUR', customer_id='nobody')
    assert str(error.value) == 'Elige el cliente que recibe el saldo.'


# --- a purchase line is priced for the condition it records ----------------------------------

RULES = BuylistRules(cash_percent=50, credit_percent=65, min_offer_cents=0)


def test_the_basket_prices_the_condition_it_writes_down():
    from src.ui.buylist import basket_entry

    near_mint = Offer(RAGAVAN.printings[0], 'foil', 4000, offer_cents(4000, RULES, 'cash', 'Near Mint'),
                      offer_cents(4000, RULES, 'credit', 'Near Mint'))
    entry = basket_entry(RAGAVAN, near_mint, 'cash', 'Played', 'magic.json', RULES)
    assert entry['condition'] == 'Played'
    assert entry['cents'] == offer_cents(4000, RULES, 'cash', 'Played') == 1200  # not the Near Mint 2000
    assert (entry['quantity'], entry['collection'], entry['card'], entry['offer']) == (
        1, 'magic.json', RAGAVAN, near_mint)
    assert basket_entry(RAGAVAN, near_mint, 'credit', 'Near Mint', 'magic.json', RULES)['cents'] == 2600


def test_a_card_without_market_price_enters_the_basket_unpriced():
    from src.ui.buylist import basket_entry

    unpriced = Offer(RAGAVAN.printings[0], 'foil', 0, 0, 0)
    assert basket_entry(RAGAVAN, unpriced, 'cash', 'Played', 'magic.json', RULES)['cents'] == 0


# --- a consignment debt can be put right ------------------------------------------------------

def in_debt(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 20)
    blue = find(desk.inventory.items(['yugioh', 'magic']), 'Blue-Eyes', condition='Near Mint').model_copy(
        update={'quantity': 1})
    sale = desk.checkout.charge([blue], Discount(), 'card', 'EUR')
    desk.book.pay_out(desk.ana.id, 'cash')
    desk.checkout.refund(sale.id)
    return desk.customers.balance(desk.ana.id, 'consignment')


def test_a_consignment_debt_can_be_written_off_with_a_reason(desk):  # noqa: F811
    debt = in_debt(desk)
    assert debt == -2000
    assert desk.book.write_off(desk.ana.id, 'Devolvió el efectivo') == 2000
    assert desk.customers.balance(desk.ana.id, 'consignment') == 0
    entry = desk.customers.entries(desk.ana.id, 'consignment')[0]
    assert entry.cents == 2000 and 'Devolvió el efectivo' in entry.reason


def test_writing_off_needs_a_reason_and_a_debt(desk):  # noqa: F811
    with pytest.raises(ConsignmentError):
        desk.book.write_off(desk.ana.id, 'Nada que regularizar')
    in_debt(desk)
    for reason in ('', '   ', None):
        with pytest.raises(ConsignmentError):
            desk.book.write_off(desk.ana.id, reason)
    assert desk.customers.balance(desk.ana.id, 'consignment') == -2000
