# Fase 1a — Precios de mercado, precio de venta y reglas de reprecio

Fecha: 2026-11-11 · Estado: pendiente de revisión · Depende de: Fase 0

## Contexto y objetivo

Las colecciones son el inventario (decisión de la Fase 1). Esta subfase les da
precios: precio de mercado diario de fuentes gratuitas, un precio de venta por
entrada, reglas para calcularlo y el valor total de cada colección. Todo gratis,
sin planes. La CSV Suite queda para la Fase 1b.

**Éxito de la Fase 1a:**

1. Cada madrugada el servidor descarga solo los precios de Magic, Pokémon y
   Yu-Gi-Oh; la cuenta principal también puede forzarlo desde Ajustes.
2. Cada cuenta elige su mercado de referencia en Ajustes: **Cardmarket (EUR)**,
   por defecto, o **TCGplayer (USD)**. El precio del otro mercado se ve como
   referencia cuando está descargado.
3. Una colección puede marcarse «A la venta» y tener una regla de precio. La
   vista previa muestra antes, después y diferencia por entrada; al confirmar se
   guardan los precios. Las entradas bloqueadas no se tocan.
4. Cada colección muestra su valor de mercado y su precio de venta total.
5. Las colecciones existentes, de Yu-Gi-Oh y de otros juegos, siguen cargando
   sin cambios: todos los campos nuevos tienen valor por defecto.

## Fuentes de precio

| Juego | Cardmarket (EUR) | TCGplayer (USD) | Alcance |
|---|---|---|---|
| Magic | Guía oficial diaria `price_guide_1.json`, unida por `cardmarket_id` | Volcado `default_cards` de Scryfall: `usd` y `usd_foil` | Por impresión |
| Pokémon | API pokemontcg.io, campo `cardmarket.prices` | Misma API, campo `tcgplayer.prices` | Por impresión |
| Yu-Gi-Oh | `card_prices[0].cardmarket_price` de la BD local | `sets[].set_price` de la BD local | Cardmarket **por carta**; TCGplayer por impresión |

- **Magic Cardmarket**: se descarga
  `https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json`.
  Para unirla, el catálogo necesita el `cardmarket_id` de cada impresión.
  `CatalogPrinting` gana `market_ids: dict[str, str] = {}`, y `magic.py` lo
  rellena con `cardmarket` (`cardmarket_id`) y `tcgplayer` (`tcgplayer_id`)
  cuando vienen. Si el catálogo actual no tiene ningún `market_ids`, la fuente
  falla con «Vuelve a descargar el catálogo de Magic» y no borra precios
  anteriores.
- **Magic TCGplayer**: se usa el mismo volcado que el catálogo (gzip, ver
  `_dump_lines`), leyendo solo `id`, `prices.usd` y `prices.usd_foil`.
- **Pokémon**: `GET https://api.pokemontcg.io/v2/cards?page=N&pageSize=250&select=id,cardmarket,tcgplayer`.
  Son unas 85 páginas y se pausa 1 s entre ellas, sin clave. El `id` es el
  `printing_id` del catálogo (`base1-4`). Un error en una página aborta la
  descarga, que se reintenta al día siguiente.
- **Yu-Gi-Oh**: no hay descarga nueva. Se lee la BD local (`ygo_service._read_db_file('en')`),
  así que los precios son tan recientes como la última actualización de la BD en
  Data management. Una captura manual de Cardmarket (`pricing_service.daily_pricing`,
  la fecha más reciente) **sustituye** el precio por carta de esa impresión y
  marca el alcance como «por impresión».

### Modelo común

En `src/core/pricing_models.py`:

```python
class PriceQuote(BaseModel):          # todas en la moneda del mercado
    low: float | None = None
    avg: float | None = None
    trend: float | None = None
    avg1: float | None = None
    avg7: float | None = None
    avg30: float | None = None

class PrintingPrice(BaseModel):
    normal: PriceQuote | None = None
    foil: PriceQuote | None = None
    scope: Literal['printing', 'card'] = 'printing'
```

Así se traduce cada fuente a este modelo:

- **Guía de Cardmarket**:
  - `low`, `avg`, `trend`, `avg1`, `avg7` y `avg30` pasan tal cual a `normal`.
  - Los campos `*-foil` pasan a `foil`.
- **Cardmarket en pokemontcg.io**:
  - `normal`:
    - `lowPrice` → `low`
    - `averageSellPrice` → `avg`
    - `trendPrice` → `trend`
    - `avg1`, `avg7` y `avg30` pasan tal cual.
  - `foil`:
    - `reverseHoloLow` → `low`
    - `reverseHoloSell` → `avg`
    - `reverseHoloTrend` → `trend`
    - `reverseHoloAvg1`, `reverseHoloAvg7` y `reverseHoloAvg30` → `avg1`, `avg7` y `avg30`.
- **TCGplayer** (Scryfall y pokemontcg.io):
  - `market` → `trend`, `mid` → `avg` y `low` → `low`.
  - En pokemontcg.io, `normal` sale de `normal` o, si no existe, de `holofoil`.
  - `foil` sale de `holofoil` o `reverseHolofoil`.
  - En Scryfall solo hay `usd` (→ `normal.trend`) y `usd_foil` (→ `foil.trend`).
- **Yu-Gi-Oh**:
  - `cardmarket_price` → `normal.trend`, con alcance `card`.
  - `set_price` → `normal.trend`, con alcance `printing`.
  - La captura manual → `normal.trend`.

Los valores vacíos, `0` o no numéricos se guardan como `None`.

### Almacén y descarga

- `src/services/prices/store.py` define `PriceStore(path)`. Funciona igual que
  `CatalogStore`:
  - `load()` es perezoso y se guarda en caché.
  - `replace(mapping)` escribe de forma atómica y añade `<path>.meta.json` con
    `{count, updated_at}`.
  - También tiene `info()` y `get(printing_id) -> PrintingPrice | None`.
- Los ficheros van en `data/prices/<juego>-<mercado>.json` (`magic-cardmarket.json`…).
  Se comparten entre cuentas porque son datos públicos. No se tocan los ficheros
  antiguos de `data/prices/` (`daily_card_pricing.json`, `cardmarket_offers_pricing.json`).
- `src/services/prices/sources.py` define `PriceSource(ABC)` con `game`,
  `market`, `store`, `fetch() -> dict[str, PrintingPrice]` y `refresh() -> int`.
  `refresh()` tiene la misma protección que `CatalogProvider.refresh`: no admite
  dos descargas a la vez, y una descarga vacía lanza un error y conserva el
  fichero anterior.
- `src/services/prices/registry.py` contiene `get_source(game, market)` y
  `MARKETS = {'cardmarket': 'EUR', 'tcgplayer': 'USD'}`.
- `src/services/prices/scheduler.py` define `PriceScheduler`:
  - Se arranca en `app.on_startup` y comprueba cada hora.
  - Si son ≥ 05:00 (hora del servidor) y el último `updated_at` de una fuente
    tiene más de 20 h, la refresca con `asyncio.to_thread`.
  - Siempre refresca las fuentes Cardmarket. Las TCGplayer solo si alguna cuenta
    eligió ese mercado.
  - Después ejecuta el reprecio automático (ver más abajo).
  - Los errores se registran en el log y no paran el bucle.

## Precio de venta y reglas

### Datos nuevos (todos opcionales)

- `CollectionEntry` (lo comparten Yu-Gi-Oh y los demás juegos) gana:
  - `list_price: float | None = None` (precio de venta, en la moneda del mercado
    de la cuenta)
  - `price_locked: bool = False`
- `Collection` y `GameCollection` ganan `for_sale: bool = False` y
  `pricing_rule: PricingRule | None = None`.
- `PricingRule` (en `pricing_models.py`):
  - `metric: Literal['trend','avg','low','avg1','avg7','avg30'] = 'trend'`
  - `percent: float = 100.0`
  - `fixed: float = 0.0`
  - `min_price: float = 0.10`
  - `rounding: Literal['none','x49_x99','step_005'] = 'none'`
  - `condition_factors: dict[str, float]`, con este valor por defecto:
    Mint 100, Near Mint 100, Excellent 90, Good 80, Light Played 70, Played 60,
    Poor 40 y Damaged 30
  - `auto_apply: bool = False`
- `AccountProfile` gana `price_market: Literal['cardmarket','tcgplayer'] = 'cardmarket'`.
  La moneda de los precios es siempre la del mercado. `ShopProfile.currency` no se
  usa en esta fase; queda para el TPV de la Fase 2.

### Cálculo (`src/services/repricing.py`)

`compute_price(rule, quote, condition) -> float | None`:

1. Se toma `base = quote.<metric>`. Si falta, se prueba en este orden: `trend`,
   `avg` y `low`. Si no hay ninguno, el resultado es `None` («sin precio»).
2. Se calcula `p = base × percent/100 × condition_factors[condition]/100 + fixed`.
3. Se redondea según la regla:
   - `none`: a 2 decimales.
   - `step_005`: al múltiplo de 0,05 más cercano.
   - `x49_x99`: hacia arriba, al siguiente ,49 o ,99. Por ejemplo, 1,20 queda en
     1,49, 1,50 queda en 1,99 y 1,99 se queda igual.
4. El resultado es `max(p, min_price)`, con 2 decimales.

Qué cotización se usa:

- Si el acabado de la entrada no es `nonfoil` (otros juegos), se usa `foil`; si
  no hay, `normal`.
- Yu-Gi-Oh siempre usa `normal`.

Funciones del servicio:

- `preview(entries, prices, rule) -> list[RepriceRow]`. Cada `RepriceRow` lleva
  la carta, la impresión, la condición, la cantidad, el mercado, el precio
  actual, el nuevo, la diferencia y el estado. Los estados posibles son
  `cambia`, `igual`, `bloqueada` y `sin precio`.
- `apply(collection, rows)` solo escribe las filas `cambia`. Lo hace mediante
  un método nuevo del editor, `set_list_price(...)`, en `CollectionEditor` y
  `GameCollectionEditor`, porque el editor es el único que muta colecciones. El
  mismo método sirve para fijar un precio a mano y para bloquearlo.

### Reprecio automático

Después de la descarga diaria, el planificador recorre las carpetas de cuenta:
`data` y cada subcarpeta de `data/users/`. Usa raíces explícitas, nunca la
sesión. En cada colección con `for_sale` y `pricing_rule.auto_apply`:

1. Aplica la regla con el mercado de esa cuenta.
2. Guarda la colección de forma atómica.

Si una colección no se puede leer, se registra el error y se continúa con la
siguiente.

## Interfaz

- **Ajustes → «Precios»**:
  - Un selector para el mercado de referencia (Cardmarket EUR o TCGplayer USD).
  - Solo para la cuenta principal, el estado de cada fuente (número de
    impresiones con precio y fecha) y un botón «Actualizar precios ahora».
- **Barra de precios** (`src/ui/components/pricing_bar.py`), en la página de
  colección de Yu-Gi-Oh y en la de otros juegos. Contiene:
  - «Valor de mercado: X €», que es la suma de cantidad × `trend` del mercado de
    la cuenta, sin factor de condición.
  - «Precio de venta: Y €», que es la suma de cantidad × `list_price`.
  - El interruptor «A la venta».
  - El botón «Precios…».
- **Diálogo «Precios…»**:
  - Arriba, el editor de la regla: métrica, %, fijo, mínimo, redondeo, factores
    de condición y «Aplicar cada día».
  - Debajo, una tabla paginada de 50 en 50 con una fila por entrada.
  - En cada fila se puede editar el precio a mano y bloquearlo.
  - Botones «Vista previa» y «Aplicar cambios» (pide confirmación con el número
    de cambios).
  - El precio del otro mercado sale como referencia en gris cuando existe.
  - Las cartas de Yu-Gi-Oh con alcance `card` llevan la nota «precio por carta».
- La rejilla de la colección de otros juegos muestra en cada carta el precio de
  mercado y, si lo tiene, el de venta.
- Iconos solo de IconKit, autoalojados en `static/icons` (`tag`,
  `trending-up`), con el mismo patrón que `src/ui/icons.py`.
- Todo el trabajo de disco y red se hace con `run.io_bound` o `asyncio.to_thread`.

## Errores

- Si falla una descarga (red, HTTP o JSON), se conserva el fichero anterior y
  Ajustes muestra el error en la notificación.
- Si una entrada no tiene precio de mercado, sale como «sin precio» y no cambia.
- Si en la colección hay una condición que no está en `condition_factors`, se
  aplica factor 100.
- Si `percent` es ≤ 0 o un factor es < 0, la regla no se guarda y el diálogo lo
  muestra junto al campo.

## Pruebas

Las pruebas siguen el modelo TDD, con fixtures pequeñas en `tests/fixtures/prices/`
y sin red:

- Traducción de cada fuente:
  - Guía de Cardmarket con unión por `market_ids`.
  - Scryfall usd.
  - pokemontcg.io, con y sin reverse holo.
  - Yu-Gi-Oh por carta y la captura manual que la sustituye.
- Escritura atómica de `PriceStore`, su `info()` y la regla de que una descarga
  vacía no borra el fichero.
- `compute_price`:
  - Cada redondeo, con los ejemplos de arriba.
  - El mínimo y el fijo.
  - El factor de condición.
  - La métrica que falta con su orden de respaldo.
  - Foil frente a normal.
- `preview` y `apply`:
  - Bloqueadas y sin precio no cambian.
  - Solo se escriben las filas `cambia`.
- Compatibilidad: una colección JSON antigua de Yu-Gi-Oh y una de otro juego
  cargan y se guardan sin perder campos.
- Planificador: con un reloj falso, refresca solo lo caducado y aplica el
  reprecio automático solo a las colecciones marcadas, cada una con la raíz de su
  cuenta.
- `market_ids` en `cards_from_jsonl`.

## Despliegue

Pasos en producción:

1. Copiar el código.
2. Reiniciar la tarea `OpenYuGi`.
3. Volver a descargar el catálogo de Magic, para que tenga `market_ids`.
4. Pulsar «Actualizar precios ahora» y comprobar en la web que salen los precios
   de Magic, Pokémon y Yu-Gi-Oh.

## Fuera de alcance

- CSV Suite (Fase 1b).
- Histórico de precios y gráficas.
- Precios por idioma o primera edición.
- Precio por impresión de Cardmarket para Yu-Gi-Oh mediante emparejamiento
  automático.
- Cardmarket y TCGplayer en otras monedas.
