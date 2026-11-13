# Fase 0 — Núcleo multi-TCG y modo tienda

Fecha: 2026-11-11 · Estado: pendiente de revisión

## Contexto y objetivo

OpenYuGi pasa de ser un tracker de Yu-Gi-Oh para coleccionistas a una plataforma
gratuita (sin planes de pago) para coleccionistas **y** tiendas, con varios juegos
de cartas. Es la primera de cinco fases (0 núcleo, 1 inventario y precios, 2 venta
en tienda, 3 canales, 4 extras). Las fases 1-4 se construyen sobre la interfaz
genérica que define esta fase.

**Éxito de la Fase 0:**

1. Una cuenta puede crear una colección de Magic o Pokémon, buscar cartas en el
   catálogo de ese juego, añadirlas con condición/idioma/cantidad y verlas en su
   colección.
2. Todo lo que hoy funciona con Yu-Gi-Oh sigue funcionando igual, sin migrar
   ficheros.
3. Una cuenta puede activar el modo tienda y guardar el perfil de su tienda.
4. Añadir otro juego más adelante consiste en escribir un proveedor nuevo y
   registrarlo.

**Fuera de alcance:** precios y reprecio (Fase 1), cualquier venta (Fase 2+),
mazos y escáner para juegos distintos de Yu-Gi-Oh.

## Decisión de arquitectura

Enfoque aditivo. Yu-Gi-Oh conserva su modelo (`src/core/models.py`), su servicio
(`ygo_service`) y todas sus vistas. Los demás juegos usan un modelo y un
almacén nuevos y genéricos. Así ninguna vista de Yu-Gi-Oh (≈700 KB de UI que
asume `card_id: int`) ve colecciones de otros juegos.

## Componentes

### 1. Modelos genéricos — `src/core/catalog_models.py`

```python
class CatalogPrinting(BaseModel):
    printing_id: str          # único dentro del juego (p. ej. id de Scryfall)
    set_code: str
    set_name: str
    number: str | None = None
    rarity: str | None = None
    image_url: str | None = None
    image_url_small: str | None = None
    finishes: list[str] = []  # nonfoil, foil, holofoil, reverseHolofoil…

class CatalogCard(BaseModel):
    game: str
    card_id: str              # identidad abstracta (oracle_id en Magic)
    name: str
    printings: list[CatalogPrinting] = []
    attributes: dict[str, Any] = {}   # tipo, coste, HP… propio de cada juego

class GameCollectionVariant(BaseModel):
    printing_id: str
    set_code: str
    number: str | None = None
    rarity: str | None = None
    finish: str = "nonfoil"
    entries: list[CollectionEntry] = []   # reutiliza el modelo actual

class GameCollectionCard(BaseModel):
    card_id: str
    name: str
    variants: list[GameCollectionVariant] = []

class GameCollection(BaseModel):
    game: str
    name: str
    description: str = ""
    cards: list[GameCollectionCard] = []
```

Las entradas siguen la misma regla que hoy: son únicas por condición + idioma +
primera edición + ubicación; añadir una igual suma cantidad.

### 2. Proveedores de catálogo — `src/services/catalog/`

- `base.py`: clase abstracta `CatalogProvider` con `game`, `display_name`,
  `refresh() -> int` (descarga y compacta; devuelve nº de cartas),
  `is_available() -> bool`, `search(query, set_code=None, rarity=None, limit=60)`,
  `get(card_id)`, `sets()`.
- `registry.py`: `PROVIDERS: dict[str, CatalogProvider]`, `get_provider(game)`.
- `store.py`: lee/escribe el catálogo compacto `data/catalog/<game>.json`
  (lista de `CatalogCard`), escritura atómica (tmp + `os.replace`), carga
  perezosa en memoria e índice por nombre en minúsculas para la búsqueda.
- `yugioh.py`: adaptador de solo lectura sobre `ygo_service` (convierte `ApiCard`
  a `CatalogCard`). Se usa solo para las vistas genéricas y las fases 1-4; las
  vistas de Yu-Gi-Oh siguen usando `ygo_service` directamente.
- `magic.py`: pide `https://api.scryfall.com/bulk-data` y descarga
  `default_cards` desde `jsonl_download_uri`, línea a línea con `requests`
  (`stream=True`), agrupando por `oracle_id`. `User-Agent` propio genérico
  (`OpenYuGi/1.0`) y `Accept: application/json`, como pide Scryfall.
- `pokemon.py`: descarga `sets/en.json` y `cards/en/<set>.json` del repositorio
  público `PokemonTCG/pokemon-tcg-data` (sin clave). Cada carta es su propia
  identidad (`card_id = id`), con una impresión.

Las descargas se ejecutan siempre con `await run.io_bound(provider.refresh)`. Si
fallan, el catálogo anterior se conserva intacto y se lanza la excepción para
que la UI la muestre.

Imágenes: se muestran por URL remota (Scryfall y pokemontcg.io sirven CDN
público). No se cachean en disco en esta fase.

### 3. Almacén de colecciones genéricas — `src/core/game_collections.py`

`GameCollectionStore` con `list(game)`, `load(game, filename)`,
`save(game, collection, filename)` y `delete(game, filename)`.
Ruta: `<raíz de la cuenta>/games/<game>/collections/`, donde la raíz es `data`
para la cuenta principal y `data/users/<cuenta>` para las demás (mismo criterio
que `account_scope`). Nombres saneados con `sanitize_collection_filename`;
`game` validado contra el registro. Escritura atómica.

Mutaciones solo a través de `GameCollectionEditor.apply_change(collection,
card, printing, finish, entry_fields, delta)`, equivalente al `CollectionEditor`
actual: crea y limpia tarjetas/variantes vacías.

### 4. Perfil de cuenta y modo tienda — `src/core/account_profile.py`

Fichero `<raíz de la cuenta>/profile.json`:

```json
{"shop_mode": false,
 "enabled_games": ["yugioh"],
 "shop": {"name": "", "address": "", "city": "", "country": "",
          "currency": "EUR", "email": ""}}
```

`load_profile()` / `save_profile(profile)` con valores por defecto si no existe o
está corrupto. Es por cuenta, no global (el `config.json` actual es global).

### 5. Interfaz (diseño y tema actuales, iconos IconKit)

- **Ajustes**: sección «Juegos» con un interruptor por juego registrado, estado
  del catálogo (nº de cartas y fecha) y botón «Descargar/actualizar catálogo»
  con indicador de progreso. Sección «Modo tienda» con el interruptor y el
  formulario del perfil.
- **Catálogo** (`/catalog/{game}`, `src/ui/catalog.py`): selector de juego
  (solo juegos activos distintos de Yu-Gi-Oh; Yu-Gi-Oh sigue en sus páginas),
  búsqueda por nombre, filtros de set y rareza, cuadrícula de cartas, ficha con
  impresiones y diálogo «Añadir a colección» (colección, impresión, acabado,
  condición, idioma, cantidad).
- **Colecciones genéricas** (`/games/{game}/collection`): selector de
  colección, crear/borrar colección, cuadrícula con cantidades y quitar unidades.
- **Navegación**: la barra muestra «Catálogo» solo si hay algún juego activo
  además de Yu-Gi-Oh. Indicador «Tienda» junto al usuario si `shop_mode`.
- Estados vacíos: juego sin catálogo → «Descargar catálogo»; sin colecciones →
  «Crear colección».

### 6. Rutas

Registradas en `main.py` y protegidas por el middleware de autenticación
existente: `/catalog`, `/catalog/{game}`, `/games/{game}/collection`. Un `game`
desconocido o no activo redirige a `/catalog`.

## Errores

- Fallo de red o JSON inválido en `refresh()`: no se toca el catálogo previo;
  la UI muestra `ui.notify(..., type='negative')` con el motivo.
- Catálogo corrupto en disco: se registra en el log y se trata como no
  disponible.
- Nombre de colección o juego inválido: `ValueError`, la UI lo muestra en línea.

## Tests (`python -m pytest tests/`)

- Proveedores Magic y Pokémon con muestras JSON/JSONL pequeñas en
  `tests/fixtures/catalog/` y `requests` simulado: agrupación por `oracle_id`,
  impresiones, búsqueda y filtros.
- Adaptador Yu-Gi-Oh con un `ApiCard` de ejemplo.
- Catálogo: un fallo en `refresh()` conserva el fichero anterior.
- `GameCollectionEditor`: sumar a entrada existente, restar hasta borrar
  variante y tarjeta.
- `GameCollectionStore` y `account_profile`: aislamiento entre cuentas y
  rechazo de rutas con `..`.
- Regresión: `persistence.list_collections()` no lista colecciones genéricas.
- Prueba de navegador (Playwright, local): activar Magic con un catálogo de
  muestra, crear colección, añadir una carta y verla en la colección.

## Despliegue

Copiar los ficheros nuevos/modificados a producción y reiniciar la tarea
`OpenYuGi`. La primera descarga de cada catálogo la lanza el usuario desde
Ajustes. Magic es un volcado de varios cientos de MB que se lee en streaming y
no se guarda entero; solo se guarda el catálogo compacto.
