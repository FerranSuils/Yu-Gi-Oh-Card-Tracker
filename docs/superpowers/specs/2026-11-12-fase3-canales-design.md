# Fase 3 — Canales: pedidos, envíos y tiendas enlazadas

## Para qué

Una tienda vende fuera del mostrador: en Cardmarket, en su propia web (Shopify o WooCommerce), por
mensaje. Hoy la app solo sabe cobrar en el mostrador. Esta fase añade **pedidos por enviar** y el
**enlace con tiendas online**, gratis y sin planes, con el diseño del repo.

Éxito: un pedido entra (a mano, por fichero o desde la tienda enlazada), reserva el stock, se
prepara con una lista de recogida, se envía con su número de seguimiento y, si se anula, el stock
vuelve. El stock de la tienda enlazada sigue al de la app.

## Límites honestos

- **Cardmarket y TCGplayer**: sus API no admiten altas nuevas. Entran por fichero (CSV de pedidos) y
  salen por fichero (la exportación de la Fase 1b). No hay enlace en vivo y la app lo dice.
- **Shopify y WooCommerce**: enlace en vivo con las credenciales de la propia tienda. Se prueba con
  HTTP simulado; nadie lo ha probado contra una tienda real y la pantalla lo avisa («beta»).
- **Etiquetas de transportista**: no se compran etiquetas. Se guarda transportista y seguimiento, y
  se imprime albarán con dirección.
- eBay queda fuera (OAuth de aplicación propia); entra por el CSV genérico.

## 3a — Pedidos y envíos

**Pedido** (`Order`, en `<cuenta>/shop/orders.json`): número `P00001`, canal (`manual`,
`cardmarket`, `tcgplayer`, `ebay`, `shopify`, `woocommerce`, `otro`), referencia externa, cliente
(nombre, email, dirección), líneas `SaleLine`, envío (método, transportista, coste, seguimiento),
total, moneda, nota y estado.

Estados: `new` (pendiente de pago) → `paid` → `packed` → `shipped` → `delivered`; `cancelled` desde
`new`/`paid`/`packed`; `returned` desde `shipped`/`delivered`.

Reglas:
- Crear un pedido **quita el stock** de sus líneas de stock (todo o nada, `OutOfStock`). Si guardar
  falla, el stock vuelve.
- Anular devuelve el stock. Devolución (`returned`) lo devuelve solo si se pide («ha vuelto a la tienda»).
- Un pedido con la misma (canal, referencia externa) no entra dos veces.
- Enviar exige transportista; el seguimiento es opcional. El enlace de seguimiento sale de la plantilla
  del método (`{code}`), solo `https://`.
- Líneas que no se pudieron enlazar a un montón quedan como líneas `custom` marcadas `unlinked`: no
  mueven stock y el pedido avisa «N sin enlazar».
- Los pedidos no son ventas del mostrador: tienen su propio libro. Los informes (Fase 4) leerán ambos.

**Métodos de envío** (`<cuenta>/shop/shipping.json`): nombre, transportista, precio, plantilla de
seguimiento. Vienen unos por defecto (Correos, SEUR, MRW, GLS, DHL, UPS, Royal Mail) editables.

**Lista de recogida**: de los pedidos `paid`, las cartas agrupadas por montón y ordenadas por
ubicación → colección → nombre, con cuántas copias y para qué pedidos.

**Albarán**: página imprimible `/pedidos/{id}/albaran` con tienda, dirección, líneas y total.

**Importar pedidos por fichero**: CSV de pedidos (`;` o `,`). Dos formas: una fila por artículo, o
la de Cardmarket (una fila por pedido con `Description` = `1x Nombre (Set) - núm - rareza - estado -
idioma - precio | …`). Cada artículo se enlaza a un montón por nombre + set (+ estado + idioma si
vienen); sin candidato o sin copias suficientes → sin enlazar. Vista previa antes de crear.

**Pantalla `/pedidos`** (modo tienda): pestañas por estado, buscador, pedido nuevo (buscador de
stock como el mostrador + artículo libre + cliente + dirección + envío), detalle con acciones
(cobrado, preparado, enviar, entregado, anular, devolución), lista de recogida, importar.

## 3b — Tiendas enlazadas

**SKU de montón**: `OY-` + 12 hex de SHA-1 de `line_key`. Estable mientras el montón no cambie de
colección, estado, idioma, edición o ubicación.

**Exportar catálogo**: CSV de productos para Shopify y para WooCommerce con SKU, título, precio y
cantidad, para crear los productos en la tienda una vez.

**Conexión** (`<cuenta>/shop/channels.json`, secretos sellados con `secret_box`):
- Shopify: dominio `*.myshopify.com` + token de Admin API de una app propia. GraphQL Admin.
- WooCommerce: URL `https://` de la tienda + clave y secreto REST. La URL se resuelve y se rechaza
  si apunta a una red privada, de bucle local o de enlace local; no se siguen redirecciones.

**Sincronizar** (botón, y al entrar en `/pedidos` no más de una vez cada 10 minutos por canal):
1. Trae pedidos pagados y sin enviar; cada línea se enlaza por SKU; entran como pedidos `paid`.
2. Empuja la cantidad de cada montón a la variante con su SKU. Los SKU que la tienda no tiene se
   cuentan («37 montones sin producto en la tienda») y no son error.
Al enviar un pedido de un canal enlazado **no** se marca como enviado en la tienda (se dice en
pantalla); es una mejora posterior.

Los secretos nunca salen en registros, avisos ni HTML: solo los cuatro últimos caracteres.

## Errores

Mensajes en español para la persona (`OrderError`, `ChannelError`, `spoken = True`); lo demás se
registra por tipo y se muestra un texto genérico. Un fichero dañado no se sobrescribe.

## Pruebas

Unitarias con directorio temporal; HTTP simulado para los conectores; humo con Playwright en
producción para `/pedidos` (crear, cobrar, enviar, anular y ver el stock).
