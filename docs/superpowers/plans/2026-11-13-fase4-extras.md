# Fase 4 — Extras Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Informes, puntos, eventos, API de lectura, mapa de tiendas, lista de mazo contra stock y PWA.

**Architecture:** Módulos puros en `src/services/` sobre los libros existentes (`Desk`); páginas NiceGUI finas.
Estado nuevo en JSON bajo `<cuenta>/shop/`.

**Tech Stack:** Python 3.12, NiceGUI 3.13 (`ui.echart`, `ui.leaflet`), Pydantic 2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-fase4-extras-design.md`

## Global Constraints

- Sin BD; E/S en `run.io_bound`; solo `Inventory` muta colecciones; céntimos enteros.
- Iconos IconKit en `static/icons`, cada módulo UI con su tupla `ICONS`.
- Mapas: Leaflet + teselas OSM con atribución; Nominatim con UA `OpenYuGi/1.0`; nada más.
- Secretos nunca en logs, toasts ni HTML. Tests en directorios temporales.
- Suite: `python -m pytest tests -q` (6 fallos previos conocidos: `test_auth` ×3, `test_ui_filters` ×3).

## Review Focus

1. Venta devuelta tras dar puntos: los puntos se restan una sola vez.
2. Evento con jugadores impares y retirados: nadie recibe dos byes ni juega contra un retirado.
3. API: clave de otra cuenta, clave revocada, cabecera mal formada → 401 sin filtrar datos.
4. Informes con libros vacíos o fechas invertidas: ceros, no excepción.
5. Mapa: dirección que Nominatim no encuentra o red caída → no se publica y se explica.

---

### Task 1: Informes (servicio)
**Files:** Create `src/services/reports/__init__.py`, `src/services/reports/summary.py`; Test `tests/test_reports.py`.
**Produces:** `period(name: str, today: date) -> tuple[date, date]`; `build(sales: list[Sale], orders: list[Order],
purchases: list[Purchase], start: date, end: date, tz=None) -> Report` (campos `revenue_cents, count, units,
average_cents, purchases_cents, by_day: list[tuple[str,int]], by_channel: dict[str,int], by_method: dict[str,int],
top: list[TopCard(name,set_code,units,cents)]`); `stock_value(items: list[SaleLine]) -> tuple[int,int]`;
`report_csv(report) -> bytes`; `gather(desk, start, end) -> Report`.

### Task 2: Informes (página)
**Files:** Create `src/ui/reports.py`; Modify `main.py`, `src/ui/layout.py`; Test `tests/test_reports_page.py`.
Ruta `/informes`, en `SHOP_ROUTES` y `nav_items`.

### Task 3: Fidelización
**Files:** Create `src/services/shop/loyalty.py`; Modify `src/core/shop_models.py` (LedgerKind + `LoyaltyRules`),
`src/services/shop/customers.py` (`points`), `src/services/sales/checkout.py` (`_close`, `_undo_money`),
`src/services/shop/desk.py`, `src/ui/customers.py`, `src/ui/settings_shop.py`; Test `tests/test_loyalty.py`.
**Produces:** `Loyalty(root, customers)` con `rules()`, `save_rules(rules)`, `earn(sale)`, `reverse(sale)`,
`redeem(customer_id) -> tuple[int,int]`; `points_for(total_cents, rules) -> int`.

### Task 4: Eventos (servicio)
**Files:** Create `src/core/event_models.py`, `src/services/events/{__init__,swiss,store}.py`; Test `tests/test_events.py`.
**Produces:** `pair(players, rounds, rng) -> list[Match]`, `standings(event) -> list[Standing]`,
`EventStore(root)` con `all, get, create, enter, drop, set_paid, start, next_round, report, finish, remove`.

### Task 5: Eventos (página)
**Files:** Create `src/ui/events.py`; Modify `main.py`, `src/ui/layout.py`; Test `tests/test_events_page.py`.

### Task 6: API de lectura
**Files:** Create `src/services/shop/api_keys.py`, `src/services/shop/public_api.py`; Modify `main.py`,
`src/services/auth_middleware.py` (prefijo público `/api/v1/shop/`), `src/ui/settings_shop.py`; Test `tests/test_public_api.py`.
**Produces:** `create(root) -> str`, `revoke(root)`, `hint(root)`, `account_for(key, base)`;
`stock_rows(items)`, `order_rows(orders)`, `sale_rows(sales)`; router montado en `main.py`.

### Task 7: Mapa
**Files:** Create `src/services/shop/shop_map.py`, `src/ui/shop_map.py`; Modify `main.py`, `auth_middleware.py`
(`/mapa` público), `src/ui/settings_shop.py`; Test `tests/test_shop_map.py`.
**Produces:** `geocode(address, http) -> tuple[float,float] | None`, `publish(root, profile, http)`, `unpublish(root)`,
`pins(base) -> list[Pin]`.

### Task 8: Lista de mazo
**Files:** Create `src/services/sales/decklist.py`, `src/ui/decklist.py`; Modify `main.py`, `layout.py`; Test `tests/test_decklist.py`.
**Produces:** `parse(text) -> list[Wanted(name, quantity)]`, `match(wanted, items) -> list[Found]`,
`available_lines(found) -> list[SaleLine]`.

### Task 9: PWA
**Files:** Create `static/brand/icon-192.png`, `icon-512.png`, `src/ui/pwa.py`; Modify `main.py`, `src/ui/theme.py`,
`auth_middleware.py`; Test `tests/test_pwa.py`.
**Produces:** `manifest() -> dict`, `SERVICE_WORKER: str`, `HEAD_HTML: str`; rutas `/manifest.webmanifest`, `/sw.js`.

### Task 10: Despliegue, humo en producción, revisión final y una pasada de arreglos.
