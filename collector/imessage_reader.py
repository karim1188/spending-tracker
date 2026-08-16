from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from collector.macos_access import (
    FDA_HELP,
    apple_timestamp_to_datetime,
    default_chat_db_path,
    is_permission_error,
    normalize_service,
)
from collector.project_paths import RUST_READER_DIR
from collector.streamtyped import StreamTypedError, parse_streamtyped
from models.message import Message

INCOMING_QUERY = """
SELECT
    m.ROWID AS id,
    m.guid AS guid,
    COALESCE(h.id, '') AS sender,
    m.text AS text,
    m.attributedBody AS attributed_body,
    m.date AS date,
    m.service AS service,
    m.is_from_me AS is_from_me
FROM message AS m
LEFT JOIN handle AS h ON m.handle_id = h.ROWID
WHERE m.ROWID > ?
  AND (? = 0 OR m.is_from_me = 0)
ORDER BY m.ROWID ASC
LIMIT ?
"""

SENDERS_QUERY = """
SELECT
    COALESCE(h.id, '') AS sender,
    COUNT(*) AS message_count
FROM message AS m
LEFT JOIN handle AS h ON m.handle_id = h.ROWID
WHERE m.is_from_me = 0
  AND COALESCE(h.id, '') != ''
GROUP BY h.id
ORDER BY message_count DESC, sender ASC
"""


class MessagesAccessError(RuntimeError):
    def __init__(self, message: str, *, full_disk_access: bool = False):
        super().__init__(message)
        self.full_disk_access = full_disk_access


@dataclass(slots=True)
class AccessResult:
    ok: bool
    path: Path
    read_only: bool
    message: str
    full_disk_access_required: bool = False


class IMessageReader:
    """Normalized incoming-message reader.

    Prefer the Rust helper (imessage_database + crabstep) when it is built.
    Otherwise open chat.db with sqlite3 URI mode=ro and decode text /
    streamtyped fallback only. Never writes to chat.db.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        rust_bin: Path | None = None,
        use_rust: bool = True,
    ):
        self.db_path = Path(db_path) if db_path else default_chat_db_path()
        if rust_bin is not None:
            self.rust_bin = rust_bin
        elif use_rust:
            self.rust_bin = _discover_rust_bin()
        else:
            self.rust_bin = None

    def test_access(self) -> AccessResult:
        path = self.db_path
        if not path.exists():
            return AccessResult(
                ok=False,
                path=path,
                read_only=True,
                message=(
                    f"Messages database not found at {path}. "
                    "This pipeline is designed for macOS with Messages enabled."
                ),
                full_disk_access_required=True,
            )
        try:
            conn = self._connect_readonly()
            try:
                conn.execute("SELECT ROWID FROM message LIMIT 1").fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            fda = is_permission_error(exc)
            return AccessResult(
                ok=False,
                path=path,
                read_only=True,
                message=f"Could not open Messages database read-only: {exc}",
                full_disk_access_required=fda,
            )
        return AccessResult(
            ok=True,
            path=path,
            read_only=True,
            message="Messages database connected in READ ONLY mode",
        )

    def get_messages(
        self,
        after_id: int = 0,
        limit: int = 100,
        incoming_only: bool = True,
    ) -> list[Message]:
        if self.rust_bin and self.rust_bin.exists():
            return self._get_messages_rust(after_id, limit, incoming_only)
        return self._get_messages_python(after_id, limit, incoming_only)

    def list_senders(self) -> list[tuple[str, int]]:
        if self.rust_bin and self.rust_bin.exists():
            payload = self._run_rust(["--list-senders", "--db-path", str(self.db_path)])
            return [(item["sender"], int(item["count"])) for item in payload]
        conn = self._connect_readonly()
        try:
            rows = conn.execute(SENDERS_QUERY).fetchall()
            return [(row["sender"], int(row["message_count"])) for row in rows]
        finally:
            conn.close()

    def _get_messages_python(
        self, after_id: int, limit: int, incoming_only: bool
    ) -> list[Message]:
        conn = self._connect_readonly()
        try:
            rows = conn.execute(
                INCOMING_QUERY,
                (after_id, 1 if incoming_only else 0, limit),
            ).fetchall()
            messages: list[Message] = []
            for row in rows:
                text = (row["text"] or "").strip()
                if not text and row["attributed_body"]:
                    try:
                        text = parse_streamtyped(row["attributed_body"])
                    except StreamTypedError:
                        text = ""
                messages.append(
                    Message(
                        id=int(row["id"]),
                        guid=str(row["guid"]),
                        sender=str(row["sender"] or ""),
                        text=text,
                        timestamp=apple_timestamp_to_datetime(row["date"]),
                        service=normalize_service(row["service"]),
                        is_from_me=bool(row["is_from_me"]),
                    )
                )
            return messages
        finally:
            conn.close()

    def _get_messages_rust(
        self, after_id: int, limit: int, incoming_only: bool
    ) -> list[Message]:
        args = [
            "--db-path",
            str(self.db_path),
            "--after-id",
            str(after_id),
            "--limit",
            str(limit),
        ]
        if incoming_only:
            args.append("--incoming-only")
        payload = self._run_rust(args)
        return [Message.from_dict(item) for item in payload]

    def _run_rust(self, args: list[str]) -> list[dict]:
        assert self.rust_bin is not None
        completed = subprocess.run(
            [str(self.rust_bin), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise MessagesAccessError(
                completed.stderr.strip() or "imessage_reader failed",
                full_disk_access=is_permission_error(completed.stderr),
            )
        return json.loads(completed.stdout or "[]")

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise MessagesAccessError(
                f"Messages database not found at {self.db_path}\n{FDA_HELP}",
                full_disk_access=True,
            )
        uri = self.db_path.resolve().as_posix()
        try:
            conn = sqlite3.connect(f"file:{uri}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise MessagesAccessError(
                f"Could not open Messages database read-only: {exc}\n{FDA_HELP}",
                full_disk_access=is_permission_error(exc),
            ) from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn


def _discover_rust_bin() -> Path | None:
    env = os.environ.get("IMESSAGE_READER_BIN")
    if env:
        path = Path(env)
        return path if path.exists() else None
    candidates = [
        RUST_READER_DIR / "target" / "release" / "imessage_reader",
        RUST_READER_DIR / "target" / "release" / "imessage_reader.exe",
        RUST_READER_DIR / "target" / "debug" / "imessage_reader",
        RUST_READER_DIR / "target" / "debug" / "imessage_reader.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
