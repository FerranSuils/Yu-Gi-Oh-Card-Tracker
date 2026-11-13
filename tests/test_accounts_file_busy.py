import sys
import threading
import time
from unittest.mock import Mock

import pytest

from src.services.auth_service import AuthService


def _service(tmp_path):
    manager = Mock()
    manager.get_auth_username.return_value = 'owner'
    manager.get_auth_password_hash.return_value = ''
    return AuthService(manager, accounts_file=tmp_path / 'accounts.json')


@pytest.mark.skipif(sys.platform != 'win32', reason='only Windows refuses to replace a file somebody is reading')
def test_signing_up_while_somebody_is_reading_the_accounts_waits_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = _service(tmp_path)
    service.register('first', 'ValidPass123!', 'ValidPass123!')
    reader = open(service.accounts_file, 'rb')   # a login reading the file at that very moment
    threading.Timer(0.3, reader.close).start()
    try:
        assert service.register('second', 'ValidPass123!', 'ValidPass123!') == 'second'
    finally:
        reader.close()
    assert service.identify('second', 'ValidPass123!') == 'second'
    assert service.identify('first', 'ValidPass123!') == 'first'


def test_a_file_that_stays_locked_is_still_an_error_and_keeps_the_accounts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = _service(tmp_path)
    service.register('first', 'ValidPass123!', 'ValidPass123!')
    monkeypatch.setattr('src.services.auth_service.os.replace', Mock(side_effect=PermissionError('busy')))
    monkeypatch.setattr('src.services.auth_service.time.sleep', lambda seconds: None, raising=False)
    with pytest.raises(PermissionError):
        service.register('second', 'ValidPass123!', 'ValidPass123!')
    monkeypatch.undo()
    assert [a['username'] for a in service._read_accounts()] == ['first']
