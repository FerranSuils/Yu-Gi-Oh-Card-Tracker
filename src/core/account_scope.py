"""Resolve which account is handling the current request.

The primary account keeps the original data directory. Every registered
account gets its own folder so one person cannot read another's collection.
"""

from __future__ import annotations

import os
import re

SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def current_account_name() -> str | None:
    try:
        from nicegui import app

        name = app.storage.user.get("auth_user")
    except Exception:
        return None
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
        return None
    return name


def uses_private_storage(name: str | None) -> bool:
    if not name:
        return False
    try:
        from src.services.auth_service import auth_service

        primary = auth_service.config_manager.get_auth_username()
    except Exception:
        return False
    return name.casefold() != str(primary).casefold()


def user_data_root(name: str) -> str:
    return os.path.join("data", "users", name)
