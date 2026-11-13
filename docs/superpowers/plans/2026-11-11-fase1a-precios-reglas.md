# Fase 1a — Precios y reglas: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Precios de mercado diarios gratuitos por juego y mercado, precio de venta por entrada, reglas de reprecio con vista previa y aplicación automática, y valor de cada colección.

**Architecture:**
- **Fuentes de precio:** `src/services/prices/` sigue el patrón de `src/services/catalog/`, con un almacén JSON perezoso y fuentes intercambiables tras un registro.
- **Datos de dominio:** los modelos Pydantic de `src/core/pricing_models.py` y unos campos nuevos con valor por defecto en los modelos existentes.
- **Reprecio:** un servicio puro, `src/services/repricing.py`, al que las páginas llaman mediante una barra común, `src/ui/components/pricing_bar.py`.

**Tech Stack:** Python 3.12, NiceGUI 3.13, Pydantic 2, requests, pytest.

**Spec:** `docs/superpowers/specs/2026-11-11-fase1a-precios-reglas-design.md`

## Global Constraints

- Gratis y sin planes. Solo fuentes públicas sin clave: Cardmarket S3, Scryfall, pokemontcg.io y la BD local de Yu-Gi-Oh.
- Todos los campos nuevos de los modelos son opcionales con valor por defecto, para que los JSON antiguos carguen igual.
- Las mutaciones de colecciones pasan solo por `CollectionEditor` o `GameCollectionEditor`.
- La E/S de disco y red se hace en `run.io_bound` (UI) o `asyncio.to_thread` (planificador), nunca en el bucle de eventos.
- Iconos solo de IconKit, autoalojados en `static/icons/` y renderizados con `src/ui/icons.py`.
- Peticiones HTTP con `User-Agent: OpenYuGi/1.0`. El email de la cuenta no se envía nunca.
- Los textos de la interfaz van en español.
- Mercados: `{'cardmarket': 'EUR', 'tcgplayer': 'USD'}`. Por defecto, `cardmarket`.
- Los tests no tocan la red ni `data/`: usan `tmp_path` y fixtures en `tests/fixtures/prices/`.

## Review Focus

1. **JSON antiguos.** Una colección de Yu-Gi-Oh de producción, sin campos nuevos, se carga, se reprecia, se guarda y se vuelve a cargar sin perder `storage_definitions` ni entradas. Test en la Task 2.
2. **Descarga de precios vacía o rota.** Si la descarga falla o llega vacía, se conserva el fichero anterior y la UI dice por qué. Test en la Task 3.
3. **Reprecio automático entre cuentas.** Cada cuenta usa su raíz y su mercado; nunca se escribe en `data/` con la regla de otra cuenta. Test en la Task 6.
4. **Redondeo `x49_x99` en los bordes:** 0,00 (aplica el mínimo), 1,49, 1,50, 1,99 y 2,00. Test en la Task 5.
5. **Catálogo de Magic sin `market_ids`.** El error es claro y no se borran los precios. Test en la Task 4.

---

### Task 1: Modelos de precio y `market_ids`

**Files:**
- Create: `src/core/pricing_models.py`.
- Modify:
  - `src/core/catalog_models.py`: añade `market_ids` a `CatalogPrinting`.
  - `src/services/catalog/magic.py`: rellena `market_ids`.
- Test:
  - `tests/test_pricing_models.py`
  - `tests/test_catalog_magic.py`, con un caso nuevo.
  - Fixture: añadir `cardmarket_id`/`tcgplayer_id` a una línea de `tests/fixtures/catalog/scryfall_default.jsonl`.

**Interfaces:**
- Produces:
  - `PriceQuote(low, avg, trend, avg1, avg7, avg30: float|None)`
  - `PrintingPrice(normal: PriceQuote|None, foil: PriceQuote|None, scope: Literal['printing','card']='printing')`
  - `PricingRule`, con los campos y valores por defecto de la spec.
  - `DEFAULT_CONDITION_FACTORS: dict[str, float]`
  - `to_price(value) -> float|None`: convierte vacío, 0 o no numérico en `None`.
  - `CatalogPrinting.market_ids: dict[str, str] = {}`

- [ ] **Step 1: Escribir los tests que fallan.**
  - `test_rule_defaults`: `PricingRule().metric == 'trend'`, `min_price == 0.10` y `condition_factors['Excellent'] == 90`.
  - `test_to_price`: `to_price('1.5') == 1.5`; `to_price('')`, `to_price(0)`, `to_price('abc')` y `to_price(None)` devuelven `None`.
  - `test_cards_from_jsonl_keeps_market_ids`: la impresión con ids tiene `market_ids == {'cardmarket': '<id>', 'tcgplayer': '<id>'}`; la que no los tiene, `{}`.
  - `test_old_catalog_json_loads_without_market_ids`.
- [ ] **Step 2:** Ejecutar `python -m pytest tests/test_pricing_models.py tests/test_catalog_magic.py -q`. Expected: FAIL (ImportError / KeyError).
- [ ] **Step 3:** Implementar los modelos y, en `cards_from_jsonl`, `market_ids={k: str(raw[f'{k}_id']) for k in ('cardmarket','tcgplayer') if raw.get(f'{k}_id')}`.
- [ ] **Step 4:** Ejecutar lo mismo. Expected: PASS.

### Task 2: Campos nuevos en colecciones, perfil y editores

**Files:**
- Modify:
  - `src/core/models.py`: `CollectionEntry`, `Collection`.
  - `src/core/catalog_models.py`: `GameCollection`.
  - `src/core/account_profile.py`: `AccountProfile.price_market`.
  - `src/services/collection_editor.py`.
  - `src/core/game_collections.py`: `GameCollectionEditor`.
- Test: `tests/test_pricing_fields.py`

**Interfaces:**
- Produces:
  - `CollectionEntry.list_price: float|None = None`
  - `CollectionEntry.price_locked: bool = False`
  - `Collection.for_sale` y `GameCollection.for_sale: bool = False`
  - `.pricing_rule: PricingRule|None = None`
  - `AccountProfile.price_market: Literal['cardmarket','tcgplayer'] = 'cardmarket'`
  - `CollectionEditor.set_list_price(entry: CollectionEntry, price: float|None, locked: bool|None = None) -> bool`
  - `GameCollectionEditor.set_list_price(...)`, con la misma firma: delega en la misma función.
  - `iter_priced_entries(collection) -> Iterator[EntryRef]` en `src/services/repricing.py`, que se define aquí porque la usan las Tasks 5 y 7.
  - `EntryRef(card_id: str, name: str, printing_id: str, set_code: str, rarity: str|None, finish: str, entry: CollectionEntry)`
    - Yu-Gi-Oh: `printing_id = variant_id` y `finish = 'nonfoil'`.
    - Otros juegos: `printing_id = variant.printing_id` y `finish = variant.finish`.

- [ ] **Step 1: Escribir los tests que fallan.**
  - `test_old_ygo_collection_round_trip`: un JSON sin campos nuevos y con `storage_definitions` carga y vuelca con `model_dump` sin perder claves.
  - `test_old_game_collection_loads`.
  - `test_profile_default_market == 'cardmarket'`.
  - `test_set_list_price_rounds_and_locks`: con 1.234 queda 1.23 y `locked=True` deja `price_locked` a True. Devuelve False si no cambia nada.
  - `test_iter_priced_entries_both_games`: comprueba ids y acabados.
- [ ] **Step 2:** Ejecutar `python -m pytest tests/test_pricing_fields.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implementar. `set_list_price` guarda `round(price, 2)` o `None`.
- [ ] **Step 4:** Ejecutar el mismo comando y después `python -m pytest tests -q`. Expected: PASS, salvo los 6 fallos que ya existían (`test_auth` ×3 y `test_ui_filters` ×3).

### Task 3: Almacén y base de fuentes de precio

**Files:**
- Create:
  - `src/services/prices/__init__.py`
  - `store.py`
  - `base.py`
  - `registry.py`
- Test: `tests/test_price_store.py`

**Interfaces:**
- Consumes: `PrintingPrice` (Task 1).
- Produces:
  - `PriceStore(path)`, con `load() -> dict[str, PrintingPrice]`, `get(printing_id)`, `replace(mapping)`, `info() -> {'count','updated_at'}` y `unload()`.
    - Mismo patrón que `CatalogStore`, con escritura atómica y fichero `.meta.json`.
    - Las entradas se serializan con `exclude_none`, para que el fichero sea pequeño.
  - `PriceSource(ABC)`, con los atributos `game`, `market` y `store`, el método abstracto `fetch() -> dict[str, PrintingPrice]` y `refresh() -> int`.
    - `refresh()` reutiliza la misma protección contra descargas simultáneas de `CatalogProvider`, con la clave `(game, market)`.
    - Una descarga vacía lanza `RuntimeError('La descarga no trajo precios; se conservan los anteriores.')`.
  - `PRICES_DIR = 'data/prices'`
  - `MARKETS`
  - `price_path(game, market) -> str`: devuelve `data/prices/<game>-<market>.json`.
  - `register(source)`
  - `get_source(game, market)`, que lanza KeyError si no existe.
  - `sources()`

- [ ] **Step 1: Escribir los tests que fallan.**
  - `round_trip`
  - `info_without_loading`
  - `failed_fetch_keeps_file`
  - `empty_fetch_keeps_file`
  - `concurrent_refresh_refused`: copia del patrón de `tests/test_catalog_store.py`.
  - `get_source_unknown_raises`
- [ ] **Step 2:** Ejecutar `python -m pytest tests/test_price_store.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Ejecutar el mismo comando. Expected: PASS.

### Task 4: Las cinco fuentes

**Files:**
- Create:
  - `src/services/prices/magic.py`: `MagicCardmarketSource`, `MagicTcgplayerSource`.
  - `src/services/prices/pokemon.py`: `PokemonCardmarketSource`, `PokemonTcgplayerSource`.
  - `src/services/prices/yugioh.py`: `YugiohCardmarketSource`, `YugiohTcgplayerSource`.
- Las registra `__init__.py`.
- Fixtures en `tests/fixtures/prices/`:
  - `price_guide_1.json`, con 3 productos, uno con foil.
  - `pokemon_page.json`: 2 cartas, una con reverse holo y otra solo holofoil.
  - `scryfall_prices.jsonl`
  - `ygo_db.json`: 1 carta con 2 sets y `card_prices`.
  - `daily_card_pricing.json`
- Test: `tests/test_price_sources.py`

**Interfaces:**
- Consumes:
  - `PriceSource` y `price_path` de la Task 3.
  - `get_provider('magic').store.load()`, del catálogo.
  - `_dump_lines` y `HEADERS` de `src/services/catalog/magic.py`.
  - `ygo_service._read_db_file('en')` y `pricing_service.daily_pricing`.
- Produces: funciones puras, testeadas sin red. Las clases solo añaden la descarga.
  - `guide_to_prices(guide: dict, cm_to_printing: dict[str, list[str]]) -> dict[str, PrintingPrice]`
  - `scryfall_lines_to_prices(lines) -> dict`
  - `pokemon_cards_to_prices(cards: list[dict], market: str) -> dict`
  - `ygo_to_prices(db: list[dict], market: str, manual: dict) -> dict`, donde las claves son `variant_id` o `f'{set_code}:{set_rarity}'`, igual que `catalog_card_from_api`.

- [ ] **Step 1: Escribir los tests que fallan.** Uno por función, con las correspondencias exactas de la sección «Modelo común» de la spec.
  - `guide_to_prices`: `avg-foil` pasa a `foil.avg`, y un `idProduct` que no está en el mapa se ignora.
  - `pokemon_cards_to_prices`: `reverseHoloTrend` pasa a `foil.trend`; en la carta solo holo, `normal` sale de `holofoil`.
  - `ygo_to_prices`, mercado cardmarket: las dos impresiones tienen `scope == 'card'`; la impresión con captura manual tiene la última fecha y `scope == 'printing'`.
  - `ygo_to_prices`, mercado tcgplayer: usa `set_price` por impresión.
  - Además:
    - `test_magic_cardmarket_without_market_ids_raises`: el catálogo falso no tiene ids; lanza `RuntimeError` con el texto «Vuelve a descargar el catálogo de Magic».
    - `test_pokemon_fetch_paginates`: con `requests.get` mockeado, pide hasta que `data` vuelve vacío, con `time.sleep` parcheado. Si una página falla, lanza el error.
- [ ] **Step 2:** Ejecutar `python -m pytest tests/test_price_sources.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implementar.
  - URLs:
    - Cardmarket: `https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json`
    - Pokémon: `https://api.pokemontcg.io/v2/cards?page=N&pageSize=250&select=id,cardmarket,tcgplayer`, con 1 s de pausa entre páginas y `timeout=60`.
  - Magic TCGplayer: usa el `bulk-data` de Scryfall igual que el catálogo, pero lee solo `id` y `prices`.
- [ ] **Step 4:** Ejecutar el mismo comando. Expected: PASS.

### Task 5: Cálculo de reprecio, vista previa y aplicación

**Files:**
- Modify: `src/services/repricing.py`, creado en la Task 2.
- Test: `tests/test_repricing.py`

**Interfaces:**
- Consumes:
  - `PricingRule` y `PrintingPrice` (Task 1).
  - `EntryRef`, `iter_priced_entries` y `set_list_price` (Task 2).
- Produces:
  - `compute_price(rule: PricingRule, quote: PriceQuote|None, condition: str) -> float|None`
  - `quote_for(price: PrintingPrice|None, finish: str) -> PriceQuote|None`
  - `RepriceRow(ref: EntryRef, market: float|None, current: float|None, new: float|None, delta: float|None, status: Literal['cambia','igual','bloqueada','sin precio'])`
  - `preview(collection, prices: Callable[[str], PrintingPrice|None], rule) -> list[RepriceRow]`
  - `apply(collection, rows) -> int`: devuelve el número de cambios escritos.
  - `collection_values(collection, prices) -> tuple[float, float]`: devuelve `(valor de mercado = Σ qty×trend, venta = Σ qty×list_price)`.
  - `validate_rule(rule) -> list[str]`: devuelve los mensajes de error en español.

- [ ] **Step 1: Escribir los tests que fallan.**
  - Redondeo con `rounding='x49_x99'` y `percent=100`: base 1.20 → 1.49; 1.49 → 1.49; 1.50 → 1.99; 1.99 → 1.99; 2.00 → 2.49; con base 0.01 y `min_price` 0.10, el resultado es 0.49 (el mínimo se aplica después).
  - `step_005`: 1.23 → 1.25; 1.22 → 1.20. `none`: 1.234 → 1.23.
  - Fórmula: con trend 10, 95 %, +0,50 y Excellent queda 10×0.95×0.9 + 0.5 = 9.05.
  - Respaldo de métrica: si piden `avg30` y no existe, se usa `trend`; si no hay nada, `None`.
  - Condición desconocida → factor 100.
  - `quote_for`: `foil` usa `foil` y, si falta, `normal`.
  - `preview` y `apply`:
    - Las entradas bloqueadas y sin precio no cambian.
    - `apply` devuelve el número de filas `cambia` y solo escribe esas.
  - `collection_values`.
  - `validate_rule`: `percent=0` y `condition_factors` negativo dan error.
- [ ] **Step 2:** Ejecutar `python -m pytest tests/test_repricing.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implementar.
  - `x49_x99`: primero `p = round(p, 2)` para evitar errores de coma flotante. Después se toma el menor de `{floor(p)+0.49, floor(p)+0.99, floor(p)+1.49}` que sea ≥ p.
  - Después se aplica `max(p, min_price)` y se redondea a 2 decimales.
- [ ] **Step 4:** Ejecutar el mismo comando. Expected: PASS.

### Task 6: Planificador diario y reprecio automático

**Files:**
- Create: `src/services/prices/scheduler.py`.
- Modify: `main.py`, que lo arranca en `app.on_startup`.
- Test: `tests/test_price_scheduler.py`

**Interfaces:**
- Consumes:
  - `sources()` y `PriceSource.refresh` (Task 3).
  - `preview` y `apply` (Task 5).
  - `load_profile(root)`
  - `PersistenceManager(data_dir=<root>/collections)`
  - `GameCollectionStore(root_resolver=lambda: root)`
- Produces:
  - `account_roots(base='data') -> list[str]`: devuelve `'data'` más cada subcarpeta de `data/users/`.
  - `due_sources(now: datetime, markets_in_use: set[str]) -> list[PriceSource]`:
    - Solo si `now.hour >= 5`.
    - Solo fuentes caducadas (> 20 h o sin descargar).
    - Las de TCGplayer, solo si `'tcgplayer'` está en `markets_in_use`.
  - `run_daily(now) -> dict`:
    - Refresca y captura los errores por fuente.
    - Después aplica el reprecio automático y devuelve un resumen.
  - `auto_reprice(root: str) -> int`
  - `start_scheduler()`: crea un `asyncio` task que cada 3600 s hace `await asyncio.to_thread(run_daily, datetime.now())`.

- [ ] **Step 1: Escribir los tests que fallan.**
  - `due_sources`:
    - A las 04:00 → nada.
    - A las 06:00 con una fuente de hace 21 h → incluida; con una de hace 2 h → no.
    - Sin cuentas TCGplayer, las fuentes de TCGplayer no se incluyen.
  - `run_daily`: si una fuente falla, las demás siguen.
  - `auto_reprice`, en dos raíces de `tmp_path`:
    - Raíz A, mercado cardmarket: una colección `for_sale` con `auto_apply` se reprecia; otra sin `auto_apply` no cambia.
    - Raíz B, mercado tcgplayer: usa precios de tcgplayer. Una colección corrupta se salta y no lanza error.
- [ ] **Step 2:** Ejecutar `python -m pytest tests/test_price_scheduler.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implementar. Las raíces son siempre explícitas; nunca se usa `account_root()`.
- [ ] **Step 4:** Ejecutar el mismo comando. Expected: PASS.

### Task 7: Interfaz (Ajustes, barra y diálogo de precios)

**Files:**
- Create:
  - `src/ui/components/pricing_bar.py`
  - `static/icons/tag.svg` y `static/icons/trending-up.svg`, descargados de `https://iconkit.suils.es/svg/outline/{nombre}.svg`. Antes hay que comprobar el nombre en `manifest.json`.
- Modify:
  - `src/ui/settings_games.py`: añadir `render_prices_section()`.
  - `src/ui/settings.py`: llamarla.
  - `src/ui/collection.py`: poner la barra en `render_header`.
  - `src/ui/game_collection.py`: la barra y el precio en cada carta de la rejilla.
- Test: `tests/test_pricing_ui.py`, solo con helpers puros, como en `test_settings_games.py`.

**Interfaces:**
- Consumes:
  - Todo lo anterior.
  - `account_root()` y `load_profile` / `save_profile`.
  - `can_manage_catalogs()`
- Produces:
  - `format_money(value: float|None, market: str) -> str`: `12.5` con cardmarket da `'12,50 €'`; con tcgplayer, `'$12.50'`; `None` da `'—'`.
  - `price_status_text(info) -> str`: mismo formato que `catalog_status_text`.
  - `render_pricing_bar(collection, game: str, save: Callable[[], Awaitable[None]])`

- [ ] **Step 1: Escribir los tests que fallan.**
  - `format_money`
  - `price_status_text`
  - `row_to_table_dict(row)`: el dict que pinta la tabla del diálogo, con estado y referencia.
- [ ] **Step 2:** Ejecutar `python -m pytest tests/test_pricing_ui.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implementar la UI tal como la describe la spec, sección «Interfaz».
  - Toda la E/S va en `run.io_bound`.
  - «Aplicar cambios» pide confirmación con el número de cambios, aplica y llama a `save()`.
  - En Yu-Gi-Oh, `save()` es el guardado existente de `CollectionPage`, mediante `persistence`.
- [ ] **Step 4:** Ejecutar `python -m pytest tests -q`. Expected: todo PASS salvo los 6 fallos que ya existían.
- [ ] **Step 5: Verificación en navegador.**
  - Lanzar en local (puerto 8206, cuenta testsprite) y, con Playwright:
    - Ajustes → «Precios»: el selector y el botón aparecen.
    - Colección de Pokémon con una carta: «Precios…» → «Vista previa» → «Aplicar cambios»; la barra muestra el valor.
    - La misma comprobación en una colección de Yu-Gi-Oh.
  - Capturas: JPEG de ≤ 800 px.

### Task 8: Revisión final y despliegue

- [ ] **Step 1:** Hacer la revisión de toda la rama con un revisor nuevo, según `superpowers:executing-plans`. Después, una única pasada de corrección.
- [ ] **Step 2:** Desplegar en producción (`C:\inetpub\vhosts\suils.es\tgoct.suils.es`):
  - Copiar a `App_Data\bak-20261111\fase1a\` una copia de seguridad de los ficheros que se modifican.
  - Copiar el código.
  - Reiniciar `OpenYuGi`: Stop-ScheduledTask, matar el proceso que escucha en 8205 y Start-ScheduledTask.
  - Volver a descargar el catálogo de Magic.
  - Pulsar «Actualizar precios ahora».
  - Comprobar que `logs\app.log` no tiene errores y que la web muestra precios de los tres juegos.
