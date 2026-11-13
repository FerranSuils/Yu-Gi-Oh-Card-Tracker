"""Where an account keeps its own Stripe key: <cuenta>/stripe.json, sealed with secret_box."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from src.core import secret_box
from src.core.sales_models import now_iso

logger = logging.getLogger(__name__)


def _path(root: str) -> str:
    return os.path.join(root, 'stripe.json')


def _read(root: str) -> Optional[dict]:
    try:
        with open(_path(root), 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data if isinstance(data, dict) and data.get('key') else None
    except (OSError, ValueError):
        return None


def save_key(root: str, key: str) -> None:
    os.makedirs(root, exist_ok=True)
    data = {'key': secret_box.protect(key), 'last4': key[-4:], 'mode': 'live' if '_live_' in key else 'test',
            'kind': 'restringida' if key.startswith('rk_') else 'secreta', 'connected_at': now_iso()}
    temporary = _path(root) + '.tmp'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
        json.dump(data, file)
    os.replace(temporary, _path(root))


def load_key(root: str) -> Optional[str]:
    data = _read(root)
    if not data:
        return None
    try:
        return secret_box.reveal(data['key'])
    except (ValueError, UnicodeDecodeError):
        logger.error('Stripe: la clave guardada no se puede leer; hay que volver a conectarla.')
        return None


def key_summary(root: str) -> Optional[dict]:
    """What may be shown on screen about the stored key: never the key itself."""
    data = _read(root)
    if not data:
        return None
    return {name: str(data.get(name, '')) for name in ('last4', 'mode', 'kind', 'connected_at')}


def forget_key(root: str) -> None:
    try:
        os.remove(_path(root))
    except FileNotFoundError:
        pass
