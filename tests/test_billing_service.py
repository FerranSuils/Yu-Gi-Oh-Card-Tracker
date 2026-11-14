from datetime import date

import pytest

from src.services.billing import plan
from src.services.billing.gateway import BillingGateway
from src.services.billing.service import BillingService
from src.services.sales.stripe_gateway import StripeError

KEY = 'sk_test_' + 'a' * 24


class FakeHttp:
    def __init__(self):
        self.calls, self.paid_sessions, self.paid_invoices = [], set(), set()

    def request(self, method, url, headers=None, params=None, data=None, timeout=None):
        self.calls.append((method, url.split('/v1')[1], data or {}, headers or {}))
        path = url.split('/v1')[1]
        body = {}
        if path == '/checkout/sessions' and method == 'POST':
            body = {'id': 'cs_1', 'url': 'https://checkout.stripe.com/pay/cs_1'}
        elif path.startswith('/checkout/sessions/'):
            sid = path.rsplit('/', 1)[1]
            done = sid in self.paid_sessions
            body = {'id': sid, 'status': 'complete' if done else 'open', 'payment_status': 'paid' if done else 'unpaid'}
        elif path == '/customers':
            body = {'id': 'cus_1'}
        elif path == '/invoiceitems':
            body = {'id': 'ii_1'}
        elif path == '/invoices':
            body = {'id': 'in_1'}
        elif path.endswith('/finalize'):
            body = {'id': 'in_1', 'hosted_invoice_url': 'https://invoice.stripe.com/i/in_1'}
        elif path.startswith('/invoices/'):
            body = {'id': 'in_1', 'status': 'paid' if 'in_1' in self.paid_invoices else 'open'}

        class Reply:
            status_code = 200

            def json(self_inner):
                return body
        return Reply()


@pytest.fixture
def env(tmp_path):
    http = FakeHttp()
    service = BillingService(tmp_path, BillingGateway(KEY, http=http))
    return service, http


def test_without_a_stripe_key_billing_is_off_and_nobody_is_ever_locked(tmp_path):
    service = BillingService(tmp_path, None)
    assert not service.enabled
    assert service.state('ana', date(2030, 1, 1)) == plan.ACTIVE


def test_the_first_look_starts_the_trial_and_it_is_remembered(env):
    service, _ = env
    assert service.state('ana', date(2026, 11, 1)) == plan.TRIAL
    assert service.state('ana', date(2026, 11, 29)) == plan.TRIAL
    assert service.state('ana', date(2026, 12, 2)) == plan.LOCKED_TRIAL


def test_kkdbb_never_needs_to_pay_and_never_gets_a_checkout(env):
    service, http = env
    assert service.state('KKDBB', date(2030, 1, 1)) == plan.EXEMPT
    with pytest.raises(StripeError):
        service.checkout('KKDBB', 'https://app/ok', 'https://app/no')
    assert http.calls == []


def test_checkout_asks_stripe_for_10_euros_once_for_this_account(env):
    service, http = env
    url = service.checkout('ana', 'https://app/ok', 'https://app/no')
    assert url.startswith('https://checkout.stripe.com/')
    method, path, data, headers = http.calls[0]
    assert (method, path) == ('POST', '/checkout/sessions')
    assert data['mode'] == 'payment' and data['line_items[0][price_data][unit_amount]'] == 1000
    assert data['line_items[0][price_data][currency]'] == 'eur'
    assert data['client_reference_id'] == 'ana'
    assert headers['Idempotency-Key'].startswith('lifetime-ana')


def test_a_paid_checkout_unlocks_the_account_after_refresh(env):
    service, http = env
    service.state('ana', date(2026, 11, 1))
    service.checkout('ana', 'u', 'u')
    assert service.state('ana', date(2026, 12, 5)) == plan.LOCKED_TRIAL
    http.paid_sessions.add('cs_1')
    assert service.refresh('ana', date(2026, 12, 5)) == plan.ACTIVE
    assert service.state('ana', date(2027, 6, 1)) == plan.ACTIVE


def test_year_end_invoices_each_lifetime_account_2_euros_once(env):
    service, http = env
    service.state('ana', date(2025, 3, 1)); service.checkout('ana', 'u', 'u')
    http.paid_sessions.add('cs_1'); service.refresh('ana', date(2025, 3, 2))
    service.state('bea', date(2026, 12, 1))  # still in trial: not invoiced
    http.calls.clear()
    assert service.run_year_end(date(2026, 12, 31)) == ['ana']
    item = next(c for c in http.calls if c[1] == '/invoiceitems')
    assert item[2]['amount'] == 200 and item[2]['currency'] == 'eur'
    invoice = next(c for c in http.calls if c[1] == '/invoices')
    assert invoice[2]['collection_method'] == 'send_invoice' and invoice[2]['days_until_due'] == 14
    assert service.run_year_end(date(2027, 1, 5)) == []  # already invoiced
    assert service.invoice_for('ana').url == 'https://invoice.stripe.com/i/in_1'


def test_an_unpaid_invoice_locks_after_the_due_date_and_paying_unlocks(env):
    service, http = env
    service.state('ana', date(2025, 3, 1)); service.checkout('ana', 'u', 'u')
    http.paid_sessions.add('cs_1'); service.refresh('ana', date(2025, 3, 2))
    service.run_year_end(date(2026, 12, 31))
    assert service.state('ana', date(2027, 1, 14)) == plan.ACTIVE
    assert service.state('ana', date(2027, 1, 15)) == plan.LOCKED_ANNUAL
    http.paid_invoices.add('in_1')
    assert service.refresh('ana', date(2027, 1, 15)) == plan.ACTIVE


def test_exempt_accounts_are_skipped_by_year_end(env):
    service, http = env
    service.state('KKDBB', date(2025, 1, 1))
    assert service.run_year_end(date(2026, 12, 31)) == []


def test_unsafe_account_names_never_become_file_names(env):
    service, _ = env
    with pytest.raises(ValueError):
        service.state('../x', date(2026, 1, 1))


def test_the_key_never_shows_in_the_gateway_repr_or_errors():
    assert KEY not in repr(BillingGateway(KEY, http=FakeHttp()))
