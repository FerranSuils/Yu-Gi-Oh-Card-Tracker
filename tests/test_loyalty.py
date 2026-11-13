import os

import pytest

from src.core.sales_models import Discount
from src.core.shop_models import LoyaltyRules
from src.services.sales.checkout import Checkout
from src.services.shop.customers import CustomerError, CustomerStore
from src.services.shop.loyalty import Loyalty, points_for
from tests.test_sales_services import find, shop  # noqa: F401  (fixture)

GAMES = ['yugioh', 'magic']
ON = LoyaltyRules(enabled=True)


@pytest.fixture
def club(shop):
    shop.customers = CustomerStore(str(shop.root))
    shop.loyalty = Loyalty(str(shop.root), shop.customers)
    shop.checkout = Checkout(shop.inventory, shop.store, customers=shop.customers, loyalty=shop.loyalty)
    shop.ana = shop.customers.add('Ana')
    shop.loyalty.save_rules(ON)
    return shop


def sell(club, method='cash', customer=True, quantity=1):
    blue = find(club.inventory.items(GAMES), 'Blue-Eyes', condition='Near Mint').model_copy(
        update={'quantity': quantity})
    return club.checkout.charge([blue], Discount(), method, 'EUR', received_cents=10_000 if method == 'cash' else None,
                                customer_id=club.ana.id if customer else None)


# --- the sum -----------------------------------------------------------------------------------

def test_points_are_the_whole_units_charged_times_the_rate():
    assert points_for(2599, ON) == 25
    assert points_for(99, ON) == 0
    assert points_for(2500, LoyaltyRules(enabled=True, points_per_unit=2.5)) == 62
    assert points_for(1000, LoyaltyRules(enabled=True, points_per_unit=0.1)) == 1


def test_rules_refuse_nonsense():
    for bad in ({'points_per_unit': -1}, {'points_per_unit': float('nan')}, {'points_per_unit': 5000},
                {'redeem_points': 0}, {'redeem_cents': 0}):
        with pytest.raises(ValueError):
            LoyaltyRules(**bad)


def test_rules_are_off_until_somebody_turns_them_on(shop):
    loyalty = Loyalty(str(shop.root), CustomerStore(str(shop.root)))
    assert loyalty.rules() == LoyaltyRules() and not loyalty.rules().enabled
    loyalty.save_rules(LoyaltyRules(enabled=True, points_per_unit=2, redeem_points=50, redeem_cents=200))
    assert Loyalty(str(shop.root), None).rules().redeem_cents == 200


# --- earning -----------------------------------------------------------------------------------

def test_a_paid_sale_with_a_customer_gives_points(club):
    sale = sell(club)
    assert sale.status == 'paid' and sale.note == ''
    assert club.customers.points(club.ana.id) == 25
    (entry,) = club.customers.entries(club.ana.id, 'points')
    assert (entry.cents, entry.ref) == (25, sale.id) and sale.label in entry.reason


def test_no_points_without_a_customer_or_with_the_programme_off(club):
    sell(club, customer=False)
    club.loyalty.save_rules(LoyaltyRules())
    sell(club)
    assert club.customers.points(club.ana.id) == 0


def test_what_is_paid_with_store_credit_gives_no_points(club):
    club.customers.post(club.ana.id, 'credit', 5000, 'Regalo')
    sale = sell(club, method='credit')
    assert sale.status == 'paid'
    assert club.customers.points(club.ana.id) == 0


def test_points_are_given_once_per_sale(club):
    sale = sell(club)
    assert club.loyalty.earn(sale) == 0
    assert club.customers.points(club.ana.id) == 25


def test_points_do_not_touch_the_money_balances(club):
    sell(club)
    assert club.customers.balance(club.ana.id, 'credit') == 0
    assert club.customers.balances()[club.ana.id] == {'credit': 0, 'consignment': 0, 'points': 25}


def test_a_customer_with_only_points_can_still_be_deleted(club):
    sell(club)
    club.customers.remove(club.ana.id)
    assert club.customers.get(club.ana.id) is None


# --- refunds -----------------------------------------------------------------------------------

def test_a_refund_takes_back_the_points_the_sale_gave(club):
    sale = sell(club)
    club.checkout.refund(sale.id)
    assert club.customers.points(club.ana.id) == 0
    club.loyalty.reverse(club.store.get(sale.id))   # twice does nothing more
    assert club.customers.points(club.ana.id) == 0


def test_a_refund_after_redeeming_leaves_the_points_negative(club):
    sale = sell(club, quantity=3)     # 75 points
    club.loyalty.save_rules(LoyaltyRules(enabled=True, redeem_points=50, redeem_cents=100))
    assert club.loyalty.redeem(club.ana.id) == (50, 100)
    club.checkout.refund(sale.id)
    assert club.customers.points(club.ana.id) == -50


def test_a_refund_takes_points_back_even_with_the_programme_off(club):
    sale = sell(club)
    club.loyalty.save_rules(LoyaltyRules())
    club.checkout.refund(sale.id)
    assert club.customers.points(club.ana.id) == 0


# --- redeeming ---------------------------------------------------------------------------------

def test_redeeming_swaps_whole_blocks_of_points_for_store_credit(club):
    club.customers.post(club.ana.id, 'points', 250, 'Bienvenida')
    assert club.loyalty.redeem(club.ana.id) == (200, 200)
    assert club.customers.points(club.ana.id) == 50
    assert club.customers.balance(club.ana.id, 'credit') == 200


def test_redeeming_needs_a_whole_block_and_the_programme_on(club):
    club.customers.post(club.ana.id, 'points', 99, 'Bienvenida')
    with pytest.raises(CustomerError, match='99'):
        club.loyalty.redeem(club.ana.id)
    club.customers.post(club.ana.id, 'points', 1, 'Bienvenida')
    club.loyalty.save_rules(LoyaltyRules())
    with pytest.raises(CustomerError, match='apagad'):
        club.loyalty.redeem(club.ana.id)
    assert club.customers.points(club.ana.id) == 100 and club.customers.balance(club.ana.id, 'credit') == 0


def test_redeeming_writes_both_movements_or_none(club, monkeypatch):
    club.customers.post(club.ana.id, 'points', 100, 'Bienvenida')
    import src.services.shop.customers as module

    def refuse(path, items):
        raise OSError('disk full')

    monkeypatch.setattr(module, 'write_list', refuse)
    with pytest.raises(OSError):
        club.loyalty.redeem(club.ana.id)
    monkeypatch.undo()
    assert club.customers.points(club.ana.id) == 100 and club.customers.balance(club.ana.id, 'credit') == 0


def test_redeeming_for_nobody_is_refused(club):
    with pytest.raises(CustomerError, match='no existe'):
        club.loyalty.redeem('nadie')


# --- when the book cannot be written -----------------------------------------------------------

def test_a_sale_stands_when_its_points_cannot_be_written(club, monkeypatch):
    monkeypatch.setattr(club.loyalty, 'earn', lambda sale: (_ for _ in ()).throw(OSError('held')))
    sale = sell(club)
    assert sale.status == 'paid' and 'Puntos sin anotar' in sale.note
    assert 'Puntos sin anotar' in club.store.get(sale.id).note


def test_a_refund_stands_when_its_points_cannot_be_taken_back(club, monkeypatch):
    sale = sell(club)
    monkeypatch.setattr(club.loyalty, 'reverse', lambda sale: (_ for _ in ()).throw(OSError('held')))
    refunded = club.checkout.refund(sale.id)
    assert refunded.status == 'refunded' and 'Puntos sin descontar' in refunded.note


def test_damaged_rules_are_not_read_as_defaults(club):
    with open(os.path.join(str(club.root), 'shop', 'loyalty.json'), 'w', encoding='utf-8') as file:
        file.write('{ roto')
    with pytest.raises(CustomerError, match='loyalty.json'):
        club.loyalty.rules()
    sale = sell(club)
    assert sale.status == 'paid' and 'Puntos sin anotar' in sale.note


# --- the desk and the screens ------------------------------------------------------------------

def test_the_desk_gives_points_at_the_till(club):
    from src.services.shop.desk import desk_for

    desk = desk_for(str(club.root), 'EUR')
    desk.loyalty.save_rules(ON)
    ana = desk.customers.add('Berta')
    blue = find(desk.inventory.items(GAMES), 'Blue-Eyes', condition='Near Mint').model_copy(update={'quantity': 1})
    desk.checkout.charge([blue], Discount(), 'card', 'EUR', customer_id=ana.id)
    assert desk.customers.points(ana.id) == 25


def test_screens_name_points_and_their_icons_exist():
    from src.core.shop_models import LEDGER_LABELS
    from src.ui.customers import ICONS, amount_text
    from src.ui.settings_shop import ICONS as SETTINGS_ICONS, render_loyalty_section

    assert LEDGER_LABELS['points'] == 'Puntos' and callable(render_loyalty_section)
    assert amount_text('points', 25, 'EUR') == '+25 pts' and amount_text('points', -5, 'EUR') == '−5 pts'
    assert amount_text('credit', 250, 'EUR').startswith('+2,50')
    for name in ICONS + SETTINGS_ICONS:
        assert os.path.exists(os.path.join('static', 'icons', f'{name}.svg')), name
