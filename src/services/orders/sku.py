"""The name a pile goes by in an online shop."""

from __future__ import annotations

import hashlib

from src.core.sales_models import SaleLine
from src.services.sales.inventory import line_key


def sku_of(line: SaleLine) -> str:
    """Same pile, same SKU. It changes when the pile moves collection, condition, language, edition or place."""
    text = '|'.join('' if part is None else str(part) for part in line_key(line))
    return 'OY-' + hashlib.sha1(text.encode('utf-8')).hexdigest()[:12].upper()
