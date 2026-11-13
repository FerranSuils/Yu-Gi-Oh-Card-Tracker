import json
import os

import pytest
import requests

from src.core import secret_box
from src.core.sales_models import Sale, SaleLine
from src.services.sales import stripe_settings
from src.services.sales.stripe_gateway import StripeError, StripeGateway, check_key_format

KEY = 'rk_test_' + 'a1B2' * 6


class Reply:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeHttp:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def sale():
    return Sale(id='abc123', lines=[SaleLine(name='Dark Magician', quantity=2, unit_cents=999)], total_cents=1998,
                subtotal_cents=1998, currency='EUR', method='stripe', status='pending')


# --- key format ----------------------------------------------------------------------------

@pytest.mark.parametrize('key', [KEY, 'sk_live_' + 'x' * 24, '  ' + KEY + '\n'])
def test_key_format_accepts_secret_and_restricted_keys(key):
    assert check_key_format(key) == key.strip()


@pytest.mark.parametrize('key, message', [
    ('', 'Pega'), ('pk_live_' + 'x' * 24, 'publicable'), ('hola', 'sk_'), ('sk_live_corta', 'sk_'),
    ('whsec_' + 'x' * 24, 'sk_'),
])
def test_key_format_rejects(key, message):
    with pytest.raises(StripeError, match=message):
        check_key_format(key)


# --- gateway -------------------------------------------------------------------------------

def test_check_ok_sends_the_key_as_bearer():
    http = FakeHttp(Reply(200, {'data': []}))
    StripeGateway(KEY, http).check()
    method, url, kwargs = http.calls[0]
    assert (method, url) == ('GET', 'https://api.stripe.com/v1/checkout/sessions')
    assert kwargs['headers']['Authorization'] == f'Bearer {KEY}'
    assert kwargs['params'] == {'limit': 1}
    assert kwargs['timeout']


@pytest.mark.parametrize('status, message', [(401, 'no es válida'), (403, 'permiso')])
def test_check_explains_bad_keys(status, message):
    http = FakeHttp(Reply(status, {'error': {'message': f'Invalid API Key provided: {KEY}'}}))
    with pytest.raises(StripeError, match=message) as caught:
        StripeGateway(KEY, http).check()
    assert KEY not in str(caught.value)


def test_create_checkout_charges_the_ticket_total_once():
    http = FakeHttp(Reply(200, {'id': 'cs_test_1', 'url': 'https://checkout.stripe.com/c/pay/cs_test_1'}))
    session, url = StripeGateway(KEY, http).create_checkout(sale(), 'https://tienda.test/tpv/pagado')
    assert (session, url) == ('cs_test_1', 'https://checkout.stripe.com/c/pay/cs_test_1')
    method, address, kwargs = http.calls[0]
    assert (method, address) == ('POST', 'https://api.stripe.com/v1/checkout/sessions')
    data = kwargs['data']
    assert data['mode'] == 'payment'
    assert data['line_items[0][price_data][unit_amount]'] == 1998
    assert data['line_items[0][price_data][currency]'] == 'eur'
    assert data['line_items[0][quantity]'] == 1
    assert data['line_items[0][price_data][product_data][name]'] == 'Compra en tienda (2 artículos)'
    assert data['payment_method_types[0]'] == 'card'
    assert data['client_reference_id'] == 'abc123' and data['metadata[sale]'] == 'abc123'
    assert data['success_url'] == 'https://tienda.test/tpv/pagado'
    assert data['expires_at'] > 0
    assert kwargs['headers']['Idempotency-Key'] == 'sale-abc123'


def test_create_checkout_rejects_a_reply_without_a_stripe_url():
    http = FakeHttp(Reply(200, {'id': 'cs_test_1', 'url': 'http://evil.test/pay'}))
    with pytest.raises(StripeError):
        StripeGateway(KEY, http).create_checkout(sale(), 'https://tienda.test/ok')


@pytest.mark.parametrize('body, state', [
    ({'status': 'complete', 'payment_status': 'paid'}, 'paid'),
    ({'status': 'complete', 'payment_status': 'no_payment_required'}, 'paid'),
    ({'status': 'open', 'payment_status': 'unpaid'}, 'open'),
    ({'status': 'expired', 'payment_status': 'unpaid'}, 'expired'),
    ({'status': 'complete', 'payment_status': 'unpaid'}, 'open'),
])
def test_status(body, state):
    http = FakeHttp(Reply(200, body))
    assert StripeGateway(KEY, http).status('cs_test_1') == state
    assert http.calls[0][1] == 'https://api.stripe.com/v1/checkout/sessions/cs_test_1'


def test_session_ids_cannot_reach_other_endpoints():
    with pytest.raises(StripeError):
        StripeGateway(KEY, FakeHttp()).status('../refunds')


def test_expire():
    http = FakeHttp(Reply(200, {'status': 'expired'}))
    StripeGateway(KEY, http).expire('cs_test_1')
    assert http.calls[0][:2] == ('POST', 'https://api.stripe.com/v1/checkout/sessions/cs_test_1/expire')


def test_refund_uses_the_payment_of_the_session():
    http = FakeHttp(Reply(200, {'payment_intent': 'pi_9'}), Reply(200, {'id': 're_1', 'status': 'succeeded'}))
    StripeGateway(KEY, http).refund('cs_test_1')
    method, url, kwargs = http.calls[1]
    assert (method, url) == ('POST', 'https://api.stripe.com/v1/refunds')
    assert kwargs['data'] == {'payment_intent': 'pi_9'}
    assert kwargs['headers']['Idempotency-Key'] == 'refund-cs_test_1'


def test_refund_without_a_payment_fails():
    with pytest.raises(StripeError, match='pago'):
        StripeGateway(KEY, FakeHttp(Reply(200, {'payment_intent': None}))).refund('cs_test_1')


def test_stripe_errors_keep_the_message_but_never_the_key():
    http = FakeHttp(Reply(400, {'error': {'message': f'Amount too small for {KEY}.'}}))
    with pytest.raises(StripeError) as caught:
        StripeGateway(KEY, http).status('cs_test_1')
    assert 'Amount too small' in str(caught.value) and KEY not in str(caught.value)


def test_network_failure_is_a_stripe_error_without_the_key():
    http = FakeHttp(requests.ConnectionError(f'boom {KEY}'))
    with pytest.raises(StripeError, match='conectar') as caught:
        StripeGateway(KEY, http).check()
    assert KEY not in str(caught.value)


def test_unreadable_reply_is_a_stripe_error():
    with pytest.raises(StripeError):
        StripeGateway(KEY, FakeHttp(Reply(502, ValueError('html')))).status('cs_test_1')


def test_gateway_repr_hides_the_key():
    assert KEY not in repr(StripeGateway(KEY, FakeHttp()))


# --- secret box and settings ---------------------------------------------------------------

def test_secret_box_round_trip_and_not_plain():
    blob = secret_box.protect(KEY)
    assert secret_box.reveal(blob) == KEY
    if os.name == 'nt':
        assert blob.startswith('dpapi:') and KEY not in blob


@pytest.mark.parametrize('blob', ['', 'dpapi:not-base64!!', 'dpapi:AAAA', 'otra:cosa'])
def test_secret_box_rejects_garbage(blob):
    with pytest.raises(ValueError):
        secret_box.reveal(blob)


def test_settings_store_only_a_protected_key(tmp_path):
    assert stripe_settings.key_summary(str(tmp_path)) is None
    assert stripe_settings.load_key(str(tmp_path)) is None
    stripe_settings.save_key(str(tmp_path), KEY)
    raw = (tmp_path / 'stripe.json').read_text(encoding='utf-8')
    if os.name == 'nt':
        assert KEY not in raw
    summary = stripe_settings.key_summary(str(tmp_path))
    assert (summary['last4'], summary['mode'], summary['kind']) == (KEY[-4:], 'test', 'restringida')
    assert KEY not in json.dumps(summary)
    assert stripe_settings.load_key(str(tmp_path)) == KEY


def test_settings_are_per_account_and_forgettable(tmp_path):
    stripe_settings.save_key(str(tmp_path / 'a'), KEY)
    assert stripe_settings.load_key(str(tmp_path / 'b')) is None
    stripe_settings.forget_key(str(tmp_path / 'a'))
    assert stripe_settings.load_key(str(tmp_path / 'a')) is None
    stripe_settings.forget_key(str(tmp_path / 'a'))


def test_settings_survive_a_broken_file(tmp_path):
    (tmp_path / 'stripe.json').write_text('{broken', encoding='utf-8')
    assert stripe_settings.load_key(str(tmp_path)) is None
    assert stripe_settings.key_summary(str(tmp_path)) is None


def test_a_refund_stripe_already_made_counts_as_done():
    http = FakeHttp(Reply(200, {'payment_intent': 'pi_9'}),
                    Reply(400, {'error': {'code': 'charge_already_refunded',
                                          'message': 'Charge ch_1 has already been refunded.'}}))
    StripeGateway(KEY, http).refund('cs_test_1')
    assert len(http.calls) == 2


def test_other_refund_errors_still_fail():
    http = FakeHttp(Reply(200, {'payment_intent': 'pi_9'}),
                    Reply(400, {'error': {'code': 'charge_disputed', 'message': 'Disputed.'}}))
    with pytest.raises(StripeError):
        StripeGateway(KEY, http).refund('cs_test_1')
