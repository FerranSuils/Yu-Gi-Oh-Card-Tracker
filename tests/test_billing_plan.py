from datetime import date

from src.services.billing import plan
from src.services.billing.plan import AnnualInvoice, BillingRecord


def _rec(trial='2026-01-01', paid=None, invoices=()):
    return BillingRecord(trial_started=trial, lifetime_paid_on=paid, invoices=list(invoices))


def test_prices_and_trial_are_the_agreed_ones():
    assert (plan.LIFETIME_CENTS, plan.ANNUAL_CENTS, plan.TRIAL_DAYS) == (1000, 200, 30)


def test_a_new_account_is_in_trial_for_30_days_then_locked_until_it_pays():
    rec = _rec('2026-11-01')
    assert plan.status('ana', rec, date(2026, 11, 1)) == plan.TRIAL
    assert plan.trial_days_left(rec, date(2026, 11, 20)) == 11
    assert plan.status('ana', rec, date(2026, 11, 30)) == plan.TRIAL
    assert plan.status('ana', rec, date(2026, 12, 1)) == plan.LOCKED_TRIAL


def test_paying_the_lifetime_plan_unlocks_everything_even_after_the_trial():
    assert plan.status('ana', _rec('2026-01-01', paid='2026-03-01'), date(2026, 11, 14)) == plan.ACTIVE


def test_kkdbb_is_exempt_whatever_the_case_and_never_locked():
    old = _rec('2020-01-01')
    assert plan.status('KKDBB', old, date(2026, 11, 14)) == plan.EXEMPT
    assert plan.status('kkdbb', old, date(2026, 11, 14)) == plan.EXEMPT
    assert plan.is_exempt('KKDBB') and not plan.is_exempt('kkdbb2')


def test_an_unpaid_annual_invoice_locks_only_once_it_is_past_due():
    inv = AnnualInvoice(year=2026, invoice_id='in_1', url='https://x', due_on='2027-01-14')
    rec = _rec('2025-01-01', paid='2025-02-01', invoices=[inv])
    assert plan.status('ana', rec, date(2027, 1, 14)) == plan.ACTIVE
    assert plan.status('ana', rec, date(2027, 1, 15)) == plan.LOCKED_ANNUAL
    inv.paid = True
    assert plan.status('ana', rec, date(2027, 1, 15)) == plan.ACTIVE


def test_the_annual_fee_starts_the_year_after_the_purchase_and_never_repeats():
    rec = _rec('2025-01-01', paid='2026-03-01')
    assert not plan.owes_annual(rec, 2026)
    assert plan.owes_annual(rec, 2027)
    rec.invoices.append(AnnualInvoice(year=2027, invoice_id='in_2', url='u', due_on='2028-01-14'))
    assert not plan.owes_annual(rec, 2027)


def test_accounts_that_never_paid_are_not_invoiced():
    assert not plan.owes_annual(_rec('2025-01-01'), 2027)


def test_the_invoice_is_due_14_days_after_it_is_created_at_year_end():
    assert plan.invoice_year(date(2026, 12, 31)) == 2026
    assert plan.invoice_year(date(2026, 12, 30)) is None
    assert plan.invoice_year(date(2027, 1, 3)) == 2026  # a missed run catches up
    assert plan.due_date(date(2026, 12, 31)).isoformat() == '2027-01-14'
