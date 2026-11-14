"""«Novedades»: próximos lanzamientos y cambios recientes, leídos del almacén local."""

from nicegui import run, ui

from src.services.reference import novedades, scheduler
from src.ui.theme import page_header


def _days_text(days: int) -> str:
    if days == 0:
        return 'Hoy'
    if days == 1:
        return 'Mañana'
    return f'En {days} días'


def novedades_page():
    content = ui.column().classes('w-full gap-6 p-4')

    async def render():
        view = await run.io_bound(novedades.build_view)
        content.clear()
        with content:
            with ui.row().classes('w-full items-end justify-between gap-4'):
                page_header('Novedades', 'Próximos lanzamientos y cambios recientes de sets.')
                with ui.row().classes('items-center gap-3'):
                    updated = view['last_update'].replace('T', ' ') if view['last_update'] else 'nunca'
                    ui.label(f'Última actualización: {updated}').classes('oy-sub')
                    ui.button('Actualizar ahora', on_click=refresh).props('flat dense no-caps color=primary')

            ui.label('Próximos lanzamientos').classes('text-h6')
            if not view['upcoming']:
                ui.label('No hay lanzamientos con fecha guardados todavía.').classes('oy-sub')
            for s in view['upcoming']:
                with ui.card().classes('w-full p-4'):
                    with ui.row().classes('w-full items-center justify-between no-wrap'):
                        with ui.column().classes('gap-0'):
                            ui.label(s['name']).classes('text-subtitle1')
                            extra = f" · {s['num_of_cards']} cartas" if s.get('num_of_cards') else ''
                            ui.label(f"{s['set_code']}{extra}").classes('oy-sub')
                        with ui.column().classes('gap-0 items-end'):
                            ui.label(s['date_label']).classes('text-subtitle1')
                            ui.label(_days_text(s['days_left'])).classes('oy-sub')

            ui.label('Novedades recientes (30 días)').classes('text-h6')
            if not view['recent']:
                ui.label('Sin cambios recientes.').classes('oy-sub')
            for r in view['recent']:
                ui.label(f"{r['at'][:10]} · {r['label']}: {r['name']} ({r['set_code']}) · {r['date_label']}")

            ui.label('Fuentes: YGOPRODeck (fechas de sets). cardcluster.es no se puede leer sin navegador: '
                     'exige JavaScript y un desafío anti-bot.').classes('oy-sub')

    async def refresh():
        ui.notify('Actualizando…')
        result = await run.io_bound(scheduler.refresh_all)
        errors = [f'{k}: {v["error"]}' for k, v in result.items() if 'error' in v]
        ui.notify('Actualizado' if not errors else 'Actualizado con avisos: ' + ' | '.join(errors),
                  type='positive' if not errors else 'warning', multi_line=True)
        await render()

    ui.timer(0.01, render, once=True)
