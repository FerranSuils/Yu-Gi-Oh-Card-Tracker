# Fase 0 — Núcleo multi-TCG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que una cuenta pueda activar Magic y Pokémon, descargar sus catálogos, crear colecciones de esos juegos y añadir cartas, y que pueda activar el modo tienda con su perfil, sin cambiar nada de Yu-Gi-Oh.

**Architecture:** Aditiva. Modelos genéricos (`catalog_models.py`), proveedores de catálogo enchufables (`src/services/catalog/`), almacén de colecciones por juego en `<raíz cuenta>/games/<game>/collections/` y perfil por cuenta en `<raíz cuenta>/profile.json`. Yu-Gi-Oh sigue con `models.py`, `ygo_service` y sus vistas; solo un adaptador de lectura lo expone por la interfaz genérica.

**Tech Stack:** Python 3.12, NiceGUI 3.13, Pydantic 2, requests (streaming), pytest, Playwright (node) para la prueba de navegador.

**Spec:** `docs/superpowers/specs/2026-11-11-fase0-nucleo-multitcg-design.md`

## Global Constraints

- Ninguna vista ni servicio de Yu-Gi-Oh cambia de comportamiento; `persistence.list_collections()` sigue listando solo ficheros de nivel superior.
- Toda E/S de red o disco grande desde la UI va en `await run.io_bound(...)`.
- Escrituras atómicas: fichero temporal en el mismo directorio + `os.replace`.
- Raíz de cuenta: `data` para la cuenta principal; `data/users/<cuenta>` para las demás (`account_scope.current_account_name()` + `uses_private_storage()` + `user_data_root()`).
- Juegos registrados en esta fase: `yugioh`, `magic`, `pokemon`. `enabled_games` por defecto: `["yugioh"]`.
- Perfil por defecto: `{"shop_mode": false, "enabled_games": ["yugioh"], "shop": {"name": "", "address": "", "city": "", "country": "", "currency": "EUR", "email": ""}}`.
- Scryfall: `GET https://api.scryfall.com/bulk-data`, entrada `type == "default_cards"`, descargar `jsonl_download_uri`; cabeceras `User-Agent: OpenYuGi/1.0` y `Accept: application/json`.
- Pokémon: `https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master/sets/en.json` y `.../cards/en/<set_id>.json`.
- Iconos nuevos: SVG outline de IconKit (`https://iconkit.suils.es/svg/outline/{nombre}.svg`, comprobar el nombre en `manifest.json`), nunca Material.
- Textos de UI en español, con el estilo de las páginas actuales (`page_header`, tokens `--oy-*`, funciona en tema claro y oscuro).
- Tests sin red: `requests` simulado con `unittest.mock.patch`; ficheros en `tmp_path`.
- No hacer commit salvo que Ferran lo pida: los pasos «Commit» de este plan se sustituyen por «dejar los cambios listos y la suite en verde» hasta entonces.

## Review Focus

- Búsqueda con texto vacío, con mayúsculas/acentos («Æther», «Pokémon») o con caracteres especiales: debe devolver resultados por coincidencia insensible a mayúsculas y no fallar → test en Task 2 (`test_search_is_case_insensitive_and_handles_empty_query`).
- Carta de Magic de doble cara sin `image_uris` en la raíz (solo en `card_faces`): debe tener imagen de la primera cara → test en Task 3 (`test_double_faced_card_uses_first_face_image`).
- Línea JSONL corrupta o carta de Scryfall sin `oracle_id` (p. ej. tokens raros, `reversible_card`): se salta esa línea y sigue → test en Task 3 (`test_skips_bad_lines_and_cards_without_oracle_id`).
- Dos cuentas con la misma colección «Mis cartas» en Magic: cada una ve solo la suya → test en Task 5 (`test_store_isolates_accounts`).
- Quitar más unidades de las que hay: la cantidad no queda negativa; la variante y la carta desaparecen → test en Task 5 (`test_removing_more_than_owned_deletes_variant_and_card`).

---

### Task 1: Modelos genéricos

**Files:**
- Create: `src/core/catalog_models.py`
- Test: `tests/test_catalog_models.py`

**Interfaces:**
- Consumes: `CollectionEntry` de `src/core/models.py`.
- Produces: `CatalogPrinting`, `CatalogCard`, `GameCollectionVariant`, `GameCollectionCard`, `GameCollection` exactamente con los campos de la sección 1 de la spec. `GameCollectionCard.total_quantity` y `GameCollection.total_cards` como propiedades (suma de `entries[].quantity`).

- [ ] **Step 1: Write the failing tests**

```python
def test_game_collection_round_trips_through_json():
    col = GameCollection(game='magic', name='Mis cartas', cards=[GameCollectionCard(
        card_id='o1', name='Lightning Bolt', variants=[GameCollectionVariant(
            printing_id='p1', set_code='lea', entries=[CollectionEntry(quantity=3)])])])
    again = GameCollection(**col.model_dump(mode='json'))
    assert again == col and again.total_cards == 3
    assert again.cards[0].variants[0].finish == 'nonfoil'

def test_catalog_card_defaults():
    card = CatalogCard(game='pokemon', card_id='base1-4', name='Charizard')
    assert card.printings == [] and card.attributes == {}
```

- [ ] **Step 2: Run** `python -m pytest tests/test_catalog_models.py -v` → FAIL (ImportError).
- [ ] **Step 3: Implement** the five models in `src/core/catalog_models.py`.
- [ ] **Step 4: Run** the same command → 2 passed.
- [ ] **Step 5: Commit** `feat: add generic multi-game catalog and collection models`.

### Task 2: Almacén de catálogo y registro de proveedores

**Files:**
- Create: `src/services/catalog/__init__.py`, `src/services/catalog/base.py`, `src/services/catalog/store.py`, `src/services/catalog/registry.py`
- Test: `tests/test_catalog_store.py`

**Interfaces:**
- Consumes: `CatalogCard` (Task 1).
- Produces:
  - `CatalogStore(path: str)` con `load() -> list[CatalogCard]` (perezoso, cacheado; `[]` si no existe o está corrupto, registrando el error), `replace(cards: list[CatalogCard]) -> None` (atómico, invalida caché), `info() -> dict` (`{"count": int, "updated_at": str | None}` desde un `<path>.meta.json`), `search(query: str, set_code: str | None = None, rarity: str | None = None, limit: int = 60) -> list[CatalogCard]`, `get(card_id: str) -> CatalogCard | None`, `sets() -> list[tuple[str, str]]` (código, nombre; ordenado por nombre).
  - `CatalogProvider` (ABC) con atributos `game: str`, `display_name: str`, `store: CatalogStore`; método abstracto `fetch() -> list[CatalogCard]`; métodos concretos `refresh() -> int` (llama a `fetch()`, luego `store.replace`; si `fetch()` lanza, no toca el store y relanza), `is_available() -> bool` (`store.info()["count"] > 0`), y `search/get/sets` delegando en el store.
  - `CATALOG_DIR = os.path.join('data', 'catalog')`; `PROVIDERS: dict[str, CatalogProvider]`; `register(provider)`; `get_provider(game: str) -> CatalogProvider` (`KeyError` si no existe); `game_ids() -> list[str]`.
- Búsqueda: coincidencia por subcadena sobre `name.casefold()`; consulta vacía devuelve las primeras `limit` cartas ordenadas por nombre; filtros `set_code`/`rarity` exigen al menos una impresión que cumpla.

- [ ] **Step 1: Write the failing tests** — `test_replace_then_load_round_trip`, `test_refresh_failure_keeps_previous_catalog` (proveedor falso cuyo `fetch` lanza `RuntimeError`; tras `pytest.raises`, `load()` devuelve las cartas anteriores), `test_corrupt_file_reads_as_empty`, `test_search_filters_by_set_and_rarity`, `test_search_is_case_insensitive_and_handles_empty_query` (`search('æther')` encuentra «Æther Vial»; `search('')` devuelve ≤ limit sin error), `test_get_provider_unknown_game_raises`.
- [ ] **Step 2: Run** `python -m pytest tests/test_catalog_store.py -v` → FAIL.
- [ ] **Step 3: Implement** the four files.
- [ ] **Step 4: Run** → all pass.
- [ ] **Step 5: Commit** `feat: add catalog store and provider registry`.

### Task 3: Proveedor de Magic (Scryfall)

**Files:**
- Create: `src/services/catalog/magic.py`, `tests/fixtures/catalog/scryfall_bulk.json`, `tests/fixtures/catalog/scryfall_default.jsonl`
- Modify: `src/services/catalog/__init__.py` (registrar)
- Test: `tests/test_catalog_magic.py`

**Interfaces:**
- Consumes: `CatalogProvider`, `CatalogStore`, `register` (Task 2).
- Produces: `MagicProvider(game='magic', display_name='Magic: The Gathering')`, `fetch() -> list[CatalogCard]`, y la función pura `cards_from_jsonl(lines: Iterable[str]) -> list[CatalogCard]` que usa `fetch`.
- Mapeo por carta Scryfall: agrupa por `oracle_id` → `card_id`; `name`; impresión con `printing_id=id`, `set_code=set`, `set_name`, `number=collector_number`, `rarity`, `finishes`, `image_url=image_uris.normal`, `image_url_small=image_uris.small` (si falta `image_uris`, usar `card_faces[0].image_uris`); `attributes = {type_line, mana_cost, colors}` de la primera impresión vista.
- `fetch()`: `requests.get(bulk_url, headers=..., timeout=30)`, elegir `default_cards`, luego `requests.get(jsonl_download_uri, headers=..., stream=True, timeout=60)` y `iter_lines(decode_unicode=True)`; `raise_for_status()` en ambas.

- [ ] **Step 1: Write the failing tests** — fixture JSONL con 4 líneas: dos impresiones del mismo `oracle_id`, una carta de doble cara, una línea `{"broken"`, una carta sin `oracle_id`. Tests: `test_groups_printings_by_oracle_id` (2 impresiones, `set_code` y `number` correctos), `test_double_faced_card_uses_first_face_image`, `test_skips_bad_lines_and_cards_without_oracle_id` (resultado: 2 cartas), `test_fetch_uses_default_cards_jsonl_with_headers` (`requests.get` simulado; comprueba la URL `jsonl_download_uri` y `User-Agent: OpenYuGi/1.0`).
- [ ] **Step 2: Run** `python -m pytest tests/test_catalog_magic.py -v` → FAIL.
- [ ] **Step 3: Implement** `src/services/catalog/magic.py` and register it.
- [ ] **Step 4: Run** → 4 passed.
- [ ] **Step 5: Commit** `feat: add Scryfall-backed Magic catalog provider`.

### Task 4: Proveedores de Pokémon y Yu-Gi-Oh

**Files:**
- Create: `src/services/catalog/pokemon.py`, `src/services/catalog/yugioh.py`, `tests/fixtures/catalog/pokemon_sets.json`, `tests/fixtures/catalog/pokemon_base1.json`
- Modify: `src/services/catalog/__init__.py`
- Test: `tests/test_catalog_pokemon_yugioh.py`

**Interfaces:**
- Consumes: Task 2; `ygo_service` y `ApiCard` existentes.
- Produces:
  - `PokemonProvider(game='pokemon', display_name='Pokémon TCG')`; `fetch()` descarga `sets/en.json` y cada `cards/en/<id>.json`. Cada carta: `card_id=id`, una impresión `printing_id=id`, `set_code=<set id>`, `set_name`, `number`, `rarity`, `image_url=images.large`, `image_url_small=images.small`; `attributes={supertype, subtypes, hp, types}`. Un set cuyo fichero da 404 se salta y se registra; cualquier otro error relanza.
  - `YugiohProvider(game='yugioh', display_name='Yu-Gi-Oh!')`: `fetch()` convierte `ygo_service.load_card_database()` (lista de `ApiCard`) con la función pura `catalog_card_from_api(card: ApiCard) -> CatalogCard` (`card_id=str(id)`, una impresión por `card_sets` con `printing_id=variant_id or f"{set_code}:{set_rarity}"`, imagen de `card_images[0]`). `refresh()` no descarga nada nuevo: solo reconstruye desde la base local.

- [ ] **Step 1: Write the failing tests** — `test_pokemon_maps_card_fields`, `test_pokemon_skips_missing_set_file` (un set devuelve 404, el otro carga), `test_yugioh_converts_api_card` (con un `ApiCard` mínimo de dos `card_sets`).
- [ ] **Step 2: Run** `python -m pytest tests/test_catalog_pokemon_yugioh.py -v` → FAIL.
- [ ] **Step 3: Implement** both providers and register them (orden: yugioh, magic, pokemon).
- [ ] **Step 4: Run** → 3 passed; `game_ids() == ['yugioh', 'magic', 'pokemon']`.
- [ ] **Step 5: Commit** `feat: add Pokemon and Yu-Gi-Oh catalog providers`.

### Task 5: Raíz de cuenta, almacén y editor de colecciones genéricas

**Files:**
- Modify: `src/core/account_scope.py` (añadir `account_root() -> str`)
- Create: `src/core/game_collections.py`
- Test: `tests/test_game_collections.py`

**Interfaces:**
- Consumes: Task 1; `sanitize_collection_filename` de `src/core/persistence.py`; `game_ids()` (Task 2).
- Produces:
  - `account_root() -> str`: `user_data_root(name)` si `uses_private_storage(current_account_name())`, si no `'data'`.
  - `GameCollectionStore(root_resolver: Callable[[], str] = account_root)` con `list(game) -> list[str]`, `load(game, filename) -> GameCollection`, `save(game, collection, filename) -> None` (atómico), `delete(game, filename) -> None`. Ruta `os.path.join(root, 'games', game, 'collections', filename)`. `game` desconocido o `'yugioh'` → `ValueError` (Yu-Gi-Oh usa `persistence`).
  - `GameCollectionEditor.apply_change(collection: GameCollection, card: CatalogCard, printing: CatalogPrinting, finish: str, delta: int, condition: str = 'Near Mint', language: str = 'EN', first_edition: bool = False, storage_location: str | None = None) -> None`: entrada única por (condición, idioma, 1ª ed., ubicación); `delta` positivo suma o crea; negativo resta, borrando entrada, variante (clave `printing_id` + `finish`) y carta cuando quedan vacías.
  - Instancia global `game_collection_store = GameCollectionStore()`.

- [ ] **Step 1: Write the failing tests** — `test_add_merges_into_matching_entry`, `test_removing_more_than_owned_deletes_variant_and_card`, `test_store_round_trip_and_list`, `test_store_rejects_path_traversal_and_yugioh` (`'../x.json'` y `game='yugioh'` → `ValueError`), `test_store_isolates_accounts` (dos `root_resolver` con distintos `tmp_path`), `test_persistence_does_not_list_game_collections` (guardar en `games/magic/...` y comprobar que `PersistenceManager(data_dir=tmp).list_collections()` sigue vacío).
- [ ] **Step 2: Run** `python -m pytest tests/test_game_collections.py -v` → FAIL.
- [ ] **Step 3: Implement** `account_root` and `src/core/game_collections.py`.
- [ ] **Step 4: Run** → 6 passed, and `python -m pytest tests/ -q` keeps the 6 pre-existing failures and no new ones.
- [ ] **Step 5: Commit** `feat: store per-game collections per account`.

### Task 6: Perfil de cuenta y modo tienda

**Files:**
- Create: `src/core/account_profile.py`
- Test: `tests/test_account_profile.py`

**Interfaces:**
- Consumes: `account_root()` (Task 5), `game_ids()` (Task 2).
- Produces: modelos `ShopProfile` y `AccountProfile` (campos y valores por defecto de Global Constraints); `load_profile(root: str | None = None) -> AccountProfile` (por defecto si falta o está corrupto); `save_profile(profile: AccountProfile, root: str | None = None) -> None` (atómico; `root=None` usa `account_root()`); `enabled_games(profile) -> list[str]` que siempre incluye `'yugioh'` y descarta juegos no registrados.

- [ ] **Step 1: Write the failing tests** — `test_missing_profile_returns_defaults`, `test_corrupt_profile_returns_defaults`, `test_save_and_load_round_trip`, `test_enabled_games_always_includes_yugioh_and_drops_unknown` (`['magic', 'nope']` → `['yugioh', 'magic']`).
- [ ] **Step 2: Run** `python -m pytest tests/test_account_profile.py -v` → FAIL.
- [ ] **Step 3: Implement** `src/core/account_profile.py`.
- [ ] **Step 4: Run** → 4 passed.
- [ ] **Step 5: Commit** `feat: add per-account profile with shop mode`.

### Task 7: Ajustes — juegos y modo tienda

**Files:**
- Create: `src/ui/settings_games.py` (render de las dos secciones; mantiene `settings.py` acotado)
- Modify: `src/ui/settings.py` (llamar a `render_games_section()` y `render_shop_section()` antes de «Data management»)
- Test: `tests/test_settings_games.py`

**Interfaces:**
- Consumes: Tasks 2, 6.
- Produces: `render_games_section() -> None`, `render_shop_section() -> None`, y la función pura `catalog_status_text(info: dict) -> str` (`"Sin descargar"` si `count == 0`; si no `"{count:,} cartas · actualizado {fecha}"` con separador de miles `.`).
- Juegos: fila por proveedor con `ui.switch` (Yu-Gi-Oh activado y deshabilitado), estado y botón «Descargar catálogo» / «Actualizar catálogo» que ejecuta `await run.io_bound(provider.refresh)`, desactiva el botón mientras corre y notifica éxito (`f"{n:,} cartas"`) o el error (`type='negative'`). Al cambiar un interruptor, guarda el perfil.
- Tienda: `ui.switch('Modo tienda')` y campos Nombre, Dirección, Ciudad, País, Moneda (select `EUR`, `USD`, `GBP`), Email; botón «Guardar tienda». Email validado con `@` y punto en el dominio; error en línea.

- [ ] **Step 1: Write the failing tests** — `test_catalog_status_text` (0 → «Sin descargar»; 12345 → contiene «12.345 cartas»), `test_settings_page_calls_new_sections` (aserción sobre el código fuente de `settings.py`, como en `test_config_language.py`).
- [ ] **Step 2: Run** `python -m pytest tests/test_settings_games.py -v` → FAIL.
- [ ] **Step 3: Implement** `settings_games.py` and wire it into `settings.py`.
- [ ] **Step 4: Run** → pass; start local instance (port 8206) and check `/settings` shows both sections in light and dark theme.
- [ ] **Step 5: Commit** `feat: manage games and shop profile from settings`.

### Task 8: Páginas Catálogo y Colección genérica, rutas y navegación

**Files:**
- Create: `src/ui/catalog.py`, `src/ui/game_collection.py`, `static/icons/` (SVG IconKit que se usen: búsqueda, más, papelera, tienda)
- Modify: `main.py` (rutas), `src/ui/layout.py` (enlace «Catálogo» e indicador «Tienda»)
- Test: `tests/test_catalog_pages.py`, `scratchpad/pw/fase0.js` (fuera del repo)

**Interfaces:**
- Consumes: Tasks 2, 5, 6.
- Produces:
  - `catalog_page(game: str | None) -> None` en `/catalog` y `/catalog/{game}`; `game_collection_page(game: str) -> None` en `/games/{game}/collection`.
  - Función pura `resolve_game(game: str | None, enabled: list[str]) -> str | None`: devuelve el juego si está activo y no es `yugioh`; si `game` es `None`, el primer activo distinto de `yugioh`; si no, `None` (la página redirige a `/catalog` o, si no hay ninguno, muestra «Activa un juego en Ajustes»).
  - Función pura `nav_items(profile: AccountProfile) -> list[tuple[str, str]]`: `NAV_ITEMS` + `('Catálogo', '/catalog')` si hay algún juego activo distinto de `yugioh`.
- Catálogo: pestañas por juego activo; buscador (Enter), selects de set y rareza; cuadrícula de 60 resultados con imagen pequeña, nombre y set; clic abre ficha con impresiones y diálogo «Añadir a colección» (colección existente o nueva, impresión, acabado de `printing.finishes` o `nonfoil`, condición, idioma, cantidad 1-999) que usa `GameCollectionEditor` + `game_collection_store.save` en `run.io_bound`. Catálogo no disponible → estado vacío con botón que lleva a `/settings`.
- Colección genérica: select de colección, «Nueva colección», «Borrar colección» con confirmación, cuadrícula con imagen, nombre, set, acabado, condición y cantidad, y botón «−1».
- Rutas protegidas por el middleware existente (no añadir a `PUBLIC_PATHS`).

- [ ] **Step 1: Write the failing tests** — `test_resolve_game` (casos: activo, inactivo, `yugioh`, `None` con y sin activos), `test_nav_items_adds_catalog_only_with_other_games`, `test_routes_registered` (aserción sobre `main.py`: `@ui.page('/catalog')`, `'/catalog/{game}'`, `'/games/{game}/collection'`).
- [ ] **Step 2: Run** `python -m pytest tests/test_catalog_pages.py -v` → FAIL.
- [ ] **Step 3: Implement** the two pages, routes and nav changes.
- [ ] **Step 4: Run** pytest → pass. Then browser check against local 8206 with a sample Magic catalog written via `CatalogStore.replace` (3 cartas): log in, activate Magic in `/settings`, open `/catalog/magic`, search «bolt», add 2× to new collection «Prueba», open `/games/magic/collection` and assert «Lightning Bolt» with quantity 2; repeat the screenshot in dark theme; confirm `/collection` (Yu-Gi-Oh) still loads without errors.
- [ ] **Step 5: Commit** `feat: add multi-game catalog and collection pages`.

### Task 9: Verificación final y despliegue

**Files:** ninguno nuevo.

- [ ] **Step 1:** `python -m pytest tests/ -q` → only the 6 pre-existing failures (3 `test_auth` chmod, 3 `test_ui_filters`).
- [ ] **Step 2:** Backup to `C:\inetpub\vhosts\suils.es\tgoct.suils.es\App_Data\bak-<fecha>\fase0\` of every production file that will be overwritten; copy new/modified files; restart scheduled task `OpenYuGi` (stop task, kill the 8205 listener, start task).
- [ ] **Step 3:** In production with a temporary account: download the Pokémon catalog from `/settings`, add one card, see it in the collection; delete the temporary account (`accounts.json` + `data/users/<cuenta>`).
- [ ] **Step 4:** Download the Magic catalog once in production and record time and resulting `data/catalog/magic.json` size in the final report.
