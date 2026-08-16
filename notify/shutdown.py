from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger("spending")

_lock = threading.Lock()
_callback: Callable[[str], None] | None = None
_triggered = False


def register_shutdown(callback: Callable[[str], None]) -> None:
    global _callback
    with _lock:
        _callback = callback


def request_shutdown(reason: str) -> bool:
    """Ask the app to stop. Returns True if a shutdown was started."""
    global _triggered
    with _lock:
        if _triggered:
            return False
        callback = _callback
        if callback is None:
            logger.warning("Shutdown requested but no handler registered: %s", reason)
            return False
        _triggered = True
    try:
        callback(reason)
    except Exception:  # noqa: BLE001 — never block the alert loop on shutdown errors
        logger.exception("Shutdown handler failed")
        return False
    return True
