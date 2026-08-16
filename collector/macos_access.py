from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

# Apple Messages epoch: 2001-01-01 00:00:00 UTC
APPLE_EPOCH = 978307200
TIMESTAMP_FACTOR = 1_000_000_000
FDA_HELP = """macOS Full Disk Access is required to read Messages.

System Settings > Privacy & Security > Full Disk Access
Enable the terminal app or Python interpreter you are using, then retry.

The Messages database is opened READ ONLY. This app never writes to chat.db.
"""


def default_chat_db_path() -> Path:
    return Path.home() / "Library" / "Messages" / "chat.db"


def apple_timestamp_to_datetime(value: int | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    stamp = int(value)
    seconds_since_2001 = stamp // TIMESTAMP_FACTOR if stamp >= 1_000_000_000_000 else stamp
    return datetime.fromtimestamp(seconds_since_2001 + APPLE_EPOCH, tz=timezone.utc)


def normalize_service(name: str | None) -> str:
    if not name:
        return "Unknown"
    cleaned = name.strip()
    mapping = {
        "iMessage": "iMessage",
        "iMessageLite": "Satellite",
        "SMS": "SMS",
        "sms": "SMS",
        "RCS": "RCS",
        "rcs": "RCS",
    }
    return mapping.get(cleaned, cleaned)


def mask_sender(sender: str) -> str:
    digits = "".join(ch for ch in sender if ch.isdigit())
    if len(digits) >= 8 and (sender.startswith("+") or sender.startswith("00")):
        prefix = sender[:5] if sender.startswith("+") else sender[:4]
        return prefix + ("X" * max(len(sender) - len(prefix), 4))
    return sender


def is_permission_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "authorization",
            "permission denied",
            "not authorized",
            "unable to open",
            "operation not permitted",
            "access denied",
        )
    )
