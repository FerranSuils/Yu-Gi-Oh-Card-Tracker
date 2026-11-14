"""Decides whether a locked account may open a page: only the billing page and the files it needs."""

from __future__ import annotations

from datetime import date
from typing import Optional

from src.services.billing import plan
from src.services.billing.service import BillingService

LOCKED_HOME = '/facturacion'
ALLOWED_PREFIXES = ('/facturacion', '/_nicegui/', '/fonts/', '/brand/', '/.well-known/')
ALLOWED_PATHS = {'/_nicegui_ws', '/manifest.webmanifest', '/sw.js', '/login', '/registro'}


def blocks(username: Optional[str], path: str, service: BillingService, today: Optional[date] = None,
           operator: bool = False) -> bool:
    """True when this request must be turned away because the account is locked for non-payment."""
    if operator or not username or not service.enabled:
        return False
    if path in ALLOWED_PATHS or any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return False
    return service.state(username, today) in plan.LOCKED
