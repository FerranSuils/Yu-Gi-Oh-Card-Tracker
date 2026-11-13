"""IconKit outline icons, self-hosted in static/icons and inlined so they follow currentColor."""

from __future__ import annotations

import functools
import os
import re

from nicegui import ui

ICON_DIR = os.path.join('static', 'icons')


@functools.lru_cache(maxsize=None)
def icon_svg(name: str, size: int = 18) -> str:
    if not re.fullmatch(r'[a-z0-9-]+', name):
        raise ValueError(f'Bad icon name: {name!r}')
    with open(os.path.join(ICON_DIR, f'{name}.svg'), 'r', encoding='utf-8') as file:
        svg = file.read().strip()
    svg = re.sub(r'\swidth="\d+"', f' width="{size}"', svg, count=1)
    svg = re.sub(r'\sheight="\d+"', f' height="{size}"', svg, count=1)
    return svg.replace('<svg ', '<svg class="oy-ik" aria-hidden="true" ', 1)


def icon(name: str, size: int = 18) -> ui.html:
    return ui.html(icon_svg(name, size), sanitize=False).classes('inline-flex items-center')
