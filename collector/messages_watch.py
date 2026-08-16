from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from collector.logging_config import get_logger
from collector.macos_access import default_chat_db_path

logger = get_logger()

WATCH_NAMES = ("chat.db", "chat.db-wal", "chat.db-shm")


def messages_watch_paths(chat_db: Path | None = None) -> list[Path]:
    root = Path(chat_db) if chat_db else default_chat_db_path()
    parent = root.parent
    return [parent / name for name in WATCH_NAMES]


def snapshot_mtimes(paths: list[Path]) -> dict[str, float]:
    out: dict[str, float] = {}
    for path in paths:
        try:
            out[str(path)] = path.stat().st_mtime
        except OSError:
            out[str(path)] = -1.0
    return out


class MessagesWatcher:
    """Idle until Apple Messages writes chat.db (FSEvents via watchdog, else mtime)."""

    def __init__(
        self,
        on_change: Callable[[], None],
        chat_db: Path | None = None,
        debounce_seconds: float = 2.0,
        mtime_poll_seconds: float = 3.0,
    ) -> None:
        self.on_change = on_change
        self.chat_db = Path(chat_db) if chat_db else default_chat_db_path()
        self.debounce_seconds = debounce_seconds
        self.mtime_poll_seconds = mtime_poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._debounce_timer: threading.Timer | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="messages-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        if self._thread:
            self._thread.join(timeout=5)

    def _schedule(self) -> None:
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            timer = threading.Timer(self.debounce_seconds, self._fire)
            timer.daemon = True
            self._debounce_timer = timer
            timer.start()

    def _fire(self) -> None:
        if self._stop.is_set():
            return
        try:
            self.on_change()
        except Exception as exc:  # noqa: BLE001 — keep watching
            logger.info("Messages watch handler failed: %s", exc)

    def _run(self) -> None:
        paths = messages_watch_paths(self.chat_db)
        directory = self.chat_db.parent
        if self._run_watchdog(directory):
            return
        logger.info(
            "Messages idle watch: mtime poll every %.0fs on %s (install watchdog for FSEvents)",
            self.mtime_poll_seconds,
            directory,
        )
        self._run_mtime(paths)

    def _run_watchdog(self, directory: Path) -> bool:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return False
        if not directory.is_dir():
            logger.info("Messages folder missing: %s", directory)
            return False

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):  # type: ignore[no-untyped-def]
                name = Path(getattr(event, "src_path", "") or "").name
                if name in WATCH_NAMES or name.startswith("chat.db"):
                    watcher._schedule()

        observer = Observer()
        observer.schedule(Handler(), str(directory), recursive=False)
        observer.start()
        logger.info("Messages idle watch: FSEvents on %s", directory)
        try:
            while not self._stop.wait(0.5):
                if not observer.is_alive():
                    break
        finally:
            observer.stop()
            observer.join(timeout=5)
        return True

    def _run_mtime(self, paths: list[Path]) -> None:
        last = snapshot_mtimes(paths)
        while not self._stop.is_set():
            time.sleep(self.mtime_poll_seconds)
            if self._stop.is_set():
                return
            current = snapshot_mtimes(paths)
            if current != last:
                last = current
                self._schedule()
