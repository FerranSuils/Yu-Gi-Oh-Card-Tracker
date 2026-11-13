"""The tickets of one account: <cuenta>/sales/AAAA-MM.json plus the ticket counter."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import List, Optional

from src.core.sales_models import METHOD_LABELS, STATUS_LABELS, Sale

logger = logging.getLogger(__name__)

_MONTH = re.compile(r'\d{4}-\d{2}')
_FORMULA_START = ('=', '+', '-', '@')
_guard_lock = threading.Lock()
_locks: dict[str, threading.RLock] = {}

CSV_HEADER = ['Número', 'Fecha', 'Estado', 'Método', 'Artículo', 'Set', 'Nº carta', 'Rareza', 'Estado carta',
              'Idioma', 'Juego', 'Colección', 'Cantidad', 'Precio unidad', 'Total línea', 'Subtotal ticket',
              'Descuento ticket', 'Total ticket', 'Moneda']


def _root_lock(root: str) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(root))
    with _guard_lock:
        return _locks.setdefault(key, threading.RLock())


def patiently(action, attempts: int = 6):
    """Runs ``action``; when Windows refuses the file because somebody else has it open this instant, waits a
    little and tries again."""
    for attempt in range(attempts):
        try:
            return action()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.03 * (attempt + 1))


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.sales-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=1)
        patiently(lambda: os.replace(temporary, path))
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


class SalesUnreadable(Exception):
    """A month of tickets is on disk but cannot be read."""


class SalesStore:
    def __init__(self, root: str):
        self._dir = os.path.join(root, 'sales')
        self.lock = _root_lock(root)  # one ticket operation at a time per account

    def _file(self, month: str) -> str:
        if not _MONTH.fullmatch(month):
            raise ValueError('Mes no válido')
        return os.path.join(self._dir, f'{month}.json')

    def months(self) -> List[str]:
        if not os.path.isdir(self._dir):
            return []
        return sorted((name[:-5] for name in os.listdir(self._dir)
                       if name.endswith('.json') and _MONTH.fullmatch(name[:-5])), reverse=True)

    def _read(self, month: str, strict: bool = False) -> List[Sale]:
        path = self._file(month)
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as file:
                return [Sale(**row) for row in json.load(file)]
        except (OSError, ValueError, TypeError) as error:
            logger.error('Ventas: %s no se puede leer: %s', path, type(error).__name__)
            if strict:
                raise SalesUnreadable(month) from None
            return []

    def month(self, month: str, strict: bool = False) -> List[Sale]:
        """Tickets of a month, newest first. `strict` raises on a damaged month: figures must not read it as empty."""
        return sorted(self._read(month, strict), key=lambda sale: (sale.created_at, sale.number or 0), reverse=True)

    def get(self, sale_id: str) -> Optional[Sale]:
        for month in self.months():
            for sale in self._read(month):
                if sale.id == sale_id:
                    return sale
        return None

    def save(self, sale: Sale) -> None:
        month = sale.created_at[:7]
        with self.lock:
            path = self._file(month)
            if os.path.exists(path) and not self._read(month):
                with open(path, 'r', encoding='utf-8') as file:
                    if file.read().strip() not in ('', '[]'):
                        # Never write a fresh list over a month file we could not read.
                        raise OSError(f'El fichero de ventas de {month} está dañado; no se ha tocado.')
            sales = [other for other in self._read(month) if other.id != sale.id] + [sale]
            _write(path, [item.model_dump(mode='json') for item in sales])

    def next_number(self) -> int:
        """Hands out the next ticket number; numbers are never reused."""
        path = os.path.join(self._dir, 'counter.json')
        with self.lock:
            last = 0
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    last = int(json.load(file).get('last', 0))
            except (OSError, ValueError, TypeError, AttributeError):
                # No counter (or a broken one): carry on after the highest number already used.
                last = max((sale.number or 0 for month in self.months() for sale in self._read(month)), default=0)
            _write(path, {'last': last + 1})
            return last + 1

    def pending_stripe(self) -> List[Sale]:
        return [sale for month in self.months() for sale in self._read(month)
                if sale.status == 'pending' and sale.method == 'stripe']


def _text(value) -> str:
    text = '' if value is None else str(value)
    if text[:1] in ('\t', '\r') or text.lstrip()[:1] in _FORMULA_START:
        return "'" + text
    return text


def _amount(cents: int) -> str:
    return f'{cents // 100},{cents % 100:02d}'


def sales_csv(sales: List[Sale]) -> bytes:
    """One row per ticket line, semicolon-separated with decimal commas, ready for a spreadsheet."""
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, delimiter=';', lineterminator='\r\n')
    writer.writerow(CSV_HEADER)
    for sale in sales:
        for line in sale.lines:
            writer.writerow([
                sale.label if sale.number else '', sale.paid_at or sale.created_at,
                STATUS_LABELS.get(sale.status, sale.status), METHOD_LABELS.get(sale.method, sale.method),
                _text(line.name), _text(line.set_code), _text(line.number), _text(line.rarity),
                line.condition if line.kind == 'stock' else '', line.language if line.kind == 'stock' else '',
                line.game if line.kind == 'stock' else '', _text(line.collection), line.quantity,
                _amount(line.unit_cents), _amount(line.total_cents), _amount(sale.subtotal_cents),
                _amount(sale.discount_cents), _amount(sale.total_cents), sale.currency])
    return buffer.getvalue().encode('utf-8-sig')
