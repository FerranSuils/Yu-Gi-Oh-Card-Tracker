from nicegui import app, ui

from src.core.persistence import persistence
from src.services.auth_service import AUTH_REVISION_KEY, AUTH_SESSION_KEY, AUTH_USER_KEY
from src.ui.theme import apply_theme

# Routes the shell must keep reachable. Labels follow the desk, not the old drawer.
NAV_ITEMS = [
    ('Resumen', '/'),
    ('Colección', '/collection'),
    ('Almacén', '/storage'),
    ('Sets', '/sets'),
    ('Mazos', '/decks'),
    ('Entrada', '/bulk_add'),
    ('Escanear', '/scan'),
    ('Importar', '/import'),
    ('Base de cartas', '/db_editor'),
]

PRIMARY_ROUTES = ['/collection', '/storage', '/decks', '/sets', '/bulk_add', '/scan']
PHONE_ROUTES = ['/collection', '/scan', '/decks', '/storage']


def _display_name(filename: str) -> str:
    for suffix in ('.json', '.yaml', '.yml'):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def create_layout(content_function):
    """Top bar and mode row. The drawer is gone; every route stays one click away."""
    apply_theme()

    try:
        current_path = ui.context.client.page.path
    except (AttributeError, RuntimeError):
        current_path = ''

    def logout() -> None:
        app.storage.user.pop(AUTH_SESSION_KEY, None)
        app.storage.user.pop(AUTH_REVISION_KEY, None)
        ui.navigate.to('/login')

    def go(target: str):
        ui.navigate.to(target)

    nav_by_route = dict((route, label) for label, route in NAV_ITEMS)
    try:
        saved = persistence.load_ui_state()
        collections = persistence.list_collections()
    except Exception:
        saved = {}
        collections = []
    selected = saved.get('collection_selected_file')
    if selected not in collections:
        selected = collections[0] if collections else None

    def select_collection(filename: str) -> None:
        persistence.save_ui_state({'collection_selected_file': filename})
        ui.navigate.to(current_path or '/collection')

    def submit_search() -> None:
        persistence.save_ui_state({'collection_search_text': search.value or ''})
        if current_path == '/collection':
            ui.navigate.reload()
        else:
            ui.navigate.to('/collection')

    with ui.column().classes('w-full gap-0'):
        with ui.row().classes('oy-topbar w-full items-center gap-4 px-4 lg:px-6 py-2 no-wrap'):
            with ui.row().classes('oy-brand').on('click', lambda: go('/collection')):
                ui.image('/brand/mark.svg').classes('oy-mark')
                ui.label('OpenYuGi').classes('oy-wordmark')

            with ui.row().classes('items-center gap-4 oy-desktop-only'):
                for filename in collections[:4]:
                    active = filename == selected
                    ui.label(_display_name(filename)).classes(
                        'oy-collection-tab' + (' active' if active else '')
                    ).on('click', lambda filename=filename: select_collection(filename))

            search = ui.input(placeholder='Nombre, código o passcode').props(
                'dense borderless'
            ).classes('oy-search flex-grow max-w-md')
            search.on('keydown.enter', submit_search)

            ui.space()
            signed_in_as = ''
            try:
                signed_in_as = str(app.storage.user.get(AUTH_USER_KEY) or '')
            except Exception:
                signed_in_as = ''
            if signed_in_as:
                ui.label(signed_in_as).classes('oy-mono text-xs text-gray-600')
            with ui.button('Más', icon='expand_more').props('flat dense no-caps color=primary'):
                with ui.menu():
                    for route in ('/', '/import', '/db_editor', '/settings'):
                        label = 'Ajustes' if route == '/settings' else nav_by_route.get(route, route)
                        ui.menu_item(label, on_click=lambda route=route: go(route))
                    ui.separator()
                    ui.menu_item('Salir', on_click=logout)

        with ui.row().classes('oy-modebar w-full items-center gap-6 px-4 lg:px-6 flex-wrap oy-desktop-only'):
            for route in PRIMARY_ROUTES:
                ui.label(nav_by_route[route]).classes(
                    'oy-mode' + (' active' if current_path == route else '')
                ).on('click', lambda route=route: go(route))

        with ui.column().classes('oy-page w-full items-start px-4 py-4 lg:px-6'):
            content_function()

    with ui.row().classes('oy-phone-nav w-full items-center justify-around py-3'):
        for route in PHONE_ROUTES:
            ui.label(nav_by_route[route]).classes(
                'oy-mode' + (' active' if current_path == route else '')
            ).on('click', lambda route=route: go(route))
