# Fase 3 — Canales Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Inline, TDD, ledger.

**Goal:** Pedidos por enviar con stock reservado, importación por fichero y enlace en vivo con Shopify/WooCommerce.

**Architecture:** Modelos en `src/core/order_models.py`; servicios en `src/services/orders/` (libro de
pedidos, importador, canales); UI en `src/ui/orders.py` y `src/ui/settings_channels.py`. Todo cuelga
de `Desk` (`desk.dispatch`). Ficheros JSON en `<cuenta>/shop/` con `read_list`/`write_list` y el
candado de la cuenta.

**Tech Stack:** Python 3.12, Pydantic 2, NiceGUI 3.13, requests.

**Spec:** `docs/superpowers/specs/2026-11-12-fase3-canales-design.md`

## Global Constraints

- Sin base de datos; E/S fuera del hilo de UI (`run.io_bound`); solo `Inventory.take/give_back` mueve stock.
- Iconos IconKit autoalojados en `static/icons`, declarados en `ICONS`.
- Errores para personas con `spoken = True`; nunca rutas ni secretos en avisos o registros.
- `User-Agent: OpenYuGi/1.0`. Sin correo del usuario hacia fuera.
- Sin commits.

## Review Focus

- Pedido repetido (misma referencia externa) importado dos veces → no duplica ni quita stock dos veces.
- Guardar falla tras quitar stock → el stock vuelve.
- URL de WooCommerce hacia red privada o con redirección → rechazada.
- CSV con fórmulas o nombres hostiles → no se ejecuta nada, se muestra como texto (NiceGUI escapa).
- Sincronización a medias (la tienda cae) → los pedidos ya creados quedan, no se repiten al reintentar.

## Tasks

### Task 1 — Modelos y libro de pedidos
Files: `src/core/order_models.py`, `src/services/orders/__init__.py`, `src/services/orders/book.py`,
`src/services/shop/desk.py`; Test `tests/test_orders_book.py`.
Produces: `Order`, `Address`, `ShippingMethod`, `ORDER_LABELS`, `CHANNEL_LABELS`;
`OrderBook(root, inventory)` con `all()`, `get(id)`, `create(lines, *, channel='manual', external_id='',
customer_name='', email='', address=None, method=None, shipping_cents=None, currency='EUR', paid=False,
note='', customer_id=None) -> Order`, `mark(id, status) -> Order`, `ship(id, carrier, tracking='')`,
`cancel(id)`, `returned(id, restock)`, `has(channel, external_id)`, `methods()`, `save_methods(list)`,
`pick_list(orders) -> List[Pick]`, `tracking_url(order)`; `OrderError`; `Desk.dispatch`.

### Task 2 — Importar pedidos por fichero
Files: `src/services/orders/importer.py`; Test `tests/test_orders_import.py`.
Produces: `Incoming(external_id, channel, customer_name, email, address, shipping_cents, currency,
articles: List[Article])`, `Article(name, set_code, condition, language, quantity, unit_cents, sku)`,
`parse_orders(data: bytes, channel) -> List[Incoming]`, `link(articles, items) -> List[SaleLine]`
(sin enlazar → `kind='custom'`, `unlinked=True`), `bring_in(book, incoming, items) -> Report(created, skipped, unlinked)`.
Consumes: `read_table` de `csv_suite`, `OrderBook`.

### Task 3 — Pantalla /pedidos y albarán
Files: `src/ui/orders.py`, `main.py`, `src/ui/layout.py`, `src/ui/shop_common.py`, `static/icons/*`;
Test `tests/test_orders_ui.py` (helpers puros, rutas, iconos).

### Task 4 — SKU, exportación de catálogo y credenciales de canal
Files: `src/services/orders/channels.py`; Test `tests/test_orders_channels.py`.
Produces: `sku_of(line)`, `shopify_csv(items)`, `woocommerce_csv(items)`, `ChannelSettings(root)` con
`save_shopify(domain, token)`, `save_woocommerce(url, key, secret)`, `summary()`, `forget(channel)`,
`client(channel)`; `check_public_https(url, resolve=...)`; `ChannelError`.

### Task 5 — Clientes Shopify/WooCommerce y sincronización
Files: `src/services/orders/shopify.py`, `src/services/orders/woocommerce.py`, `src/services/orders/sync.py`;
Test `tests/test_orders_sync.py`.
Produces: cada cliente `ping()`, `orders() -> List[Incoming]`, `push(quantities: Dict[sku, int]) -> PushReport(updated, missing)`;
`sync(book, client, items) -> SyncReport`.

### Task 6 — Ajustes de canales y botón de sincronizar
Files: `src/ui/settings_channels.py`, `src/ui/settings.py`, `src/ui/orders.py`; Test en `tests/test_orders_ui.py`.

### Cierre
Suite completa, despliegue con copia, humo Playwright, revisión fresca de toda la fase, una pasada de arreglos.
