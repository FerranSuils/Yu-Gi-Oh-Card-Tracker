"""Who may use the app: trial, lifetime plan, the yearly 2 € invoice, and what to do when they pay."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from typing import List, Optional

from src.services.billing import plan
from src.services.billing.gateway import BillingGateway
from src.services.billing.plan import AnnualInvoice, BillingRecord
from src.services.sales.stripe_gateway import StripeError

logger = logging.getLogger(__name__)
SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
KEY_ENV = 'OPENYUGI_STRIPE_BILLING_KEY'
_LOCK = threading.RLock()
CACHE_SECONDS = 10


class BillingService:
    def __init__(self, root, gateway: Optional[BillingGateway]):
        self.root = Path(root)
        self.gateway = gateway
        self._cache: dict = {}  # username -> (loaded_at, record): every request asks for the state

    @property
    def enabled(self) -> bool:
        return self.gateway is not None

    # --- storage -----------------------------------------------------------------------------

    def _path(self, username: str) -> Path:
        if not isinstance(username, str) or not SAFE_NAME.fullmatch(username):
            raise ValueError('Nombre de cuenta no válido')
        return self.root / f'{username}.json'

    def record(self, username: str, today: Optional[date] = None) -> BillingRecord:
        """The account's record; the first look starts its trial."""
        path = self._path(username)
        with _LOCK:
            cached = self._cache.get(username)
            if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
                return cached[1].model_copy(deep=True)
            if path.exists():
                try:
                    record = BillingRecord(**json.loads(path.read_text(encoding='utf-8')))
                    self._cache[username] = (time.monotonic(), record)
                    return record.model_copy(deep=True)
                except Exception as exc:
                    logger.error('Billing record %s unreadable: %s', path, exc)
            record = BillingRecord(trial_started=(today or date.today()).isoformat())
            self._save(username, record)
            return record

    def _save(self, username: str, record: BillingRecord) -> None:
        path = self._path(username)
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.bill-', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as file:
                json.dump(record.model_dump(mode='json'), file, indent=2)
            os.replace(temporary, path)
            self._cache.pop(username, None)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    # --- state -------------------------------------------------------------------------------

    def state(self, username: str, today: Optional[date] = None) -> str:
        today = today or date.today()
        if not self.enabled:
            return plan.ACTIVE  # no Stripe key configured: never lock anybody
        return plan.status(username, self.record(username, today), today)

    def invoice_for(self, username: str) -> Optional[AnnualInvoice]:
        unpaid = [i for i in self.record(username).invoices if not i.paid]
        return unpaid[-1] if unpaid else None

    # --- paying ------------------------------------------------------------------------------

    def checkout(self, username: str, success_url: str, cancel_url: str) -> str:
        if not self.enabled:
            raise StripeError('Los pagos todavía no están activados.')
        if plan.is_exempt(username):
            raise StripeError('Esta cuenta tiene el plan de por vida gratis.')
        with _LOCK:
            record = self.record(username)
            if record.lifetime_paid_on:
                raise StripeError('Esta cuenta ya tiene el plan de por vida.')
            session, url = self.gateway.create_lifetime_checkout(username, success_url, cancel_url)
            record.lifetime_session = session
            self._save(username, record)
            return url

    def refresh(self, username: str, today: Optional[date] = None) -> str:
        """Asks Stripe whether the pending payments were made and returns the new state."""
        today = today or date.today()
        if not self.enabled or plan.is_exempt(username):
            return self.state(username, today)
        with _LOCK:
            record = self.record(username, today)
            changed = False
            try:
                if not record.lifetime_paid_on and record.lifetime_session \
                        and self.gateway.status(record.lifetime_session) == 'paid':
                    record.lifetime_paid_on, changed = today.isoformat(), True
                for invoice in record.invoices:
                    if not invoice.paid and self.gateway.invoice_paid(invoice.invoice_id):
                        invoice.paid, changed = True, True
            except StripeError as error:
                logger.warning('Billing refresh for %s failed: %s', username, error)
            if changed:
                self._save(username, record)
            return plan.status(username, record, today)

    # --- year end ----------------------------------------------------------------------------

    def accounts(self) -> List[str]:
        if not self.root.exists():
            return []
        return sorted(p.stem for p in self.root.glob('*.json') if SAFE_NAME.fullmatch(p.stem))

    def run_year_end(self, today: Optional[date] = None) -> List[str]:
        """Invoices every lifetime account for the year that just ended. Returns the accounts invoiced."""
        today = today or date.today()
        year = plan.invoice_year(today)
        if not self.enabled or year is None:
            return []
        done = []
        for username in self.accounts():
            if plan.is_exempt(username):
                continue
            with _LOCK:
                record = self.record(username, today)
                if not plan.owes_annual(record, year):
                    continue
                try:
                    if not record.customer_id:
                        record.customer_id = self.gateway.ensure_customer(username)
                    invoice_id, url = self.gateway.create_annual_invoice(record.customer_id, username, year)
                except StripeError as error:
                    logger.error('Annual invoice for %s failed: %s', username, error)
                    continue
                record.invoices.append(AnnualInvoice(year=year, invoice_id=invoice_id, url=url,
                                                     due_on=plan.due_date(today).isoformat()))
                self._save(username, record)
                done.append(username)
        return done


def build_service(root='data/billing') -> BillingService:
    key = os.environ.get(KEY_ENV, '').strip()
    return BillingService(root, BillingGateway(key) if key else None)


billing_service = build_service()
