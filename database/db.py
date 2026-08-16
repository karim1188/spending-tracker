from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from collector.project_paths import SCHEMA_PATH, SPENDING_DB_PATH
from models.transaction import Transaction

COLLECTOR_SOURCE = "macos_messages"


class SpendingDatabase:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else SPENDING_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def initialize(self) -> None:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        self.conn.executescript(schema)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> SpendingDatabase:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def guid_exists(self, guid: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM transactions WHERE source_message_guid = ? LIMIT 1",
            (guid,),
        ).fetchone()
        return row is not None

    def insert_transaction(self, tx: Transaction) -> bool:
        """Insert a transaction. Returns False if the GUID already exists."""
        row = tx.to_row()
        try:
            self.conn.execute(
                """
                INSERT INTO transactions (
                    source_message_guid, bank, sender, transaction_type, amount,
                    currency, merchant, card_last4, account_last4, transaction_time,
                    balance, category, subcategory, raw_message
                ) VALUES (
                    :source_message_guid, :bank, :sender, :transaction_type, :amount,
                    :currency, :merchant, :card_last4, :account_last4, :transaction_time,
                    :balance, :category, :subcategory, :raw_message
                )
                """,
                row,
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def recent_transactions(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM transactions
            ORDER BY COALESCE(transaction_time, created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def get_checkpoint(self, source: str = COLLECTOR_SOURCE) -> int:
        row = self.conn.execute(
            "SELECT last_message_id FROM collector_state WHERE source = ?",
            (source,),
        ).fetchone()
        return int(row["last_message_id"]) if row else 0

    def set_checkpoint(self, last_message_id: int, source: str = COLLECTOR_SOURCE) -> None:
        now = datetime.now(timezone.utc).isoformat(sep=" ")
        self.conn.execute(
            """
            INSERT INTO collector_state (source, last_message_id, last_checked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                last_message_id = excluded.last_message_id,
                last_checked_at = excluded.last_checked_at
            """,
            (source, last_message_id, now),
        )
        self.conn.commit()

    def replace_bank_senders(self, mapping: dict[str, list[str]]) -> None:
        self.conn.execute("DELETE FROM bank_senders")
        for bank, senders in mapping.items():
            for sender in senders:
                self.conn.execute(
                    "INSERT OR IGNORE INTO bank_senders (bank, sender) VALUES (?, ?)",
                    (bank, sender),
                )
        self.conn.commit()

    def upsert_merchant_rule(self, pattern: str, category: str) -> None:
        self.conn.execute(
            """
            INSERT INTO merchant_rules (pattern, category) VALUES (?, ?)
            ON CONFLICT(pattern) DO UPDATE SET category = excluded.category
            """,
            (pattern, category),
        )
        self.conn.commit()

    def merchant_rules(self) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT pattern, category FROM merchant_rules ORDER BY LENGTH(pattern) DESC"
        ).fetchall()
        return [(row["pattern"], row["category"]) for row in rows]

    def list_transactions(
        self,
        limit: int = 200,
        bank: str | None = None,
        category: str | None = None,
    ) -> list[sqlite3.Row]:
        sql = [
            """
            SELECT id, bank, sender, transaction_type, amount, currency, merchant,
                   card_last4, account_last4, transaction_time, balance, category,
                   created_at
            FROM transactions
            WHERE 1=1
            """
        ]
        params: list[object] = []
        if bank:
            sql.append("AND bank = ?")
            params.append(bank)
        if category:
            sql.append("AND category = ?")
            params.append(category)
        sql.append("ORDER BY COALESCE(transaction_time, created_at) DESC, id DESC")
        sql.append("LIMIT ?")
        params.append(limit)
        return self.conn.execute("\n".join(sql), params).fetchall()

    def summary(self) -> dict:
        total_row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS txn_count,
                COALESCE(SUM(CASE WHEN amount IS NOT NULL THEN amount ELSE 0 END), 0) AS total_amount
            FROM transactions
            """
        ).fetchone()
        month_row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS txn_count,
                COALESCE(SUM(CASE WHEN amount IS NOT NULL THEN amount ELSE 0 END), 0) AS total_amount
            FROM transactions
            WHERE strftime('%Y-%m', COALESCE(transaction_time, created_at)) = strftime('%Y-%m', 'now')
            """
        ).fetchone()
        by_category = self.conn.execute(
            """
            SELECT COALESCE(category, 'Other') AS label,
                   COUNT(*) AS txn_count,
                   COALESCE(SUM(amount), 0) AS total_amount
            FROM transactions
            GROUP BY COALESCE(category, 'Other')
            ORDER BY total_amount DESC
            """
        ).fetchall()
        by_bank = self.conn.execute(
            """
            SELECT COALESCE(bank, 'Unknown') AS label,
                   COUNT(*) AS txn_count,
                   COALESCE(SUM(amount), 0) AS total_amount
            FROM transactions
            GROUP BY COALESCE(bank, 'Unknown')
            ORDER BY total_amount DESC
            """
        ).fetchall()
        checkpoint = self.conn.execute(
            "SELECT source, last_message_id, last_checked_at FROM collector_state"
        ).fetchall()
        return {
            "txn_count": int(total_row["txn_count"]),
            "total_amount": float(total_row["total_amount"]),
            "month_count": int(month_row["txn_count"]),
            "month_amount": float(month_row["total_amount"]),
            "by_category": [dict(row) for row in by_category],
            "by_bank": [dict(row) for row in by_bank],
            "checkpoint": [dict(row) for row in checkpoint],
        }

