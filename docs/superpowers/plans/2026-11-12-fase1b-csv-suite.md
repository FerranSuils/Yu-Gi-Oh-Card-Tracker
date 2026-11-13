# Fase 1b — CSV Suite Implementation Plan

**Goal:** Página `/csv` con exportación universal compatible con Cardmarket, importación con mapeo, fusión y tabla editable.
**Architecture:** lógica pura en `src/services/csv_suite.py`; UI en `src/ui/csv_suite.py`; mutaciones solo por los editores.
**Tech Stack:** Python 3.12, csv estándar, Pydantic 2, NiceGUI 3.13.
**Spec:** `docs/superpowers/specs/2026-11-12-fase1b-csv-suite-design.md`

## Global Constraints
- Separador `;`, utf-8-sig. Sin dependencias nuevas. Iconos solo IconKit. Texto de interfaz en español.
- Disco siempre en `run.io_bound`; stores `.bound()` en el hilo de UI.

## Review Focus
- CSV con BOM, separador coma y decimales con coma.
- Fila ambigua (misma carta, varias impresiones, sin set) no debe importarse a ciegas.
- Importar dos veces suma, nunca reemplaza; cantidad negativa o no numérica se rechaza.
- Editar el estado hacia una pila ya existente debe sumar y conservar precio.
- Inyección de fórmulas en CSV (`=`, `+`, `-`, `@` al inicio de nombre/comentario) al abrir en Excel.

## Tasks (tests en `tests/test_csv_suite.py`, `tests/test_csv_page.py`)
1. **Export** — `export_rows(collection, game, lookup) -> list[dict]`, `to_csv(rows) -> bytes`, `EXPORT_COLUMNS`.
2. **Read + mapping** — `read_table(data) -> (headers, rows)`, `guess_mapping(headers) -> dict[field, header]`.
3. **Parse** — `ImportRow`, `parse_rows(rows, mapping) -> list[ImportRow]` (con `error` por fila).
4. **Match** — `CatalogIndex(cards)`, `match_rows(rows, index) -> list[MatchedRow]`.
5. **Apply** — `apply_import(collection, matched, api_card_for=None) -> int` para ambos tipos de colección.
6. **Merge** — `merge_collections(name, sources, game=None, api_card_for=None)`.
7. **Edit** — `edit_entry(collection, ref, quantity, condition, price) -> bool`.
8. **Página** — `csv_suite_page()`, ruta `/csv`, menú, iconos; prueba de humo de ruta/menú.
9. Suite completa, comprobación en navegador, despliegue.
