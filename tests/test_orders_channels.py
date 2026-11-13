import csv
import io
import json
import socket

import pytest

from src.core.sales_models import SaleLine
from src.services.orders.sku import sku_of
from tests.test_sales_services import find, qty, shop  # noqa: F401  (fixture)

GAMES = ['yugioh', 'magic']
TOKEN = 'shpat_0123456789abcdef0123456789abWXYZ'
CK = 'ck_0123456789abcdef0123456789abcdef0123KKKK'
CS = 'cs_0123456789abcdef0123456789abcdef0123SSSS'


def rows(data: bytes):
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


def public(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]


def resolving(*addresses):
    def resolve(host, *args, **kwargs):
        return [(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))
                for address in addresses]
    return resolve


# --- product files ---------------------------------------------------------------------------

def test_the_shopify_file_has_a_product_per_pile_with_its_sku_price_and_stock(shop):  # noqa: F811
    from src.services.orders.channels import shopify_csv

    items = shop.inventory.items(GAMES)
    table = rows(shopify_csv(items))
    assert (len(items), len(table)) == (4, 3)   # the pile without a price stays out
    pile = find(items, 'Blue-Eyes', condition='Near Mint')
    row = next(r for r in table if r['Variant SKU'] == sku_of(pile))
    assert row['Handle'] == sku_of(pile).lower()
    assert 'Blue-Eyes White Dragon' in row['Title'] and 'LOB-EN001' in row['Title']
    assert (row['Variant Price'], row['Variant Inventory Qty']) == ('25.00', '3')
    assert (row['Variant Inventory Tracker'], row['Variant Inventory Policy']) == ('shopify', 'deny')
    assert row['Variant Fulfillment Service'] == 'manual' and row['Status'] == 'active'
    german = next(r for r in table if 'Dark Magician' in r['Title'])
    assert 'DE' in german['Title'] and '1.ª' in german['Title']


def test_the_woocommerce_file_has_a_simple_product_per_pile(shop):  # noqa: F811
    from src.services.orders.channels import woocommerce_csv

    items = shop.inventory.items(GAMES)
    table = rows(woocommerce_csv(items))
    assert len(table) == 3
    pile = find(items, 'Ragavan')
    row = next(r for r in table if r['SKU'] == sku_of(pile))
    assert (row['Type'], row['Published'], row['In stock?'], row['Stock'], row['Regular price']) == (
        'simple', '1', '1', '2', '40.00')
    assert 'Ragavan, Nimble Pilferer' in row['Name'] and 'MH2' in row['Name']


def test_a_card_name_cannot_become_a_spreadsheet_formula():
    from src.services.orders.channels import shopify_csv, woocommerce_csv

    hostile = SaleLine(name='=HYPERLINK("http://x","y")', set_code='+SUM(A1)', collection='a.json', card_id='1',
                       variant_id='v', quantity=1, unit_cents=100)
    assert rows(shopify_csv([hostile]))[0]['Title'].startswith("'=")
    assert rows(woocommerce_csv([hostile]))[0]['Name'].startswith("'=")


# --- where a WooCommerce shop may live --------------------------------------------------------

def test_a_public_https_address_is_accepted_and_tidied():
    from src.services.orders.channels import check_public_https

    assert check_public_https(' https://Tienda.Example.com/ ', resolve=public) == 'https://tienda.example.com'
    assert check_public_https('https://example.com/shop/', resolve=public) == 'https://example.com/shop'


@pytest.mark.parametrize('url', [
    'http://example.com', 'ftp://example.com', 'example.com', '', 'https://', 'https://user:pw@example.com',
    'https://example.com:8443', 'https://example.com/?a=1', 'https://example.com/#x', 'https://exa mple.com',
])
def test_an_address_that_is_not_plain_https_is_refused(url):
    from src.services.orders.channels import ChannelError, check_public_https

    with pytest.raises(ChannelError):
        check_public_https(url, resolve=public)


@pytest.mark.parametrize('address', [
    '127.0.0.1', '10.0.0.5', '192.168.1.10', '172.16.4.4', '169.254.169.254', '0.0.0.0', '::1', 'fe80::1',
    'fd00::1', '100.64.0.1', '::ffff:127.0.0.1', '224.0.0.1',
])
def test_an_address_inside_a_private_network_is_refused(address):
    from src.services.orders.channels import ChannelError, check_public_https

    with pytest.raises(ChannelError):
        check_public_https('https://example.com', resolve=resolving(address))
    with pytest.raises(ChannelError):   # one public answer does not excuse a private one
        check_public_https('https://example.com', resolve=resolving('93.184.216.34', address))


def test_a_literal_private_ip_and_an_unknown_host_are_refused():
    from src.services.orders.channels import ChannelError, check_public_https

    def unknown(host, *args, **kwargs):
        raise socket.gaierror('nope')

    with pytest.raises(ChannelError):
        check_public_https('https://192.168.1.1', resolve=resolving('192.168.1.1'))
    with pytest.raises(ChannelError):
        check_public_https('https://nowhere.example', resolve=unknown)
    with pytest.raises(ChannelError):
        check_public_https('https://empty.example', resolve=lambda *a, **k: [])


def test_channel_errors_may_be_spoken_to_the_shop():
    from src.services.orders.channels import ChannelError
    from src.ui.shop_common import SHOP_ERRORS

    assert ChannelError.spoken is True and ChannelError in SHOP_ERRORS


# --- the connection on disk -------------------------------------------------------------------

def test_a_shopify_connection_is_kept_sealed_and_shown_by_its_last_four(tmp_path):
    from src.services.orders.channels import ChannelSettings

    settings = ChannelSettings(str(tmp_path))
    assert settings.summary() == {}
    settings.save_shopify(' Cartas-Sol.myshopify.com ', TOKEN)
    text = (tmp_path / 'shop' / 'channels.json').read_text(encoding='utf-8')
    assert TOKEN not in text and 'WXYZ' in text
    summary = settings.summary()['shopify']
    assert (summary['where'], summary['last4']) == ('cartas-sol.myshopify.com', 'WXYZ')
    assert summary['connected_at'] and summary['synced_at'] == ''
    assert TOKEN not in json.dumps(settings.summary())
    assert settings.secrets('shopify') == {'domain': 'cartas-sol.myshopify.com', 'token': TOKEN}


@pytest.mark.parametrize('domain', ['', 'example.com', 'x.myshopify.com.evil.com', 'https://x.myshopify.com',
                                    'a/b.myshopify.com', '-x.myshopify.com', 'x.myshopify.com/admin'])
def test_a_shopify_domain_must_be_a_myshopify_one(tmp_path, domain):
    from src.services.orders.channels import ChannelError, ChannelSettings

    with pytest.raises(ChannelError):
        ChannelSettings(str(tmp_path)).save_shopify(domain, TOKEN)


def test_a_shopify_token_must_look_like_one_and_never_shows_in_the_error(tmp_path):
    from src.services.orders.channels import ChannelError, ChannelSettings

    for token in ('', 'short', 'has spaces in it 0123456789', 'x' * 400):
        with pytest.raises(ChannelError) as failure:
            ChannelSettings(str(tmp_path)).save_shopify('x.myshopify.com', token)
        assert not token or token not in str(failure.value)


def test_a_woocommerce_connection_keeps_both_secrets_sealed(tmp_path):
    from src.services.orders.channels import ChannelError, ChannelSettings

    settings = ChannelSettings(str(tmp_path), resolve=public)
    settings.save_woocommerce('https://Tienda.example.com/', CK, CS)
    text = (tmp_path / 'shop' / 'channels.json').read_text(encoding='utf-8')
    assert CK not in text and CS not in text
    summary = settings.summary()['woocommerce']
    assert (summary['where'], summary['last4']) == ('https://tienda.example.com', 'KKKK')
    assert settings.secrets('woocommerce') == {'url': 'https://tienda.example.com', 'key': CK, 'secret': CS}
    with pytest.raises(ChannelError):
        settings.save_woocommerce('https://tienda.example.com', 'nope', CS)
    with pytest.raises(ChannelError):
        settings.save_woocommerce('https://tienda.example.com', CK, 'nope')
    with pytest.raises(ChannelError):
        ChannelSettings(str(tmp_path), resolve=resolving('10.0.0.1')).save_woocommerce('https://intra.example', CK, CS)


def test_both_channels_live_side_by_side_and_one_can_be_forgotten(tmp_path):
    from src.services.orders.channels import ChannelSettings

    settings = ChannelSettings(str(tmp_path), resolve=public)
    settings.save_shopify('x.myshopify.com', TOKEN)
    settings.save_woocommerce('https://tienda.example.com', CK, CS)
    assert sorted(settings.summary()) == ['shopify', 'woocommerce']
    settings.forget('shopify')
    assert sorted(settings.summary()) == ['woocommerce'] and settings.secrets('shopify') is None
    settings.forget('shopify')   # twice is fine
    settings.forget('woocommerce')
    assert settings.summary() == {}


def test_a_connection_nobody_can_read_counts_as_not_connected(tmp_path):
    from src.services.orders.channels import ChannelSettings

    settings = ChannelSettings(str(tmp_path))
    settings.save_shopify('x.myshopify.com', TOKEN)
    path = tmp_path / 'shop' / 'channels.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['shopify']['secrets'] = 'garbage'
    path.write_text(json.dumps(data), encoding='utf-8')
    assert settings.secrets('shopify') is None and settings.client('shopify') is None
    path.write_text('{not json', encoding='utf-8')
    assert settings.summary() == {} and settings.secrets('shopify') is None


def test_an_unknown_channel_is_refused(tmp_path):
    from src.services.orders.channels import ChannelError, ChannelSettings

    settings = ChannelSettings(str(tmp_path))
    with pytest.raises(ChannelError):
        settings.forget('ebay')
    with pytest.raises(ChannelError):
        settings.secrets('ebay')


# --- when to talk to the shop again -----------------------------------------------------------

def test_a_channel_is_due_at_most_every_ten_minutes(tmp_path):
    from src.services.orders.channels import ChannelSettings

    clock = [1000.0]
    settings = ChannelSettings(str(tmp_path), now=lambda: clock[0])
    assert not settings.due('shopify')          # not connected: nothing to do
    settings.save_shopify('x.myshopify.com', TOKEN)
    assert settings.due('shopify')
    settings.stamp('shopify')
    assert settings.summary()['shopify']['synced_at']
    assert not settings.due('shopify')
    clock[0] += 9 * 60
    assert not settings.due('shopify')
    clock[0] += 61
    assert settings.due('shopify')


def test_what_was_pushed_is_remembered_and_dropped_on_reconnect(tmp_path):
    from src.services.orders.channels import ChannelSettings

    settings = ChannelSettings(str(tmp_path))
    settings.save_shopify('x.myshopify.com', TOKEN)
    assert settings.pushed('shopify') == {}
    settings.remember('shopify', {'OY-AAA': 3, 'OY-BBB': 0})
    assert settings.pushed('shopify') == {'OY-AAA': 3, 'OY-BBB': 0}
    assert settings.secrets('shopify')['token'] == TOKEN    # remembering does not disturb the secret
    settings.save_shopify('y.myshopify.com', TOKEN)         # another shop knows nothing of the old one
    assert settings.pushed('shopify') == {}
