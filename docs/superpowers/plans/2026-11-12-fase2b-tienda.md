# Fase 2b — plan

**Spec:** docs/superpowers/specs/2026-11-12-fase2b-tienda-design.md
**Ejecución:** inline, TDD, una revisión final con contexto fresco.

## Restricciones globales
Sin BD · I/O en `run.io_bound` · stock solo por `CollectionEditor`/`GameCollectionEditor` (vía `Inventory`) ·
céntimos enteros · iconos IconKit autoalojados · tests en directorios temporales · nada de commits.

## Tareas
1. `src/core/shop_models.py` (Customer, LedgerEntry, BuylistRules, Purchase, Consignment, KioskOrder) y
   `src/services/shop/customers.py` → `CustomerStore(root)`: `all, get, save, remove, post, balance, balances,
   entries`. Tests `tests/test_shop_customers.py`.
2. `Checkout`: método `credit` con `customer_id`; `Checkout(inventory, store, customers=None, consignments=None)`;
   al cobrar → `consignments.settle(sale)`; al devolver → `consignments.reverse(sale)` y reponer saldo.
   `src/services/shop/consignment.py` → `ConsignmentBook(root, customers)`: `all, open, close, of, settle,
   reverse, pay_out`. Tests `tests/test_shop_consignment.py`, `tests/test_sales_credit.py`.
3. `src/services/shop/buylist.py`: `offer_cents`, `market_cents`, `PurchaseStore`, `Buying.buy/cancel`.
   Tests `tests/test_shop_buylist.py`.
4. `src/services/shop/kiosk.py`: `enable/disable/account_for(token)`, `KioskOrders(root)`: `add, open, take`,
   `shelf(items)`. Tests `tests/test_shop_kiosk.py`.
5. UI: `/clientes`, `/compras`, `/consigna`, `/kiosko/{token}`, Ajustes (Compras, Kiosko), `/tpv` (Saldo, pedidos
   del kiosko), navegación, ruta pública. Tests de navegación y de ruta pública.
6. Revisión final, una pasada de correcciones, despliegue y humo en producción.

## Foco de revisión
- Dos cobros a saldo a la vez del mismo cliente (no puede quedar negativo).
- Devolver una venta con consigna ya liquidada (el pendiente queda negativo y se ve).
- Token de kiosko de otra cuenta o inventado; pedidos en masa.
- Anular una compra cuyas cartas ya se vendieron.
- Reparto de un descuento de ticket entre líneas en consigna (redondeo).
