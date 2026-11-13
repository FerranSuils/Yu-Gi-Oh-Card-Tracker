from pathlib import Path

from src.core.account_profile import AccountProfile, ShopProfile
from src.core.order_models import Address, Order, OrderLine
from src.services.orders.book import Pick

HOSTILE = '<img src=x onerror=alert(1)>'


def order(**changes) -> Order:
    values = dict(
        number=7, channel='cardmarket', external_id='9001', customer_name='Ana Ruiz', email='ana@example.test',
        address=Address(name='Ana Ruiz', line1='Calle Mayor 1', postcode='08001', city='Barcelona', country='ES'),
        lines=[OrderLine(name='Blue-Eyes White Dragon', set_code='LOB-EN001', rarity='Ultra Rare', quantity=2,
                         unit_cents=2500, collection='vitrina.json', storage_location='Caja A'),
               OrderLine(kind='custom', name='Dark Hole (LOB-EN052)', quantity=1, unit_cents=300, unlinked=True)],
        shipping_name='Correos', carrier='Correos', shipping_cents=145, total_cents=5445, status='paid',
        note='Sin sobre acolchado')
    values.update(changes)
    return Order(**values)


# --- navigation and routes -------------------------------------------------------------------

def test_orders_only_show_in_shop_mode_after_the_counter_pages():
    from src.ui.layout import SHOP_ROUTES, menu_routes, nav_items

    plain = dict((route, label) for label, route in nav_items(AccountProfile()))
    assert '/pedidos' not in plain
    shop_nav = dict((route, label) for label, route in nav_items(AccountProfile(shop_mode=True)))
    assert shop_nav['/pedidos'] == 'Pedidos'
    assert menu_routes(shop_nav)[:7] == ['/', '/tpv', '/ventas', '/compras', '/clientes', '/consigna', '/pedidos']
    assert '/pedidos' in SHOP_ROUTES


def test_orders_are_private_and_registered():
    from src.services.auth_middleware import is_public_path

    assert not is_public_path('/pedidos')
    assert "@ui.page('/pedidos')" in Path('main.py').read_text(encoding='utf-8')


def test_icons_are_self_hosted():
    from src.ui.orders import ICONS

    assert ICONS
    for name in ICONS:
        assert Path('static/icons', f'{name}.svg').is_file(), name


# --- what may be done with an order ----------------------------------------------------------

def test_each_status_offers_only_its_own_steps():
    from src.services.orders.paper import next_steps

    assert next_steps(order(status='new')) == ['paid', 'cancel']
    assert next_steps(order(status='paid')) == ['packed', 'ship', 'cancel']
    assert next_steps(order(status='packed')) == ['ship', 'cancel']
    assert next_steps(order(status='shipped')) == ['delivered', 'return']
    assert next_steps(order(status='delivered')) == ['return']
    assert next_steps(order(status='cancelled')) == [] and next_steps(order(status='returned')) == []


def test_views_split_the_book():
    from src.services.orders.paper import VIEWS, in_view

    book = [order(status=status, number=n) for n, status in enumerate(
        ('new', 'paid', 'packed', 'shipped', 'delivered', 'cancelled', 'returned'), start=1)]
    assert [o.status for o in in_view(book, 'open')] == ['new', 'paid', 'packed']
    assert [o.status for o in in_view(book, 'shipped')] == ['shipped']
    assert [o.status for o in in_view(book, 'closed')] == ['delivered', 'cancelled', 'returned']
    assert in_view(book, 'all') == book and in_view(book, 'nonsense') == book
    assert list(VIEWS) == ['open', 'shipped', 'closed', 'all']


def test_a_search_finds_orders_by_label_reference_buyer_or_card():
    from src.services.orders.paper import matching

    book = [order(), order(number=8, external_id='77', customer_name='Bo', email='bo@example.test', lines=[OrderLine(name='Raigeki')])]
    assert [o.number for o in matching(book, 'p00007')] == [7]
    assert [o.number for o in matching(book, '77')] == [8]
    assert [o.number for o in matching(book, 'ana')] == [7]
    assert [o.number for o in matching(book, 'raigeki')] == [8]
    assert matching(book, '  ') == book


# --- paper -----------------------------------------------------------------------------------

def test_the_slip_says_who_what_and_how_it_travels():
    from src.services.orders.paper import slip_html

    html = slip_html(order(), ShopProfile(name='Cartas Sol', address='Rambla 5', city='Reus', email='hola@sol.test'))
    for text in ('Cartas Sol', 'Rambla 5', 'P00007', 'Cardmarket', '9001', 'Ana Ruiz', 'Calle Mayor 1',
                 '08001 Barcelona', 'Blue-Eyes White Dragon', 'LOB-EN001', 'Dark Hole (LOB-EN052)', 'Correos',
                 'Sin sobre acolchado', '54,45'):
        assert text in html, text
    assert 'class="oy-slip"' in html


def test_the_slip_escapes_everything_a_stranger_wrote():
    from src.services.orders.paper import slip_html

    hostile = order(
        customer_name=HOSTILE, external_id=HOSTILE, note=HOSTILE, shipping_name=HOSTILE, carrier=HOSTILE,
        address=Address(name=HOSTILE, line1=HOSTILE, city=HOSTILE, country=HOSTILE),
        lines=[OrderLine(kind='custom', name=HOSTILE, set_code=HOSTILE, rarity=HOSTILE, unlinked=True)])
    html = slip_html(hostile, ShopProfile(name=HOSTILE, address=HOSTILE, email=HOSTILE))
    assert '<img' not in html and '&lt;img' in html


def test_the_pick_sheet_lists_piles_and_escapes_them():
    from src.services.orders.paper import picks_html

    html = picks_html([
        Pick(name='Blue-Eyes White Dragon', set_code='LOB-EN001', game='yugioh', collection='vitrina.json',
             storage_location='Caja A', condition='Near Mint', language='EN', first_edition=True, quantity=3,
             orders=['P00007', 'P00008']),
        Pick(name=HOSTILE, set_code=HOSTILE, game='magic', collection=HOSTILE, storage_location=HOSTILE,
             condition='Played', language='DE', first_edition=False, quantity=1, orders=['P00009'])])
    for text in ('Blue-Eyes White Dragon', 'LOB-EN001', 'Caja A', 'vitrina', '3', 'P00007, P00008', '1.ª'):
        assert text in html, text
    assert '<img' not in html and 'class="oy-slip"' in html
    assert 'No hay' in picks_html([])


# --- connected online shops ------------------------------------------------------------------

SHOP_TOKEN = 'shpat_0123456789abcdef0123456789abWXYZ'


def test_channel_icons_are_self_hosted_and_orders_can_sync():
    from src.ui.orders import ICONS as ORDER_ICONS
    from src.ui.settings_channels import ICONS

    assert ICONS and 'refresh-cw' in ORDER_ICONS
    for name in ICONS:
        assert Path('static/icons', f'{name}.svg').is_file(), name


def test_settings_show_the_online_shops_section():
    text = Path('src/ui/settings.py').read_text(encoding='utf-8')
    assert 'render_channels_section()' in text


def test_a_shop_that_is_not_connected_says_so():
    from src.ui.settings_channels import channel_status_text

    assert channel_status_text(None) == 'Sin conectar'
    assert channel_status_text({}) == 'Sin conectar'


def test_a_connected_shop_shows_where_and_the_last_four_only(tmp_path):
    from src.services.orders.channels import ChannelSettings
    from src.ui.settings_channels import channel_status_text

    settings = ChannelSettings(str(tmp_path))
    settings.save_shopify('cartas-sol.myshopify.com', SHOP_TOKEN)
    text = channel_status_text(settings.summary()['shopify'])
    assert 'cartas-sol.myshopify.com' in text and '····WXYZ' in text
    assert 'sin sincronizar todavía' in text
    assert SHOP_TOKEN not in text and SHOP_TOKEN[:-4] not in text
    settings.stamp('shopify')
    assert 'última sincronización' in channel_status_text(settings.summary()['shopify'])


def test_a_strange_date_does_not_break_the_status():
    from src.ui.settings_channels import channel_status_text

    text = channel_status_text({'where': 'https://tienda.example', 'last4': 'abcd', 'connected_at': 'ayer',
                                'synced_at': 'nunca'})
    assert text.startswith('Conectada · https://tienda.example · clave ····abcd')


def test_only_connected_shops_that_are_due_sync_on_their_own(tmp_path):
    from src.services.orders.channels import ChannelSettings
    from src.services.orders.sync import due_channels

    clock = {'now': 1_000_000.0}
    settings = ChannelSettings(str(tmp_path), now=lambda: clock['now'])
    assert due_channels(settings) == []
    settings.save_shopify('cartas-sol.myshopify.com', SHOP_TOKEN)
    assert due_channels(settings) == ['shopify']
    settings.stamp('shopify')
    assert due_channels(settings) == []
    clock['now'] += 10 * 60
    assert due_channels(settings) == ['shopify']


def test_the_sync_summary_says_what_happened_to_the_stock():
    from src.services.orders.sync import SyncReport
    from src.ui.settings_channels import sync_lines

    assert sync_lines(SyncReport()) == ['El stock de la tienda ya estaba al día.']
    lines = sync_lines(SyncReport(updated=3, missing=2))
    assert lines[0] == 'Stock actualizado en 3 productos de la tienda.'
    assert '2 pilas' in lines[1] and 'SKU' in lines[1]
    assert sync_lines(SyncReport(updated=1))[0] == 'Stock actualizado en 1 producto de la tienda.'
    failed = sync_lines(SyncReport(push_error='Shopify no acepta ese token.'))
    assert failed == ['No se pudo enviar el stock: Shopify no acepta ese token. Se reintentará en la próxima '
                      'sincronización.']


def test_the_sync_button_is_named_after_the_shop():
    from src.ui.settings_channels import sync_label

    assert sync_label('shopify') == 'Sincronizar Shopify'
    assert sync_label('woocommerce') == 'Sincronizar WooCommerce'
