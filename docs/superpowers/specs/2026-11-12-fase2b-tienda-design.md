# Fase 2b — Clientes, compras (buylist), consigna y kiosko

Aprobación: el usuario pidió seguir de forma autónoma («sigue con el plan automaticamente y autonomo»).
Todo gratis, todo dentro del modo tienda. Sin base de datos: ficheros JSON por cuenta en `<cuenta>/shop/`.

## Qué hace

1. **Clientes** (`/clientes`). Ficha mínima (nombre, email, teléfono, nota) y dos saldos que salen de un
   libro de apuntes que solo crece (`ledger.json`): **saldo de tienda** (`credit`) y **consigna por liquidar**
   (`consignment`). Un saldo nunca se edita: se apunta un movimiento con motivo. El saldo de tienda no puede
   quedar negativo. Un cliente con saldo no se puede borrar.
2. **Saldo de tienda en el mostrador**. Nueva forma de cobro «Saldo» en `/tpv`: se elige el cliente, se
   descuenta el total de su saldo; la devolución lo repone.
3. **Compras** (`/compras`). La tienda compra cartas a un cliente. Se busca en el catálogo (cualquier juego
   activo), se elige impresión, acabado, estado, idioma y cantidad. La oferta sugerida es
   `precio de mercado × % de la forma de pago × % del estado`, editable. Se paga en **efectivo** o en **saldo
   de tienda** (porcentajes distintos). Al confirmar: las cartas entran en la colección elegida (con el precio
   de mercado como precio de venta si la pila es nueva), se guarda la compra numerada y, si es a saldo, se
   apunta al cliente. Una compra se puede **anular** mientras las cartas sigan en stock y el saldo sin gastar.
   Reglas en Ajustes → «Compras»: % efectivo (50), % saldo (65), % por estado (los de precios), oferta mínima.
4. **Consigna** (`/consigna`). Una consigna es **una colección asignada a un cliente con una comisión**. Las
   cartas se meten con las herramientas de siempre (escáner, entrada, CSV). Cuando el mostrador cobra una línea
   de esa colección, se apunta al cliente `parte de la línea en el total − comisión`; la devolución lo
   revierte con los mismos importes. «Liquidar» paga lo pendiente en efectivo o lo pasa a saldo de tienda.
   Cerrar la consigna la desvincula (la colección queda como normal).
5. **Kiosko** (`/kiosko/<token>`, sin sesión). Página pública de la tienda, activada en Ajustes con un enlace
   secreto que se puede regenerar. Pestaña «Comprar»: buscar el stock con precio, añadir a «Mi lista» y
   enviarla al mostrador con un nombre; devuelve un código de 4 cifras. Pestaña «Vender» (si hay precios):
   cuánto paga la tienda por una carta. En `/tpv`, «Pedidos del kiosko» carga una lista en el ticket.
   No se cobra en el kiosko: se paga en el mostrador.

## Límites honestos

- El kiosko no reserva stock: al cargar la lista, el ticket se ajusta a lo que quede.
- Las ofertas usan los precios ya descargados; el kiosko nunca dispara descargas.
- Yu-Gi-Oh en Cardmarket solo tiene precio por carta (no por impresión): la oferta lo avisa.
- Sin identificación legal del vendedor ni registro policial de compras: la tienda responde de eso.

## Seguridad

- El kiosko solo lee: nombre de la tienda, stock con precio > 0 y ofertas. Nunca clientes, saldos ni ventas.
- Token de 128 bits guardado en `<cuenta>/shop/kiosk.json`; mapa token → cuenta en memoria, con reescaneo limitado (1 cada 5 s). Regenerar invalida el anterior.
- Pedidos: máx. 30 abiertos por tienda, 60 líneas, nombre 40 caracteres, caducan a las 24 h, 3 por visita.
- Dinero en céntimos enteros. Todo cambio de stock pasa por los editores de colección.
- Las operaciones de saldo + stock + venta van bajo el candado de ventas de la cuenta.
