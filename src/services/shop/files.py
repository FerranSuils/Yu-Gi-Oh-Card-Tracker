"""JSON lists under <cuenta>/shop/. A file that cannot be read is never written over."""

from __future__ import annotations

import json
import os
from typing import List, Type, TypeVar

from pydantic import BaseModel

from src.services.sales.store import _root_lock, _write, patiently

Model = TypeVar('Model', bound=BaseModel)
root_lock = _root_lock


class BrokenFile(Exception):
    """A shop file exists but does not hold what it should."""


def shop_path(root: str, name: str) -> str:
    return os.path.join(root, 'shop', name)


def _load(path: str):
    with open(path, 'r', encoding='utf-8') as file:
        return json.load(file)


def read_list(path: str, model: Type[Model]) -> List[Model]:
    if not os.path.exists(path):
        return []
    try:
        rows = patiently(lambda: _load(path))
        if not isinstance(rows, list):
            raise ValueError('not a list')
        return [model(**row) for row in rows]
    except (OSError, ValueError, TypeError) as error:
        raise BrokenFile(os.path.basename(path)) from error


def write_list(path: str, items: List[BaseModel]) -> None:
    _write(path, [item.model_dump(mode='json') for item in items])
