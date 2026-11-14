from datetime import date

from src.services.billing import plan
from src.services.billing.guard import LOCKED_HOME, blocks
from src.services.billing.gateway import BillingGateway
from src.services.billing.service import BillingService


class _Http:
    def request(self, *args, **kwargs):
        raise AssertionError('the guard must not call Stripe')


def _service(tmp_path):
    return BillingService(tmp_path, BillingGateway('sk_test_' + 'a' * 24, http=_Http()))


def test_a_locked_account_may_only_reach_the_billing_page_and_assets(tmp_path):
    service = _service(tmp_path)
    service.state('ana', date(2026, 1, 1))
    late = date(2026, 6, 1)
    assert blocks('ana', '/collection', service, late)
    assert blocks('ana', '/api/v1/cards', service, late)
    assert not blocks('ana', LOCKED_HOME, service, late)
    assert not blocks('ana', '/fonts/a.woff2', service, late)
    assert not blocks('ana', '/brand/logo.svg', service, late)


def test_accounts_in_trial_or_with_the_plan_are_never_blocked(tmp_path):
    service = _service(tmp_path)
    service.state('ana', date(2026, 1, 1))
    assert not blocks('ana', '/collection', service, date(2026, 1, 20))
    assert not blocks('KKDBB', '/collection', service, date(2030, 1, 1))


def test_nothing_is_blocked_while_billing_is_not_configured(tmp_path):
    assert not blocks('ana', '/collection', BillingService(tmp_path, None), date(2030, 1, 1))


def test_the_operator_account_is_never_blocked(tmp_path):
    service = _service(tmp_path)
    service.state('admin', date(2026, 1, 1))
    assert not blocks('admin', '/collection', service, date(2026, 6, 1), operator=True)
