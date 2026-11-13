"""One account's shop desk: its stock, tills and books, built from the account folder alone."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.core.game_collections import GameCollectionStore
from src.core.persistence import _BoundPersistence
from src.services.sales.checkout import Checkout
from src.services.sales.inventory import Inventory
from src.services.orders.book import OrderBook
from src.services.sales.store import SalesStore
from src.services.shop.buylist import Buying, PurchaseStore
from src.services.shop.consignment import ConsignmentBook
from src.services.shop.customers import CustomerStore
from src.services.shop.kiosk import KioskOrders
from src.services.shop.loyalty import Loyalty


@dataclass
class Desk:
    root: str
    inventory: Inventory
    sales: SalesStore
    customers: CustomerStore
    book: ConsignmentBook
    purchases: PurchaseStore
    checkout: Checkout
    buying: Buying
    orders: KioskOrders
    dispatch: OrderBook
    loyalty: Loyalty


def inventory_for(root: str) -> Inventory:
    """The stock of the account kept in ``root``, whoever is (or is not) signed in."""
    files = _BoundPersistence(os.path.join(root, 'collections'), os.path.join(root, 'decks'))
    return Inventory(files, GameCollectionStore(lambda: root))


def desk_for(root: str, currency: str = 'EUR') -> Desk:
    inventory = inventory_for(root)
    sales = SalesStore(root)
    customers = CustomerStore(root, currency)
    book = ConsignmentBook(root, customers)
    purchases = PurchaseStore(root)
    loyalty = Loyalty(root, customers, currency)
    return Desk(root=root, inventory=inventory, sales=sales, customers=customers, book=book, purchases=purchases,
                loyalty=loyalty,
                checkout=Checkout(inventory, sales, customers=customers, consignments=book, loyalty=loyalty),
                buying=Buying(inventory, purchases, customers, book), orders=KioskOrders(root), dispatch=OrderBook(root, inventory))
