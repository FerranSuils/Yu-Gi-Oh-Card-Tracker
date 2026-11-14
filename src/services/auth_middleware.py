from urllib.parse import quote

from nicegui import app
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from src.core.account_scope import uses_private_storage
from src.services.auth_service import AUTH_REVISION_KEY, AUTH_SESSION_KEY, AUTH_USER_KEY, auth_service
from src.services.billing.guard import LOCKED_HOME, blocks
from src.services.billing.service import billing_service


PUBLIC_PATHS = {'/login', '/registro', '/login/callback', '/_nicegui_ws', '/api/v1/register', '/tpv/pagado', '/mapa', '/manifest.webmanifest', '/sw.js'}
PUBLIC_PREFIXES = ('/_nicegui/', '/.well-known/', '/fonts/', '/brand/', '/kiosko/', '/api/v1/shop/')


def is_public_path(path: str) -> bool:
    """Allow login, framework assets, and well-known URIs before authentication."""
    return path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Protect UI pages, API endpoints, debug files, and application static data."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if is_public_path(request.url.path):
            return await call_next(request)

        session = app.storage.user
        cookie_user = request.session.get('oy_user') if 'session' in request.scope else None
        cookie_rev = request.session.get('oy_rev') if 'session' in request.scope else None
        if (
            isinstance(cookie_user, str)
            and cookie_user
            and cookie_rev == auth_service.revision_for(cookie_user)
        ):
            session[AUTH_SESSION_KEY] = True
            session[AUTH_USER_KEY] = cookie_user
            session[AUTH_REVISION_KEY] = cookie_rev
        username = session.get(AUTH_USER_KEY)
        expected_revision = (
            auth_service.revision_for(username)
            if isinstance(username, str) and username
            else auth_service.revision()
        )
        authenticated = bool(
            session.get(AUTH_SESSION_KEY)
            and session.get(AUTH_REVISION_KEY) == expected_revision
        )
        if authenticated:
            if blocks(username, request.url.path, billing_service, operator=not uses_private_storage(username)):
                # Unpaid account (trial over, or the yearly 2 EUR past due): only the billing page opens.
                if request.url.path.startswith('/api/'):
                    return JSONResponse({'detail': 'Payment required'}, status_code=402)
                return RedirectResponse(LOCKED_HOME, status_code=303)
            return await call_next(request)

        if request.url.path.startswith('/api/'):
            return JSONResponse({'detail': 'Not authenticated'}, status_code=401)

        next_path = request.url.path
        if request.url.query:
            next_path += f'?{request.url.query}'
        return RedirectResponse(f'/login?next={quote(next_path, safe="")}', status_code=303)
