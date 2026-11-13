"""Page teardown that survives a dropped socket.

NiceGUI 3 calls ``client.on_disconnect`` handlers on every socket drop, also when
the browser reconnects to the same page a moment later. A page that cancels its
timers there stays dead after the reconnect: the scan page stopped receiving
results in the middle of a long batch. ``on_delete`` only fires once the client
is really gone.
"""

from __future__ import annotations

from typing import Callable


def cleanup_when_client_is_deleted(client, cleanup: Callable[[], None]) -> None:
    client.on_delete(cleanup)
