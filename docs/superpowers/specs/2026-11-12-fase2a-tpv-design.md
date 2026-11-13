# Fase 2a — Mostrador (TPV) y ventas

Fecha: 2026-11-12. Parte de la paridad con SortSwift (todo gratis). La Fase 2 se divide en
**2a** mostrador + ventas + Stripe por tienda (este documento) y **2b** buylist, kiosko y consigna.

## Decisión de negocio

«Cada tienda conecta su propio Stripe.» El dinero va directo a la cuenta de Stripe de la tienda.
Nordic Byte no cobra, no retiene ni ve fondos, y no hay comisión.

## Qué hace

Solo para cuentas con **Modo tienda** activo. Dos páginas nuevas y una tarjeta en Ajustes.

### `/tpv` — Mostrador
- Busca en el inventario de la cuenta (todas las colecciones de todos los juegos activos) por
  nombre, código de set o número. Cada resultado es una pila física: carta, set, rareza/acabado,
  estado, idioma, 1.ª edición, ubicación, cantidad y precio de venta (`list_price`).
- Añadir al ticket; en el ticket se cambia cantidad (nunca más que el stock) y precio unitario.
  Una línea sin precio (0) impide cobrar hasta que se escriba uno.
- Línea libre («Artículo sin inventario»: fundas, sobres…) con nombre y precio.
- Descuento del ticket: porcentaje o importe. El total nunca baja de 0.
- Cobro:
  - **Efectivo**: importe entregado y cambio.
  - **Tarjeta (datáfono propio)**: se anota como cobrado; la app no toca el datáfono.
  - **Stripe**: se crea una Checkout Session en la cuenta de Stripe de la tienda y se muestra un
    QR + enlace para que el cliente pague con su móvil. La página consulta el estado; al pagarse,
    la venta se cierra sola. Se puede cancelar (la sesión caduca y el stock vuelve).
- Al cobrar: se descuenta el stock de las colecciones, se guarda la venta y se muestra el
  ticket imprimible (nombre y dirección de la tienda, líneas, descuento, total, método, número).

### `/ventas` — Ventas
- Lista por día (más reciente primero) con total del día y por método de cobro.
- Detalle y ticket de cada venta. **Devolver**: devuelve el stock a su colección y marca la venta
  como devuelta; si fue por Stripe, emite el reembolso en Stripe.
- Exportar a CSV el mes.

### Ajustes → Cobros con Stripe
- La tienda pega una **clave restringida** (`rk_…`) o secreta (`sk_…`) de su cuenta. Se comprueba
  contra Stripe antes de guardarla. Nunca se vuelve a mostrar (solo los 4 últimos caracteres y si es
  de pruebas). Botón para desconectar.
- Se explica qué permisos necesita la clave restringida: Checkout Sessions (escritura) y
  Reembolsos (escritura).

## Reglas

- Stock: una venta nunca deja una pila en negativo. Si entre añadir al ticket y cobrar el stock ha
  bajado, el cobro se rechaza diciendo qué línea falla y no se descuenta nada (todo o nada).
- Stripe: el stock se reserva al crear el cobro (venta `pending`); se libera al cancelar o caducar.
  Una venta `pending` de Stripe que se encuentre pagada al abrir `/ventas` se cierra.
- Importes en céntimos (enteros) para no arrastrar errores de coma flotante. Monedas: la de la
  tienda (EUR, USD, GBP). Stripe exige un mínimo de 0,50.
- Numeración correlativa por cuenta (`000001`…), sin huecos por ventas canceladas de Stripe
  (el número se asigna al cobrar).
- Datos por cuenta: `<cuenta>/sales/AAAA-MM.json`, `<cuenta>/sales/counter.json`,
  `<cuenta>/stripe.json`. Ninguna cuenta ve ventas ni clave de otra.
- La clave de Stripe se guarda cifrada con DPAPI de Windows (ligada al usuario del servicio); en
  otros sistemas, en un fichero con permisos 600. Nunca aparece en logs ni en avisos.
- Los errores de Stripe se muestran con el mensaje de Stripe, sin clave ni rutas.
- Solo `CollectionEditor` / `GameCollectionEditor` tocan las colecciones.

## Fuera de alcance (se dice en la interfaz o en el informe)

- Stripe Terminal (lector físico de Stripe): requiere hardware y SDK; se usa QR/enlace.
- Stripe Connect con alta por OAuth: necesita una cuenta de plataforma de Nordic Byte; con clave
  propia el resultado para la tienda es el mismo y Nordic Byte no interviene.
- Impuestos/IVA desglosado, caja (arqueo), clientes y crédito de tienda: Fase 2b/4.
- Webhooks: el estado se consulta desde la página (sin secreto de webhook por tienda).
