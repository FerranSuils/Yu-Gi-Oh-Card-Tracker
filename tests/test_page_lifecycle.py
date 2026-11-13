from pathlib import Path


class FakeClient:
    """Mirrors NiceGUI 3: on_disconnect also fires on a transient socket drop, on_delete only at the end."""

    def __init__(self):
        self.disconnect_handlers, self.delete_handlers = [], []

    def on_disconnect(self, handler):
        self.disconnect_handlers.append(handler)

    def on_delete(self, handler):
        self.delete_handlers.append(handler)


def test_cleanup_survives_a_reconnect_and_runs_on_delete():
    from src.ui.page_lifecycle import cleanup_when_client_is_deleted

    client, calls = FakeClient(), []
    cleanup_when_client_is_deleted(client, lambda: calls.append('cleanup'))
    for handler in client.disconnect_handlers:  # the socket drops and the browser reconnects
        handler()
    assert calls == []
    for handler in client.delete_handlers:
        handler()
    assert calls == ['cleanup']


def test_scan_page_does_not_tear_down_on_a_socket_drop():
    source = Path('src/ui/scan.py').read_text(encoding='utf-8')
    assert 'on_disconnect(' not in source
    assert 'cleanup_when_client_is_deleted(ui.context.client, cleanup)' in source
