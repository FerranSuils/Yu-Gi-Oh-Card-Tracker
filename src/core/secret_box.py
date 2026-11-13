"""Keeps a secret unreadable at rest. On Windows it is sealed with DPAPI, so the file is useless
outside this machine and this Windows user; elsewhere the caller must restrict the file itself."""

from __future__ import annotations

import base64
import binascii
import os

_WINDOWS = os.name == 'nt'

if _WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _ARGS = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
             wintypes.DWORD, ctypes.POINTER(_Blob)]
    _crypt32.CryptProtectData.argtypes = _ARGS
    _crypt32.CryptUnprotectData.argtypes = _ARGS
    _UI_FORBIDDEN = 0x1

    def _dpapi(function, data: bytes) -> bytes:
        buffer = ctypes.create_string_buffer(data, len(data))
        source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        result = _Blob()
        if not function(ctypes.byref(source), None, None, None, None, _UI_FORBIDDEN, ctypes.byref(result)):
            raise ValueError('No se pudo proteger o leer el secreto')
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def protect(text: str) -> str:
    data = text.encode('utf-8')
    if _WINDOWS:
        return 'dpapi:' + base64.b64encode(_dpapi(_crypt32.CryptProtectData, data)).decode('ascii')
    return 'plain:' + base64.b64encode(data).decode('ascii')


def reveal(blob: str) -> str:
    kind, _, body = (blob or '').partition(':')
    try:
        data = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('Secreto ilegible') from None
    if not data:
        raise ValueError('Secreto ilegible')
    if kind == 'dpapi' and _WINDOWS:
        return _dpapi(_crypt32.CryptUnprotectData, data).decode('utf-8')
    if kind == 'plain' and not _WINDOWS:
        return data.decode('utf-8')
    raise ValueError('Secreto ilegible')
