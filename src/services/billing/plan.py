"""The plan: 30 days of trial, a one-off 10 € lifetime payment, and 2 € a year to keep the server running.

Pure rules, no I/O. The account KKDBB has the lifetime plan for free and is never invoiced.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field

LIFETIME_CENTS = 1000
ANNUAL_CENTS = 200
TRIAL_DAYS = 30
INVOICE_DAYS_DUE = 14
EXEMPT_ACCOUNTS = frozenset({'kkdbb'})

TRIAL, ACTIVE, EXEMPT = 'trial', 'active', 'exempt'
LOCKED_TRIAL, LOCKED_ANNUAL = 'locked_trial', 'locked_annual'
LOCKED = frozenset({LOCKED_TRIAL, LOCKED_ANNUAL})


class AnnualInvoice(BaseModel):
    year: int
    invoice_id: str
    url: str
    due_on: str  # ISO date
    paid: bool = False


class BillingRecord(BaseModel):
    trial_started: str  # ISO date
    lifetime_paid_on: Optional[str] = None
    lifetime_session: Optional[str] = None  # the open Checkout Session of the 10 € payment
    customer_id: Optional[str] = None
    invoices: List[AnnualInvoice] = Field(default_factory=list)


def is_exempt(username: str) -> bool:
    return (username or '').casefold() in EXEMPT_ACCOUNTS


def trial_end(record: BillingRecord) -> date:
    return date.fromisoformat(record.trial_started) + timedelta(days=TRIAL_DAYS)


def trial_days_left(record: BillingRecord, today: date) -> int:
    return max(0, (trial_end(record) - today).days)


def status(username: str, record: BillingRecord, today: date) -> str:
    if is_exempt(username):
        return EXEMPT
    if record.lifetime_paid_on:
        if any(not inv.paid and today > date.fromisoformat(inv.due_on) for inv in record.invoices):
            return LOCKED_ANNUAL
        return ACTIVE
    return TRIAL if today < trial_end(record) else LOCKED_TRIAL


def owes_annual(record: BillingRecord, year: int) -> bool:
    """Lifetime accounts pay the yearly 2 € from the year after they bought the plan, once per year."""
    if not record.lifetime_paid_on:
        return False
    if date.fromisoformat(record.lifetime_paid_on).year >= year:
        return False
    return not any(inv.year == year for inv in record.invoices)


def invoice_year(today: date) -> Optional[int]:
    """The year to invoice today: on 31 December, or in January if a run was missed."""
    if today.month == 12 and today.day == 31:
        return today.year
    if today.month == 1:
        return today.year - 1
    return None


def due_date(created: date) -> date:
    return created + timedelta(days=INVOICE_DAYS_DUE)
