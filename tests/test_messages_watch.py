from __future__ import annotations

import time
from pathlib import Path

from collector.messages_watch import MessagesWatcher, messages_watch_paths, snapshot_mtimes


def test_messages_watch_paths_include_wal(tmp_path):
    chat = tmp_path / "chat.db"
    paths = messages_watch_paths(chat)
    names = {p.name for p in paths}
    assert names == {"chat.db", "chat.db-wal", "chat.db-shm"}


def test_snapshot_mtimes_tracks_change(tmp_path):
    chat = tmp_path / "chat.db"
    chat.write_text("a", encoding="utf-8")
    paths = [chat]
    first = snapshot_mtimes(paths)
    time.sleep(0.05)
    chat.write_text("b", encoding="utf-8")
    second = snapshot_mtimes(paths)
    assert first != second


def test_messages_watcher_mtime_fires_callback(tmp_path):
    chat = tmp_path / "chat.db"
    chat.write_text("start", encoding="utf-8")
    (tmp_path / "chat.db-wal").write_text("wal", encoding="utf-8")
    hits: list[str] = []

    watcher = MessagesWatcher(
        on_change=lambda: hits.append("ok"),
        chat_db=chat,
        debounce_seconds=0.05,
        mtime_poll_seconds=0.05,
    )
    # Force mtime path even if watchdog is installed.
    watcher._run_watchdog = lambda directory: False  # type: ignore[method-assign]
    watcher.start()
    try:
        time.sleep(0.12)
        chat.write_text("changed", encoding="utf-8")
        deadline = time.time() + 2.0
        while not hits and time.time() < deadline:
            time.sleep(0.05)
        assert hits == ["ok"]
    finally:
        watcher.stop()
