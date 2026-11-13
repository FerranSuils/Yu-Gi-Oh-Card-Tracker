# Fase 4 — Extras: informes, fidelización, eventos, API, mapa, mazos y PWA

Última fase de la paridad funcional con SortSwift. Todo gratis, sin planes. Cada pieza es pequeña y
se apoya en lo que ya existe (ventas, pedidos, compras, clientes, inventario, kiosko).

## Reglas comunes

- Sin base de datos: JSON bajo `<cuenta>/shop/`, con `read_list` / `write_list` y `root_lock`.
- Lógica en `src/services/`, modelos en `src/core/`, UI en `src/ui/`. E/S bloqueante en `run.io_bound`.
- Solo `Inventory.take/give_back` toca las colecciones.
- Importes en céntimos enteros; textos en español; iconos IconKit autoalojados.
- Las páginas de tienda (`/informes`, `/eventos`, `/lista`) piden modo tienda, como `/pedidos`.

## 1. Informes — `/informes`

Lee los tres libros: ventas del mostrador, pedidos y compras.

- Periodo: hoy, 7 días, 30 días, este mes, mes pasado, este año, o dos fechas. Días en hora local.
- Cuenta como ingreso: venta `paid` (por `paid_at`); pedido que no esté `new` (sin pagar), `cancelled` ni `returned`
  (por `paid_at`, o `created_at` si falta). Una venta `refunded` no cuenta. Compras `done` son gasto.
- Cifras: ingresos, nº de operaciones, ticket medio, unidades, compras, ingresos por día, por canal
  (Mostrador + cada canal de pedidos), por forma de pago (solo mostrador), 20 cartas más vendidas
  (unidades e ingresos), y valor del stock a precio de venta (unidades y céntimos, ahora).
- Exportar el periodo en CSV (una fila por día y otra tabla de cartas).
- Los envíos de pedidos van dentro del ingreso del pedido (`total_cents`).

## 2. Fidelización — puntos

- Ajustes de tienda: activar, puntos por cada unidad de moneda cobrada (por defecto 1), y canje:
  N puntos = X de saldo de tienda (por defecto 100 puntos = 1,00).
- Al cobrar una venta con cliente se suman `floor(total / 100 * puntos_por_unidad)` puntos. Lo pagado
  con saldo de tienda no da puntos. Al devolver la venta se restan los que dio (el saldo de puntos puede
  quedar negativo: se ha gastado lo que se devolvió).
- Los puntos son un tercer tipo de movimiento del libro de clientes (`points`; `cents` = puntos).
- Canjear, desde la ficha del cliente: solo bloques completos; resta puntos y suma saldo de tienda en la
  misma operación.
- Si apuntar puntos falla, la venta sigue en pie y se anota en el ticket (como la consigna).

## 3. Eventos — `/eventos`

Torneos de tienda con emparejamiento suizo.

- Evento: nombre, juego, fecha, precio de inscripción, aforo (0 = sin límite), estado
  (`open` inscripciones → `running` → `finished`).
- Jugadores: nombre, cliente opcional, pagado sí/no, retirado sí/no. Se inscribe solo mientras está `open`
  y hay sitio; nombre repetido se rechaza.
- Rondas: emparejar exige que todos los resultados de la ronda anterior estén puestos. Suizo: orden por
  puntos, sin repetir rival mientras sea posible, descanso (bye, cuenta como victoria) para el último
  que no lo haya tenido cuando son impares. Resultados: gana A, gana B, empate. 3 / 1 / 0 puntos.
- Clasificación: puntos, luego % de victorias de los rivales (mínimo 33 %, byes fuera), luego nombre.
- Se puede corregir un resultado de la ronda actual; no de rondas anteriores.
- El cobro de la inscripción no pasa por caja automáticamente: se marca "pagado" a mano.

## 4. API pública de la tienda — `/api/v1/shop/…`

Solo lectura, para la web de la tienda o sus scripts.

- Clave por cuenta, creada en Ajustes; se enseña una sola vez; se guarda su SHA-256. Regenerar o revocar.
- `Authorization: Bearer oy_…`. Sin clave o clave mala: 401. Más de 60 peticiones por minuto y clave: 429.
- `GET /api/v1/shop/stock` (cartas con precio: juego, nombre, set, número, rareza, estado, idioma,
  cantidad, precio, SKU), `GET …/orders` (pedidos sin datos personales salvo ciudad y país),
  `GET …/sales?month=AAAA-MM` (ventas cobradas del mes, sin cliente). JSON `{ "data": [...] }`.
- Nunca devuelve claves, correos, direcciones ni nombres de clientes.

## 5. Mapa de tiendas — `/mapa` (público)

- Ajustes de tienda: "Aparecer en el mapa". Al activarlo se geocodifica la dirección de la tienda con
  Nominatim (User-Agent `OpenYuGi/1.0`, una petición, sin correo) y se guardan latitud y longitud. Si no
  se encuentra, se dice y no se publica.
- `/mapa`: Leaflet con teselas de OpenStreetMap y su atribución; un marcador por tienda con nombre,
  dirección y, si tiene kiosko abierto, enlace a él. Modo oscuro con filtro CSS sobre las mismas teselas.
- Solo se publican nombre, dirección, ciudad, país y coordenadas. Desactivar lo borra del mapa.

## 6. Mazos — `/lista` (lista de mazo contra el stock)

- Se pega una lista (`3 Dark Hole`, `3x Dark Hole`, `Dark Hole` = 1; líneas vacías y `//`, `#` fuera).
- Para cada carta: copias pedidas, copias en stock con precio (las más baratas primero, cualquier juego
  activo), y cuántas faltan. Total de lo disponible.
- "Enviar al mostrador" crea una lista de kiosko con lo disponible, que el TPV ya sabe cargar.
- El constructor de mazos de Yu-Gi-Oh existente no cambia.

## 7. PWA

- `manifest.webmanifest` (nombre, colores, iconos 192 y 512, `display: standalone`, `start_url: /`),
  `sw.js` mínimo sin caché (la app es en vivo por websocket; sin conexión no funciona y no finge que sí),
  y las etiquetas en la cabecera de todas las páginas. Resultado: instalable en móvil y escritorio.

## Fuera de alcance

Cobro de inscripciones por caja, eliminatorias (top 8), puntos por pedidos online, escritura por API,
webhooks, búsqueda en el mapa, caché sin conexión, listas de mazo con formatos de exportación de cada juego.
