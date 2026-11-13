# Fase 1b — CSV Suite (diseño)

Fecha: 2026-11-12. Aprobación: el usuario pidió ejecución autónoma ("sigue con el plan automaticamente y autonomo").

## Objetivo
Una página `/csv` ("CSV") con cuatro herramientas para cualquier colección (Yu-Gi-Oh y el resto de juegos):

1. **Exportar** — un único CSV universal, compatible con Cardmarket, igual para todas las tiendas.
2. **Importar** — subir un CSV (el nuestro o el de otra herramienta), mapear columnas, casar cada fila con el
   catálogo y añadirla a una colección. Las filas sin casar se listan y se pueden descargar.
3. **Fusionar** — unir dos o más colecciones del mismo juego en una nueva.
4. **Editar** — tabla editable (cantidad, estado, precio de venta) de una colección.

Fuera de alcance: importación en bloque desde PDF (falta el PDF de ejemplo del usuario; se añade cuando llegue)
y subida automática a tiendas (Fase 3: depende de las API de cada marketplace).

## Formato universal
- Separador `;`, UTF-8 con BOM, decimales con punto, una fila por pila física (entrada).
- Columnas Cardmarket (mismo nombre y códigos que su exportación de stock), seguidas de columnas legibles:

`idProduct;groupCount;price;idLanguage;condition;isFoil;isSigned;isAltered;isPlayset;isFirstEd;comments;`
`name;expansion;expansionCode;number;rarity;language;storage;game;cardId;printingId`

- `idProduct`: id de Cardmarket si el catálogo lo conoce (hoy solo Magic); vacío si no.
- `groupCount`: cantidad. `price`: precio de venta de la entrada; vacío si no tiene.
- `idLanguage`: 1 EN, 2 FR, 3 DE, 4 ES, 5 IT, 6 ZH (simplificado), 7 JA, 8 PT, 9 RU, 10 KO, 11 ZH-TW.
- `condition`: MT, NM, EX, GD, LP, PL, PO (Mint…Poor; Damaged → PO).
- `isFoil`: 1 si el acabado no es `nonfoil`. `isSigned`, `isAltered`, `isPlayset`: siempre 0.
- `cardId` y `printingId` hacen que reimportar nuestro propio CSV sea exacto.

## Importación
- Lectura: detecta codificación (utf-8-sig, luego cp1252) y separador (`;`, `,`, tabulador).
- Mapeo automático por alias de cabecera (sin distinguir mayúsculas, espacios ni guiones), editable en pantalla.
  Solo es obligatorio poder identificar la carta: `printingId`, o `idProduct`, o código de set (+ número), o nombre.
- Valores tolerantes: cantidad vacía = 1; precio con coma o símbolo; estado por código o nombre (ES/EN);
  idioma por id, código o nombre; booleanos 1/true/yes/x/sí/foil.
- Casado, en este orden: `printingId` → `idProduct` → set+número (+rareza) → nombre+set → nombre (solo si
  la carta tiene una única impresión). Yu-Gi-Oh: `LOB-EN001`, `LOB-DE001` y `LOB-001` son el mismo set+número.
- Resultado por fila: `ok`, `sin casar` (motivo) o `ambigua` (varias impresiones; no se importa).
- Aplicar: solo filas `ok`, siempre sumando cantidad (nunca resta ni reemplaza) mediante `CollectionEditor` /
  `GameCollectionEditor`; si la fila trae precio, se fija como precio de venta. Destino: colección existente o nueva.
- Límite de subida: 5 MB y 20 000 filas.

## Fusionar
Nueva colección con la suma de las entradas de las elegidas (mismo juego). Conserva precio de venta y bloqueo de
la primera entrada que los tenga. No toca las colecciones de origen. El nombre no puede existir ya.

## Editar
Tabla con una fila por entrada: carta, set, estado, idioma, cantidad, precio. Editables cantidad (0 borra),
estado y precio (vacío quita el precio). Cambiar el estado mueve la pila; si ya hay otra igual, se suman.
Se guarda con un botón; todas las mutaciones pasan por los editores.

## Arquitectura
- `src/services/csv_suite.py`: funciones puras (sin NiceGUI ni disco) — exportar, leer, mapear, parsear, casar,
  aplicar, fusionar, editar.
- `src/ui/csv_suite.py`: página `/csv`; todo el disco en `run.io_bound`; guardados bajo `path_lock`.
- Navegación: entrada "CSV" en el menú, junto a "Importar". Iconos IconKit autoalojados.

## Errores
Fichero ilegible o sin cabecera → mensaje claro, no se importa nada. Colección que cambió en otra pestaña →
se recarga antes de aplicar (se carga, aplica y guarda dentro del mismo bloqueo).
