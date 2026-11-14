# Paridad con SortSwift: comparación función por función

Fecha: 2026-11-14 · Fuente: sortswift.com (inicio, /features, /pricing, /features/scanning), consultada el 2026-11-14.
Regla del proyecto: todo gratis, con el diseño de OpenYuGi. «Pago» = de pago en SortSwift.

| Función de SortSwift | Plan en SortSwift | Estado en OpenYuGi | Nota |
| --- | --- | --- | --- |
| Inventario y sincronización | Gratis hasta 5 000 | Hecho (las colecciones son el inventario) | Sin tope de artículos |
| Escaneo estándar (87 TCG) | Gratis | Hecho para Yu-Gi-Oh; Magic y Pokémon por catálogo | Cobertura de juegos menor |
| Subida de archivos / PDF de escáner | Gratis | Hecho (Fase 1b) | |
| Modos de escaneo: página de carpeta, captura automática, «Slinger» | No indicado | **Falta** | Hay captura manual y subida |
| Escaneo de alta precisión (foil, edición) | Pago | Parcial: detecta foil y 1.ª edición | |
| Autoprecio por reglas, con simulación | Gratis básico | Hecho (Fase 1a) | |
| CSV Suite (editar, reprecio, fusionar, exportar) | Gratis | Hecho (Fase 1b) | Un solo CSV, compatible con Cardmarket (decisión del usuario) |
| TPV | Pago | Hecho (Fase 2a), Stripe por tienda | |
| Buylist | Pago | Hecho (Fase 2b) | |
| Consigna | Pago | Hecho (Fase 2b) | |
| Kiosko de cliente | Pago | Hecho (Fase 2b) | |
| Pedidos y envíos | No indicado | Hecho (Fase 3), sin compra de etiquetas | Las etiquetas con descuento son un servicio de transportista |
| Sincronización con tiendas | Pago | Shopify y WooCommerce (beta); Cardmarket/TCGplayer por fichero | Sin eBay, CardTrader, ManaPool, CardNexus, Square, Misprint ni Walmart |
| Informes avanzados | Pago | Hecho (Fase 4) | |
| Eventos | Pago | Hecho (Fase 4), suizo sin eliminatorias | |
| API de inventario | Pago | Hecho (Fase 4), solo lectura | |
| Mapa de tiendas | No indicado | Hecho (Fase 4) | |
| Mazos de la comunidad enlazados al inventario | No indicado | Parcial: lista pegada contra el stock (`/lista`) | Sin catálogo de mazos |
| App móvil | Gratis | Parcial: PWA instalable | |
| Cuentas de personal | No indicado | **Falta** | |
| Gestión de almacén (beta) | Pago | Hecho: ubicaciones y cajas, y hoja de recogida de pedidos ordenada por ubicación (Fase 3) | |
| Hardware (Super Sorter, Simple Sifter) | Pago | No aplica | |

## Pendiente de construir (por orden)

1. Modos de escaneo: captura automática y modo continuo.
2. Cuentas de personal con permisos.

## Fuera, con motivo

- Hardware: no es software.
- Etiquetas de envío con descuento y cartera prepago: las vende el transportista, no una función de la app.
- Conectores de eBay, CardTrader, ManaPool, CardNexus, Square, Misprint y Walmart: cada uno exige credenciales de aplicación propia y no se pueden probar sin cuenta real. Entran por el CSV.
- Escaneo de alta precisión: requiere otro modelo de reconocimiento, no un ajuste.
