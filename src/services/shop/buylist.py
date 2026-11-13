"""Buying cards from customers: what the shop offers, the purchases book, and stock coming in."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from src.core.catalog_models import CatalogCard, CatalogPrinting
from src.core.pricing_models import PricingRule, PrintingPrice
from src.core.sales_models import OutOfStock, SaleLine, format_money, now_iso, spoken, to_cents
from src.core.shop_models import BuylistRules, Purchase
from src.core.utils import generate_variant_id
from src.services.repricing import base_price, quote_for
from src.services.shop.files import BrokenFile, read_list, root_lock, shop_path, write_list

logger = logging.getLogger(__name__)

MAX_LINES = 200


class BuyError(Exception):
    """A purchase that cannot be made or cancelled, with a message for the counter."""

    spoken = True


# --- the offer -------------------------------------------------------------------------------

def offer_cents(market: int, rules: BuylistRules, payment: str, condition: str) -> int:
    """What the shop offers per copy. 0 means the card is not bought."""
    if payment not in ('cash', 'credit'):
        raise BuyError('Forma de pago no válida.')
    percent = rules.cash_percent if payment == 'cash' else rules.credit_percent
    factor = rules.condition_factors.get(condition, 100)
    offer = int((Decimal(max(market, 0)) * Decimal(str(percent)) * Decimal(str(factor)) / 10000).quantize(
        Decimal(1), rounding=ROUND_HALF_UP))
    return offer if offer > 0 and offer >= rules.min_offer_cents else 0


def market_cents(price: Optional[PrintingPrice], finish: str) -> Optional[int]:
    """The market price of a printing in that finish, or None when the source has none."""
    value = base_price(PricingRule(), quote_for(price, finish))
    if value is None:
        return None
    try:
        return to_cents(value)
    except ValueError:
        return None


@dataclass
class Offer:
    printing: CatalogPrinting
    finish: str
    market_cents: int
    cash_cents: int
    credit_cents: int


def offers(card: CatalogCard, source, rules: BuylistRules, condition: str = 'Near Mint') -> List[Offer]:
    """What the shop pays for each printing and finish of a card. Only prices already on disk count."""
    if source is None:
        return []
    rows = []
    for printing in card.printings:
        try:
            price = source.get(printing.printing_id)
        except Exception as error:
            logger.warning('Compras: precio ilegible: %s', type(error).__name__)
            continue
        for finish in ([''] if card.game == 'yugioh' else (printing.finishes or ['nonfoil'])):
            market = market_cents(price, finish)
            if not market:
                continue
            cash = offer_cents(market, rules, 'cash', condition)
            credit = offer_cents(market, rules, 'credit', condition)
            if cash or credit:
                rows.append(Offer(printing, finish, market, cash, credit))
    return rows


# --- lines -----------------------------------------------------------------------------------

def line_for(card: CatalogCard, printing: CatalogPrinting, quantity: int, paid_cents: int,
             market_cents: Optional[int], collection: str, finish: str = '', condition: str = 'Near Mint',
             language: str = 'EN', first_edition: bool = False,
             storage_location: Optional[str] = None) -> SaleLine:
    """A purchase line: ``unit_cents`` is what the shop pays, ``list_price`` what a new pile will ask."""
    yugioh = card.game == 'yugioh'
    variant_id, image_id = printing.printing_id, None
    try:
        if yugioh:
            image_id = int(card.card_id)
            if ':' in variant_id:  # the catalog had no variant id for this printing: the collection's own hash
                variant_id = generate_variant_id(image_id, printing.set_code, printing.rarity or '', image_id)
        return SaleLine(
            game=card.game, collection=collection, card_id=card.card_id, name=card.name,
            set_code=printing.set_code, number=printing.number, rarity=printing.rarity or '',
            variant_id=variant_id, finish='' if yugioh else (finish or 'nonfoil'), image_id=image_id,
            condition=condition, language=language, first_edition=first_edition,
            storage_location=storage_location or None, quantity=quantity, unit_cents=paid_cents,
            list_price=market_cents / 100 if market_cents else None)
    except (ValueError, TypeError):
        raise BuyError(f'{card.name}: cantidad o importe no válidos.') from None


# --- the purchases book ----------------------------------------------------------------------

class PurchaseStore:
    def __init__(self, root: str):
        self._path = shop_path(root, 'purchases.json')
        self.lock = root_lock(root)

    def _read(self) -> List[Purchase]:
        try:
            return read_list(self._path, Purchase)
        except BrokenFile as error:
            raise BuyError(f'El fichero {error} está dañado; no se ha tocado.') from error

    def all(self) -> List[Purchase]:
        return sorted(self._read(), key=lambda p: p.created_at, reverse=True)

    def get(self, purchase_id: str) -> Optional[Purchase]:
        return next((p for p in self._read() if p.id == purchase_id), None)

    def next_number(self) -> int:
        return max((p.number or 0 for p in self._read()), default=0) + 1

    def save(self, purchase: Purchase) -> None:
        with self.lock:
            purchases = [p for p in self._read() if p.id != purchase.id]
            write_list(self._path, purchases + [purchase])


# --- buying ----------------------------------------------------------------------------------

class Buying:
    def __init__(self, inventory, purchases: PurchaseStore, customers, consignments=None):
        self._inventory = inventory
        self._purchases = purchases
        self._customers = customers
        self._consignments = consignments

    def _check(self, lines: List[SaleLine], payment: str) -> None:
        if payment not in ('cash', 'credit'):
            raise BuyError('Forma de pago no válida.')
        if not lines:
            raise BuyError('La compra está vacía.')
        if len(lines) > MAX_LINES:
            raise BuyError(f'Una compra admite {MAX_LINES} líneas como mucho; repártela en varias.')
        for line in lines:
            name = line.collection
            if line.kind != 'stock' or not name or os.path.basename(name) != name or name.startswith('.'):
                raise BuyError(f'{line.name}: elige la colección donde entra la carta.')
            if self._consignments is not None and self._consignments.of(line.game, name) is not None:
                raise BuyError(f'{name} está en consigna: las compras de la tienda van a otra colección.')

    def buy(self, lines: List[SaleLine], payment: str, currency: str,
            customer_id: Optional[str] = None) -> Purchase:
        """Pay for the cards and put them in stock. Credit goes to the customer's store balance."""
        try:
            self._check(lines, payment)
            with self._purchases.lock:
                customer = self._customers.get(customer_id) if customer_id is not None else None
                if payment == 'credit' and customer is None:
                    raise BuyError('Elige el cliente que recibe el saldo.')
                if customer_id is not None and customer is None:
                    raise BuyError('Ese cliente ya no existe.')
                purchase = Purchase(
                    number=self._purchases.next_number(), lines=[line.model_copy() for line in lines],
                    total_cents=sum(line.total_cents for line in lines), currency=currency, payment=payment,
                    customer_id=customer.id if customer else None, customer_name=customer.name if customer else '')
                self._inventory.give_back(purchase.lines)
                try:
                    self._purchases.save(purchase)
                    if payment == 'credit' and purchase.total_cents > 0:
                        self._customers.post(customer.id, 'credit', purchase.total_cents,
                                             f'Compra {purchase.label}', ref=purchase.id)
                except Exception:
                    self._take_back(purchase)
                    raise
                return purchase
        except BuyError:
            raise
        except Exception as error:
            logger.error('Compra sin hacer: %s', type(error).__name__)
            raise BuyError(spoken(error, 'No se pudo guardar la compra.')) from error

    def _take_back(self, purchase: Purchase) -> None:
        """The purchase could not be written down: the cards do not stay in stock."""
        try:
            self._inventory.take(purchase.lines)
        except Exception as error:
            logger.error('Compra %s: cartas sin retirar: %s', purchase.id, type(error).__name__)
        try:
            if self._purchases.get(purchase.id) is not None:
                purchase.status, purchase.cancelled_at = 'cancelled', now_iso()
                self._purchases.save(purchase)
        except Exception as error:
            logger.error('Compra %s: sin anular: %s', purchase.id, type(error).__name__)

    def cancel(self, purchase_id: str) -> Purchase:
        """Undo a purchase: the cards leave the stock and the credit given is taken back."""
        try:
            with self._purchases.lock:
                purchase = self._purchases.get(purchase_id)
                if purchase is None:
                    raise BuyError('Esa compra no existe.')
                if purchase.status != 'done':
                    raise BuyError('Esa compra ya está anulada.')
                credit = purchase.total_cents if purchase.payment == 'credit' else 0
                if credit:
                    have = self._customers.balance(purchase.customer_id, 'credit')
                    if have < credit:
                        raise BuyError(
                            f'No se puede anular: el cliente ya gastó parte del saldo (le quedan '
                            f'{format_money(have, purchase.currency)} de {format_money(credit, purchase.currency)}).')
                try:
                    self._inventory.take(purchase.lines)
                except OutOfStock as error:
                    raise BuyError(f'No se puede anular: cartas ya vendidas o movidas. {error}') from None
                try:
                    if credit:
                        self._customers.post(purchase.customer_id, 'credit', -credit,
                                             f'Compra {purchase.label} anulada', ref=purchase.id)
                    purchase.status, purchase.cancelled_at = 'cancelled', now_iso()
                    self._purchases.save(purchase)
                except Exception:
                    self._inventory.give_back(purchase.lines)
                    raise
                return purchase
        except BuyError:
            raise
        except Exception as error:
            logger.error('Compra %s sin anular: %s', purchase_id, type(error).__name__)
            raise BuyError(spoken(error, 'No se pudo anular la compra.')) from error
