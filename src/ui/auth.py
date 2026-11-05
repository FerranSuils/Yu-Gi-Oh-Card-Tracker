import asyncio
import base64
import hashlib
import hmac
import logging
import time
import uuid
from urllib.parse import urlencode

from nicegui import app, run, ui

from src.services.auth_service import (
    AUTH_REVISION_KEY,
    AUTH_SESSION_KEY,
    AUTH_USER_KEY,
    auth_service,
    get_storage_secret,
)
from src.ui.theme import apply_theme

TEMP_AUTH_TOKEN_KEY = 'temp_auth_token'
TEMP_AUTH_TOKEN_EXPIRY_KEY = 'temp_auth_token_expiry'
PENDING_USER_KEY = 'pending_auth_user'
TEMP_AUTH_TOKEN_TTL_SECONDS = 60
_USED_SIGNUP_TOKENS: set[str] = set()

# Read the live input values at click time. NiceGUI's Python value can lag
# behind the last keystroke when a test or a fast user submits immediately.
_FIELD_VALUES_JS = '''(e) => {
  if (e && e.preventDefault) e.preventDefault();
  const form = (e && e.target && e.target.closest) ? (e.target.closest('form') || e.target) : document;
  const values = [...form.querySelectorAll('input')].map((input) => input.value);
  const error = form.querySelector('.oy-form-error');
  if (error && values.length >= 3 && values[1] !== values[2]) {
    error.textContent = 'Las contraseñas no coinciden.';
    return;
  }
  if (error) error.textContent = 'Enviando…';
  fetch('/api/v1/register', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({username: values[0] || '', password: values[1] || '', confirm: values[2] || ''}),
  }).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (error) error.textContent = data.detail || 'No se ha podido crear la cuenta.';
      return;
    }
    window.location.assign(data.next);
  }).catch(() => {
    if (error) error.textContent = 'No se ha podido crear la cuenta.';
  });
}'''


def _typed_pair(event, fallback_user, fallback_password):
    typed = list(getattr(event, 'args', None) or [])
    user = typed[0] if len(typed) > 0 and typed[0] is not None else fallback_user
    password = typed[1] if len(typed) > 1 and typed[1] is not None else fallback_password
    return user, password

logger = logging.getLogger(__name__)


def issue_signup_token(username: str) -> str:
    """Sign a short-lived login so the callback does not depend on the previous session."""
    expires_at = int(time.time()) + TEMP_AUTH_TOKEN_TTL_SECONDS
    payload = f'{username}\n{expires_at}'.encode()
    signature = hmac.new(get_storage_secret().encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + b'\n' + signature).decode()


def consume_signup_token(token: str) -> str | None:
    if token in _USED_SIGNUP_TOKENS:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        payload, signature = raw.rsplit(b'\n', 1)
        expected = hmac.new(get_storage_secret().encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        username, expires_at = payload.decode().split('\n', 1)
        if time.time() > int(expires_at):
            return None
    except Exception:
        return None
    _USED_SIGNUP_TOKENS.add(token)
    return username


def session_is_authenticated() -> bool:
    stored = app.storage.user
    username = stored.get(AUTH_USER_KEY)
    expected = (
        auth_service.revision_for(username)
        if isinstance(username, str) and username
        else auth_service.revision()
    )
    return bool(stored.get(AUTH_SESSION_KEY) and stored.get(AUTH_REVISION_KEY) == expected)


def _safe_next_path(next_path: str | None) -> str:
    """Return a local navigation target, falling back to the dashboard."""
    if not isinstance(next_path, str):
        return '/'

    # Browsers ignore these characters while resolving URLs. Remove them before
    # checking for protocol-relative paths so '/\t\\example.com' cannot become
    # '//example.com' in the browser.
    cleaned = ''.join(character for character in next_path if character not in '\t\r\n')
    if (
        cleaned.startswith('/')
        and not cleaned.startswith('//')
        and '\\' not in cleaned
    ):
        return cleaned
    return '/'


async def complete_login_callback(token: str | None, next_path: str | None) -> str | None:
    """Rotate the browser session after a login and return its safe destination.

    This runs from the callback page's HTTP request, where NiceGUI can still
    write the browser cookie. It must not be called from a WebSocket handler.
    """
    storage = app.storage
    old_user_storage = storage.user
    signed_user = consume_signup_token(token) if isinstance(token, str) else None
    if signed_user:
        # Keep this browser session. Rotating it on a redirect drops the new cookie.
        old_user_storage[AUTH_SESSION_KEY] = True
        old_user_storage[AUTH_USER_KEY] = signed_user
        old_user_storage[AUTH_REVISION_KEY] = auth_service.revision_for(signed_user)
        from nicegui.storage import request_contextvar
        request = request_contextvar.get()
        if request is not None:
            request.session['oy_user'] = signed_user
            request.session['oy_rev'] = old_user_storage[AUTH_REVISION_KEY]
        old_user_storage.pop(TEMP_AUTH_TOKEN_KEY, None)
        old_user_storage.pop(TEMP_AUTH_TOKEN_EXPIRY_KEY, None)
        old_user_storage.pop(PENDING_USER_KEY, None)
        return _safe_next_path(next_path)
    expected_token = old_user_storage.get(TEMP_AUTH_TOKEN_KEY)
    expires_at = old_user_storage.get(TEMP_AUTH_TOKEN_EXPIRY_KEY)
    if not (
        isinstance(token, str)
        and isinstance(expected_token, str)
        and hmac.compare_digest(token, expected_token)
        and isinstance(expires_at, (int, float))
        and time.time() <= expires_at
    ):
        if isinstance(token, str) and expected_token is None:
            logger.warning('Rejected replayed or consumed login callback token.')
        elif isinstance(expires_at, (int, float)) and time.time() > expires_at:
            logger.warning('Rejected expired login callback token.')
            old_user_storage.pop(TEMP_AUTH_TOKEN_KEY, None)
            old_user_storage.pop(TEMP_AUTH_TOKEN_EXPIRY_KEY, None)
        return None

    # Consume the token before the first await so a callback URL is single-use.
    old_user_storage.pop(TEMP_AUTH_TOKEN_KEY, None)
    old_user_storage.pop(TEMP_AUTH_TOKEN_EXPIRY_KEY, None)
    old_session_id = storage.browser.get('id')
    session_id = str(uuid.uuid4())
    storage.browser['id'] = session_id
    await storage._create_user_storage(session_id)  # pylint: disable=protected-access
    username = old_user_storage.get(PENDING_USER_KEY)
    if not isinstance(username, str) or not username:
        username = auth_service.config_manager.get_auth_username()
    storage.user[AUTH_SESSION_KEY] = True
    storage.user[AUTH_USER_KEY] = username
    storage.user[AUTH_REVISION_KEY] = auth_service.revision_for(username)

    # NiceGUI retains per-user storage by session ID. Clear its persistent data
    # and remove the old in-memory entry once the replacement session is ready.
    old_user_storage.clear()
    users = getattr(storage, '_users', None)
    if isinstance(users, dict) and old_session_id is not None:
        users.pop(old_session_id, None)
    return _safe_next_path(next_path)


def login_page(next_path: str | None = None) -> None:
    """Render the only page available without an authenticated session."""
    apply_theme()
    destination = _safe_next_path(next_path)
    if session_is_authenticated():
        ui.navigate.to(destination)
        return

    async def login(event=None) -> None:
        typed_user, typed_password = _typed_pair(event, username.value, password.value)
        submit.props('loading disable')
        try:
            account = await run.io_bound(auth_service.identify, typed_user, typed_password)
            if account:
                token = str(uuid.uuid4())
                app.storage.user[PENDING_USER_KEY] = account
                app.storage.user[TEMP_AUTH_TOKEN_KEY] = token
                app.storage.user[TEMP_AUTH_TOKEN_EXPIRY_KEY] = time.time() + TEMP_AUTH_TOKEN_TTL_SECONDS
                callback_query = urlencode({'token': token, 'next': destination})
                ui.navigate.to(f'/login/callback?{callback_query}')
                return

            # A fixed delay makes online guessing slower without blocking NiceGUI's event loop.
            await asyncio.sleep(1)
            password.set_value('')
            form_error.set_text('Usuario o contraseña incorrectos.')
        finally:
            submit.props(remove='loading disable')

    with ui.column().classes('w-full gap-0'):
        with ui.row().classes('w-full items-center justify-between px-6 py-5'):
            with ui.row().classes('oy-brand').on('click', lambda: ui.navigate.to('/login')):
                ui.image('/brand/mark.svg').classes('oy-mark')
                ui.label('OpenYuGi').classes('oy-logo')
            ui.label('gratis').classes('oy-mono text-xs text-gray-500')
        ui.separator()

        with ui.row().classes('w-full items-start gap-12 px-6 lg:px-16 py-16'):
            with ui.column().classes('gap-4 max-w-xl'):
                ui.label('COLECCIÓN FÍSICA').classes('oy-mono text-xs oy-text-accent tracking-widest')
                ui.label('Cada copia,\ncon su sitio.').classes('oy-h1 whitespace-pre-line').style('font-size: 56px; line-height: 1.05')
                ui.label(
                    'OpenYuGi es gratis. Creas una cuenta y catalogas las cartas que tienes: '
                    'set, rareza, idioma, estado, primera edición y el binder o la caja donde está cada copia.'
                ).classes('text-base text-gray-600 leading-relaxed')
            with ui.card().classes('w-full max-w-sm p-6 gap-3'):
                ui.label('Entrar').classes('oy-display text-2xl')
                ui.label('Gratis para todo el mundo.').classes('oy-sub')
                form_error = ui.label('').classes('oy-form-error')
                username = ui.input('Usuario', value='').props(
                    'outlined autocomplete=username autofocus'
                ).classes('w-full')
                password = ui.input('Contraseña', password=True, password_toggle_button=True).props(
                    'outlined autocomplete=current-password'
                ).classes('w-full')
                password.on('keydown.enter', login)
                submit = ui.button('Entrar al mostrador').props(
                    'color=secondary unelevated no-caps'
                ).classes('w-full q-mt-sm')
                submit.on('click', login, js_handler=_FIELD_VALUES_JS)
                ui.button('Crear cuenta', on_click=lambda: ui.navigate.to('/registro')).props(
                    'flat no-caps color=primary'
                ).classes('w-full')

        with ui.element('div').classes('w-full px-6 lg:px-16 pb-16 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-8'):
            for number, title, body in (
                ('01', 'Gratis', 'Una cuenta, tu colección, sin pago y sin límite de cartas.'),
                ('02', 'Dos maneras de mirar', 'Jugador agrupa impresiones. Coleccionista conserva set, arte y rareza.'),
                ('03', 'Escáner', 'La foto se usa para leer la carta. Tú confirmas antes de guardarla.'),
                ('04', 'Mazos honestos', 'El mazo se compara con lo que posees y con la banlist que elijas.'),
            ):
                with ui.column().classes('gap-1 max-w-xs'):
                    ui.label(number).classes('oy-mono text-xs oy-text-accent')
                    ui.label(title).classes('font-medium')
                    ui.label(body).classes('text-sm text-gray-600')


def register_page(next_path: str | None = None) -> None:
    """Public, free registration. Each account gets its own collection."""
    apply_theme()
    destination = _safe_next_path(next_path)
    if session_is_authenticated():
        ui.navigate.to(destination)
        return

    async def register(event=None) -> None:
        typed = list(getattr(event, 'args', None) or [])
        if len(typed) == 1 and isinstance(typed[0], (list, tuple)):
            typed = list(typed[0])
        typed_user = typed[0] if len(typed) > 0 and isinstance(typed[0], str) else username.value
        typed_password = typed[1] if len(typed) > 1 and isinstance(typed[1], str) else password.value
        typed_confirm = typed[2] if len(typed) > 2 and isinstance(typed[2], str) else confirm.value
        logger.info('Register attempt for %s', typed_user if isinstance(typed_user, str) else '')
        form_error.set_text('')
        submit.props('loading disable')
        try:
            account = await run.io_bound(
                auth_service.register,
                typed_user,
                typed_password,
                typed_confirm,
            )
            token = str(uuid.uuid4())
            app.storage.user[PENDING_USER_KEY] = account
            app.storage.user[TEMP_AUTH_TOKEN_KEY] = token
            app.storage.user[TEMP_AUTH_TOKEN_EXPIRY_KEY] = time.time() + TEMP_AUTH_TOKEN_TTL_SECONDS
            callback_query = urlencode({'token': token, 'next': destination if destination != '/' else '/collection'})
            ui.navigate.to(f'/login/callback?{callback_query}')
        except ValueError as error:
            form_error.set_text(str(error))
        finally:
            submit.props(remove='loading disable')

    with ui.column().classes('w-full gap-0'):
        with ui.row().classes('w-full items-center justify-between px-6 py-5'):
            with ui.row().classes('oy-brand').on('click', lambda: ui.navigate.to('/login')):
                ui.image('/brand/mark.svg').classes('oy-mark')
                ui.label('OpenYuGi').classes('oy-logo')
            ui.label('gratis').classes('oy-mono text-xs text-gray-500')
        ui.separator()
        with ui.row().classes('w-full justify-center px-6 py-16'):
            with ui.card().classes('oy-register w-full max-w-sm p-6 gap-3'):
                ui.label('Crear cuenta').classes('oy-display text-2xl')
                ui.label('Es gratis. Tu colección no la ve nadie más.').classes('oy-sub')
                with ui.element('form').classes('w-full column gap-3') as signup_form:
                    form_error = ui.label('').classes('oy-form-error')
                    username = ui.input('Usuario', value='').props(
                        'outlined autocomplete=username autofocus'
                    ).classes('w-full')
                    password = ui.input('Contraseña', password=True, password_toggle_button=True).props(
                        'outlined autocomplete=new-password'
                    ).classes('w-full')
                    confirm = ui.input('Repite la contraseña', password=True, password_toggle_button=True).props(
                        'outlined autocomplete=new-password'
                    ).classes('w-full')
                    submit = ui.button('Crear mi cuenta').props(
                        'type=submit color=secondary unelevated no-caps'
                    ).classes('w-full q-mt-sm')
                signup_form.on('submit', js_handler=_FIELD_VALUES_JS)
                ui.button('Ya tengo cuenta', on_click=lambda: ui.navigate.to('/login')).props(
                    'flat no-caps color=primary'
                ).classes('w-full')
