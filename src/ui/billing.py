"""/facturacion: the plan of the account, the 10 € lifetime payment and the yearly 2 € upkeep invoice."""

from __future__ import annotations

from datetime import date

from nicegui import app, run, ui

from src.core.account_scope import current_account_name
from src.services.billing import plan
from src.services.billing.service import billing_service
from src.services.sales.stripe_gateway import StripeError
from src.ui.icons import icon as ik_icon

POLL_SECONDS = 5


def _euros(cents: int) -> str:
    return f'{cents / 100:.0f} €'


def billing_page(base_url: str) -> None:
    username = current_account_name() or ''
    service = billing_service

    @ui.refreshable
    def body() -> None:
        state = service.state(username) if username else plan.ACTIVE
        record = service.record(username) if username and service.enabled else None
        locked = state in plan.LOCKED
        with ui.card().classes('w-full max-w-xl mx-auto gap-3 p-6').props('id=billing-card'):
            ui.label('Tu plan').classes('text-xl font-bold')
            if state == plan.EXEMPT:
                ui.label('Plan de por vida gratuito. No tienes que pagar nada.').props('id=billing-status')
            elif state == plan.ACTIVE:
                ui.label('Plan de por vida activo: todo ilimitado.').props('id=billing-status')
                if not service.enabled:
                    ui.label('Los pagos todavía no están activados en este servidor.').classes('oy-text-faint text-sm')
            elif state == plan.TRIAL:
                left = plan.trial_days_left(record, date.today())
                ui.label(f'Prueba gratuita: te quedan {left} días.').props('id=billing-status')
            elif state == plan.LOCKED_TRIAL:
                ui.label('La prueba de 30 días ha terminado. Para seguir, paga el plan de por vida.') \
                    .classes('font-semibold').props('id=billing-status')
            else:
                ui.label('Tienes pendiente el mantenimiento anual del servidor. Págalo para seguir.') \
                    .classes('font-semibold').props('id=billing-status')

            if state in (plan.TRIAL, plan.LOCKED_TRIAL):
                ui.label(f'Pago único de {_euros(plan.LIFETIME_CENTS)}: plan de por vida, todo ilimitado. '
                         f'Después, {_euros(plan.ANNUAL_CENTS)} al año para mantener el servidor.') \
                    .classes('text-sm oy-text-body')
                with ui.button(on_click=pay).props('no-caps color=secondary id=billing-pay'):
                    ik_icon('credit-card')
                    ui.label(f'Pagar {_euros(plan.LIFETIME_CENTS)} (de por vida)').classes('q-ml-xs')
            if state == plan.LOCKED_ANNUAL:
                invoice = service.invoice_for(username)
                if invoice:
                    ui.label(f'Factura {invoice.year}: {_euros(plan.ANNUAL_CENTS)} · vencía el {invoice.due_on}') \
                        .classes('text-sm oy-text-body')
                    with ui.button(on_click=lambda: ui.navigate.to(invoice.url)).props(
                            'no-caps color=secondary id=billing-invoice'):
                        ik_icon('receipt')
                        ui.label(f'Pagar {_euros(plan.ANNUAL_CENTS)}').classes('q-ml-xs')
            if locked:
                ui.label('Cuando pagues, esta página se desbloquea sola en unos segundos.') \
                    .classes('text-xs oy-text-faint')
                ui.button('Ya he pagado', on_click=check).props('flat no-caps id=billing-check')

    async def pay() -> None:
        from src.ui.pos import success_url
        request = ui.context.client.request
        base = success_url(request.headers, request.base_url).removesuffix('/tpv/pagado')
        try:
            url = await run.io_bound(service.checkout, username, f'{base}/facturacion?pago=ok', f'{base}/facturacion')
        except StripeError as error:
            ui.notify(str(error), type='negative')
            return
        ui.navigate.to(url)

    async def check() -> None:
        before = service.state(username)
        after = await run.io_bound(service.refresh, username)
        if before in plan.LOCKED and after not in plan.LOCKED:
            ui.notify('Pago recibido. ¡Gracias!', type='positive')
            ui.navigate.to('/')
            return
        body.refresh()

    async def poll() -> None:
        if username and service.state(username) in plan.LOCKED:
            await check()

    body()
    if service.enabled and username and not plan.is_exempt(username):
        # Stripe tells us nothing by itself: ask now (a payment may have just been made) and while locked.
        ui.timer(POLL_SECONDS, poll)
        ui.timer(0.5, check, once=True)
