"""/mapa: the public map of shops that chose to appear. OpenStreetMap tiles on Leaflet, nothing else.

Nobody is signed in here: the page shows each shop's name and address, and a link to its kiosk if open.
"""

from __future__ import annotations

import html
import logging
from typing import List, Tuple

from nicegui import run, ui

from src.services.shop.shop_map import Pin, pins
from src.ui.icons import icon
from src.ui.shop_common import SHOP_CSS
from src.ui.theme import apply_theme

logger = logging.getLogger(__name__)

ICONS = ('map-pin', 'store', 'shopping-list')
TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
SPAIN = ((40.0, -3.7), 5)

# The dark map is the same tiles seen through a filter; no second tile provider.
_DARK_TILES = 'filter: invert(1) hue-rotate(180deg) brightness(.92) contrast(.9) saturate(.7);'
MAP_CSS = f"""
.oy-map {{ width: 100%; height: 62vh; min-height: 340px; border-radius: 12px; border: 1px solid var(--oy-border);
           overflow: hidden; z-index: 0; }}
html[data-oy-theme="dark"] .oy-map .leaflet-tile-pane {{ {_DARK_TILES} }}
@media (prefers-color-scheme: dark) {{
  html:not([data-oy-theme="light"]) .oy-map .leaflet-tile-pane {{ {_DARK_TILES} }}
}}
"""


def place_text(pin: Pin) -> str:
    return ', '.join(part for part in (pin.address, pin.city, pin.country) if part)


def popup_html(pin: Pin) -> str:
    """What a marker says. Every word a shop wrote is escaped: this is read by strangers."""
    parts = [f'<strong>{html.escape(pin.name)}</strong>', html.escape(place_text(pin))]
    if pin.kiosk:
        parts.append(f'<a href="/kiosko/{html.escape(pin.kiosk, quote=True)}">Ver el kiosko</a>')
    return '<br>'.join(part for part in parts if part)


def view(shown: List[Pin]) -> Tuple[Tuple[float, float], int]:
    """Centre and zoom that take in every pin."""
    if not shown:
        return SPAIN
    lats, lons = [pin.lat for pin in shown], [pin.lon for pin in shown]
    centre = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
    spread = max(max(lats) - min(lats), max(lons) - min(lons))
    for limit, zoom in ((0.02, 13), (0.2, 10), (1.5, 8), (5, 6), (12, 5), (40, 3)):
        if spread <= limit:
            return centre, zoom
    return centre, 2


def map_page() -> None:
    apply_theme()
    ui.add_css(SHOP_CSS)
    ui.add_css(MAP_CSS)
    with ui.column().classes('w-full items-center q-pa-md'):
        page = ui.column().classes('w-full gap-3').style('max-width: 1100px')
    with page:
        with ui.row().classes('w-full items-center gap-2'):
            icon('map-pin', 24)
            ui.label('Mapa de tiendas').classes('oy-h1')
        body = ui.column().classes('w-full gap-3')
        with body:
            ui.label('Cargando…').classes('text-caption text-grey-5')

    async def load() -> None:
        try:
            shown = await run.io_bound(pins)
        except Exception as error:
            logger.error('Mapa: no se pudieron leer las tiendas: %s', type(error).__name__)
            body.clear()
            with body:
                ui.label('No se pudo cargar el mapa. Inténtalo de nuevo.').classes('oy-sub')
            return
        centre, zoom = view(shown)
        body.clear()
        with body:
            chart = ui.leaflet(center=centre, zoom=zoom).classes('oy-map')
            chart.clear_layers()
            chart.tile_layer(url_template=TILES, options={'attribution': ATTRIBUTION, 'maxZoom': 19})
            markers = [(chart.marker(latlng=(pin.lat, pin.lon)), pin) for pin in shown]
            if not shown:
                ui.label('Todavía no hay ninguna tienda en el mapa.').classes('oy-sub')
            for pin in shown:
                with ui.card().classes('w-full q-pa-md'):
                    with ui.row().classes('w-full items-center gap-2 no-wrap'):
                        icon('store', 20)
                        with ui.column().classes('gap-0').style('flex: 1; min-width: 0'):
                            ui.label(pin.name).classes('text-subtitle1')
                            ui.label(place_text(pin)).classes('text-caption text-grey-5')
                        if pin.kiosk:
                            with ui.link(target=f'/kiosko/{pin.kiosk}').classes('row items-center gap-1 no-wrap'):
                                icon('shopping-list', 18)
                                ui.label('Ver el kiosko')
        try:
            await chart.initialized()
            for marker, pin in markers:
                marker.run_method('bindPopup', popup_html(pin))
        except Exception as error:   # the list under the map already says everything the popups would
            logger.warning('Mapa: sin globos en los marcadores: %s', type(error).__name__)

    ui.timer(0.1, load, once=True)
