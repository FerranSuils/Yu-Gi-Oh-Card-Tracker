from urllib.parse import quote

from nicegui import app
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from src.services.auth_service import AUTH_REVISION_KEY, AUTH_SESSION_KEY, AUTH_USER_KEY, auth_service


PUBLIC_PATHS = {'/login', '/registro', '/login/callback', '/_nicegui_ws'}
PUBLIC_PREFIXES = ('/_nicegui/', '/.well-known/', '/fonts/', '/brand/')


def is_public_path(path: str) -> bool:
    """Allow login, framework assets, and well-known URIs before authentication."""
    return path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Protect UI pages, API endpoints, debug files, and application static data."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if is_public_path(request.url.path):
            return await call_next(request)

        session = app.storage.user
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
            return await call_next(request)

        if request.url.path.startswith('/api/'):
            return JSONResponse({'detail': 'Not authenticated'}, status_code=401)

        next_path = request.url.path
        if request.url.query:
            next_path += f'?{request.url.query}'
        return RedirectResponse(f'/login?next={quote(next_path, safe="")}', status_code=303)
