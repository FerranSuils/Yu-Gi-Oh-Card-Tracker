from pathlib import Path

from src.ui import auth


def test_login_button_does_not_use_the_signup_request():
    # The signup handler posts to /api/v1/register. When the login button shared
    # it, "Entrar al mostrador" tried to create the account instead of signing in.
    assert '/api/v1/register' not in auth._LOGIN_FIELDS_JS
    assert 'emit(' in auth._LOGIN_FIELDS_JS


def test_login_page_wires_the_login_handler():
    source = Path('src/ui/auth.py').read_text(encoding='utf-8')
    assert "submit.on('click', login, js_handler=_LOGIN_FIELDS_JS)" in source
