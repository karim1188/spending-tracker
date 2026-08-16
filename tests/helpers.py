from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from collector.macos_access import APPLE_EPOCH, TIMESTAMP_FACTOR
from config.loader import BankConfig, BankRegistry

BANK_NAMES = ("SNB", "AlRajhi", "RiyadBank", "SAB", "Alinma", "MobilyPay")


def unix_to_apple(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = int(dt.timestamp()) - APPLE_EPOCH
    return seconds * TIMESTAMP_FACTOR


def make_bank_registry(**senders_by_bank: tuple[str, ...] | list[str]) -> BankRegistry:
    banks = {name: BankConfig(name, tuple(senders_by_bank.get(name, ()))) for name in BANK_NAMES}
    return BankRegistry(banks)


def make_streamtyped_blob(text: str) -> bytes:
    return b"xxxx" + bytes((0x01, 0x2B)) + b"\x06" + text.encode("utf-8") + bytes((0x86, 0x84)) + b"yyyy"


def create_mock_chat_db(path: Path, rows: list[dict]) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY,
            id TEXT NOT NULL
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT NOT NULL,
            text TEXT,
            attributedBody BLOB,
            date INTEGER,
            service TEXT,
            is_from_me INTEGER DEFAULT 0,
            handle_id INTEGER
        );
        """
    )
    handles: dict[str, int] = {}
    for row in rows:
        sender = row["sender"]
        if sender not in handles:
            cur = conn.execute("INSERT INTO handle (id) VALUES (?)", (sender,))
            handles[sender] = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO message (ROWID, guid, text, attributedBody, date, service, is_from_me, handle_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["guid"],
                row.get("text"),
                row.get("attributed_body"),
                row.get("date", unix_to_apple(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))),
                row.get("service", "SMS"),
                1 if row.get("is_from_me") else 0,
                handles[sender],
            ),
        )
    conn.commit()
    conn.close()
    return path
