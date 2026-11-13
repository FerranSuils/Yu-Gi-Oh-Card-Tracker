from pathlib import Path

import pytest

from src.core.account_profile import AccountProfile, ShopProfile
from src.core.sales_models import Discount, Sale, SaleLine


def pile(name='Dark Magician', stock=3, cents=999, **extra):
    return SaleLine(game='yugioh', collection='main.json', card_id='46986414', name=name, set_code='LOB-EN005',
                    rarity='Ultra Rare', variant_id='v1', quantity=stock, unit_cents=cents, **extra)


# --- ticket ----------------------------------------------------------------------------------

def test_ticket_adds_one_copy_and_stacks_the_same_pile():
    from src.services.sales.ticket import Ticket

    ticket = Ticket()
    assert ticket.add(pile()) is None
    assert ticket.add(pile()) is None
    assert [(line.name, line.quantity) for line in ticket.lines] == [('Dark Magician', 2)]
    assert ticket.subtotal == 1998


def test_ticket_never_holds_more_than_the_pile():
    from src.services.sales.ticket import Ticket

    ticket = Ticket()
    ticket.add(pile(stock=1))
    assert 'solo hay 1' in ticket.add(pile(stock=1))
    assert ticket.lines[0].quantity == 1
    ticket.set_quantity(0, 9)
    assert ticket.lines[0].quantity == 1
    ticket.set_quantity(0, 0)
    assert ticket.lines[0].quantity == 1
    assert ticket.stock(0) == 1


def test_ticket_keeps_different_piles_apart():
    from src.services.sales.ticket import Ticket

    ticket = Ticket()
    ticket.add(pile())
    ticket.add(pile(condition='Played'))
    assert len(ticket.lines) == 2


def test_ticket_price_and_custom_line():
    from src.services.sales.ticket import Ticket

    ticket = Ticket()
    ticket.add(pile(cents=0))
    assert ticket.blocker() == 'Pon precio a: Dark Magician.'
    ticket.set_price(0, '2,50')
    assert ticket.lines[0].unit_cents == 250 and ticket.blocker() is None
    with pytest.raises(ValueError):
        ticket.set_price(0, 'gratis')
    ticket.add_custom(' Fundas ', '3.00', 2)
    assert (ticket.lines[1].kind, ticket.lines[1].name, ticket.lines[1].quantity) == ('custom', 'Fundas', 2)
    assert ticket.stock(1) is None
    ticket.set_quantity(1, 40)
    assert ticket.lines[1].quantity == 40
    with pytest.raises(ValueError, match='nombre'):
        ticket.add_custom('  ', '1')
    with pytest.raises(ValueError, match='precio'):
        ticket.add_custom('Sobre', '0')


def test_ticket_discount_and_total():
    from src.services.sales.ticket import Ticket

    ticket = Ticket()
    assert ticket.blocker() == 'El ticket está vacío.'
    ticket.add(pile(cents=1000))
    ticket.set_discount('percent', '10')
    assert (ticket.subtotal, ticket.discount_cents, ticket.total) == (1000, 100, 900)
    ticket.set_discount('amount', '2,5')
    assert ticket.total == 750
    ticket.set_discount('amount', '50')
    assert ticket.total == 0 and ticket.blocker() == 'El descuento deja el ticket a cero.'
    with pytest.raises(ValueError):
        ticket.set_discount('percent', '120')
    with pytest.raises(ValueError):
        ticket.set_discount('amount', 'x')
    ticket.set_discount('none', '')
    assert ticket.discount == Discount()
    ticket.remove(0)
    assert ticket.lines == []


# --- receipt, QR, day report -------------------------------------------------------------------

def sale(**extra):
    data = dict(number=7, created_at='2026-11-12T10:00:00+00:00', paid_at='2026-11-12T10:00:05+00:00',
                lines=[SaleLine(name='Dark <b>Magician</b>', set_code='LOB-EN005', quantity=2, unit_cents=999)],
                discount=Discount(kind='percent', value=10), subtotal_cents=1998, discount_cents=200,
                total_cents=1798, currency='EUR', method='cash', status='paid', received_cents=2000,
                change_cents=202)
    data.update(extra)
    return Sale(**data)


def test_receipt_shows_the_sale_and_escapes_text():
    from src.services.sales.receipt import receipt_html

    shop = ShopProfile(name='Cartas <script>', address='Calle 1', city='Barcelona', email='t@t.es')
    html = receipt_html(sale(), shop)
    assert '<script>' not in html and 'Cartas &lt;script&gt;' in html
    assert 'Dark &lt;b&gt;Magician&lt;/b&gt;' in html
    for text in ('000007', 'Calle 1', 'Barcelona', '19,98 €', '−2,00 €', '17,98 €', 'Efectivo', '20,00 €',
                 '2,02 €', 'LOB-EN005'):
        assert text in html, text


def test_receipt_marks_refunds_and_never_shows_stripe_data():
    from src.services.sales.receipt import receipt_html

    html = receipt_html(sale(status='refunded', refunded_at='2026-11-12T11:00:00+00:00', method='stripe',
                             stripe_session='cs_test_secret', stripe_url='https://checkout.stripe.com/c/x',
                             received_cents=None, change_cents=None), ShopProfile())
    assert 'Devuelta' in html and 'cs_test_secret' not in html and 'checkout.stripe.com' not in html


def test_qr_is_inline_svg_for_stripe_links_only():
    from src.services.sales.receipt import qr_svg

    svg = qr_svg('https://checkout.stripe.com/c/pay/cs_test_1')
    assert svg.startswith('<svg') and '<script' not in svg and 'http://' not in svg.replace(
        'http://www.w3.org/2000/svg', '')
    with pytest.raises(ValueError):
        qr_svg('javascript:alert(1)')


def test_days_group_sales_and_count_only_money_kept():
    from src.services.sales.receipt import days

    sales = [sale(), sale(number=8, method='card', total_cents=500),
             sale(number=9, status='refunded', total_cents=300),
             sale(number=None, status='pending', method='stripe', total_cents=900),
             sale(number=3, created_at='2026-11-10T09:00:00+00:00', method='stripe', total_cents=100)]
    report = days(sales, utc_offset_hours=0)
    assert [day.date for day in report] == ['2026-11-12', '2026-11-10']
    assert report[0].total_cents == 1798 + 500
    assert report[0].by_method == {'cash': 1798, 'card': 500}
    assert len(report[0].sales) == 4 and report[0].count == 2
    assert report[1].by_method == {'stripe': 100}


def test_days_use_the_local_day():
    from src.services.sales.receipt import days

    late = sale(created_at='2026-11-12T23:30:00+00:00')
    assert days([late], utc_offset_hours=1)[0].date == '2026-11-13'


# --- navigation and routes -------------------------------------------------------------------

def test_counter_and_sales_only_show_in_shop_mode():
    from src.ui.layout import menu_routes, nav_items

    plain = dict((route, label) for label, route in nav_items(AccountProfile()))
    assert '/tpv' not in plain and '/ventas' not in plain
    shop = dict((route, label) for label, route in nav_items(AccountProfile(shop_mode=True)))
    assert (shop['/tpv'], shop['/ventas']) == ('Mostrador', 'Ventas')
    assert menu_routes(shop)[:3] == ['/', '/tpv', '/ventas']
    assert menu_routes({}) == ['/', '/import', '/csv', '/db_editor', '/settings']


def test_routes_exist_and_only_the_thank_you_page_is_public():
    from src.services.auth_middleware import is_public_path

    main = Path('main.py').read_text(encoding='utf-8')
    for route in ("@ui.page('/tpv')", "@ui.page('/ventas')", "@ui.page('/tpv/pagado')"):
        assert route in main
    assert is_public_path('/tpv/pagado')
    assert not is_public_path('/tpv') and not is_public_path('/ventas') and not is_public_path('/tpv/pagado/x')


def test_icons_are_self_hosted():
    for name in ('cash-register', 'credit-card', 'qr-payment', 'printer-device', 'receipt', 'undo', 'x', 'check',
                 'link', 'cash-payment'):
        assert Path('static/icons', f'{name}.svg').is_file()


def test_segno_is_a_declared_dependency():
    assert 'segno' in Path('requirements.txt').read_text(encoding='utf-8')


# --- page helpers ----------------------------------------------------------------------------

def test_success_url_prefers_the_configured_public_address(monkeypatch):
    from src.ui.pos import success_url

    monkeypatch.delenv('OPENYUGI_PUBLIC_URL', raising=False)
    assert success_url({'x-forwarded-host': 'tienda.test', 'x-forwarded-proto': 'https'}, 'http://127.0.0.1:8205/') \
        == 'https://tienda.test/tpv/pagado'
    assert success_url({}, 'http://localhost:8205/') == 'http://localhost:8205/tpv/pagado'
    assert success_url({'x-forwarded-host': 'evil.test/x?y', 'x-forwarded-proto': 'https'},
                       'http://localhost:8205/') == 'http://localhost:8205/tpv/pagado'
    monkeypatch.setenv('OPENYUGI_PUBLIC_URL', 'https://tgoct.suils.es/')
    assert success_url({'x-forwarded-host': 'otra.test'}, 'http://x/') == 'https://tgoct.suils.es/tpv/pagado'


def test_pile_text_describes_the_physical_pile():
    from src.ui.pos import pile_text

    line = pile(condition='Played', language='DE', first_edition=True, storage_location='Caja 2')
    assert pile_text(line) == 'LOB-EN005 · Ultra Rare · Played · DE · 1.ª ed. · Caja 2'
    assert pile_text(SaleLine(kind='custom', name='Fundas')) == 'Artículo sin inventario'


def test_failure_text_only_shows_messages_meant_for_people():
    from src.core.sales_models import OutOfStock
    from src.services.sales.checkout import SaleError
    from src.services.sales.stripe_gateway import StripeError
    from src.ui.pos import failure_text

    assert failure_text(SaleError('El ticket está vacío.')) == 'El ticket está vacío.'
    assert failure_text(StripeError('La clave no es válida.')) == 'La clave no es válida.'
    assert 'solo quedan 1' in failure_text(OutOfStock(pile(), 1))
    assert failure_text(OSError(r'C:\data\users\x\sales\2026-11.json')) == \
        'No se pudo completar el cobro. Inténtalo de nuevo.'


def test_key_text_never_contains_the_key():
    from src.ui.settings_games import stripe_status_text

    text = stripe_status_text({'last4': 'a1B2', 'mode': 'test', 'kind': 'restringida',
                               'connected_at': '2026-11-12T10:00:00+00:00'})
    assert text == 'Conectado · clave restringida de pruebas ····a1B2 · desde 12/11/2026'
    assert 'real' in stripe_status_text({'last4': 'zzzz', 'mode': 'live', 'kind': 'secreta', 'connected_at': ''})
    assert stripe_status_text(None) == 'Sin conectar'


def test_ticket_follows_the_shelf_when_stock_changes_under_it():
    from src.services.sales.ticket import Ticket

    ticket = Ticket()
    for _ in range(3):
        ticket.add(pile(stock=3))
    ticket.add(pile(name='Kuriboh', condition='Played', stock=2))
    ticket.add_custom('Fundas', '3')
    changed = ticket.sync([pile(stock=1)])  # two copies were sold elsewhere, Kuriboh is gone
    assert [(line.name, line.quantity) for line in ticket.lines] == [('Dark Magician', 1), ('Fundas', 1)]
    assert changed == ['Dark Magician', 'Kuriboh']
    assert ticket.sync([pile(stock=1)]) == []
