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

    def _period_clause(
        self,
        year: str | None = None,
        month: str | None = None,
        bank: str | None = None,
        category: str | None = None,
        sender: str | None = None,
        transaction_type: str | None = None,
        query: str | None = None,
    ) -> tuple[str, list[object]]:
        sql = []
        params: list[object] = []
        stamp = "COALESCE(transaction_time, created_at)"
        if year:
            sql.append(f"AND strftime('%Y', {stamp}) = ?")
            params.append(str(year))
        if month:
            sql.append(f"AND strftime('%m', {stamp}) = ?")
            params.append(str(month).zfill(2))
        if bank:
            sql.append("AND bank = ?")
            params.append(bank)
        if category:
            sql.append("AND category = ?")
            params.append(category)
        if sender:
            sql.append("AND sender = ?")
            params.append(sender)
        if transaction_type:
            sql.append("AND transaction_type = ?")
            params.append(transaction_type)
        if query:
            sql.append("AND (IFNULL(merchant, '') LIKE ? OR IFNULL(sender, '') LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])
        return "\n".join(sql), params

    def list_transactions(
        self,
        limit: int = 500,
        year: str | None = None,
        month: str | None = None,
        bank: str | None = None,
        category: str | None = None,
        sender: str | None = None,
        transaction_type: str | None = None,
        query: str | None = None,
    ) -> list[sqlite3.Row]:
        extra, params = self._period_clause(
            year, month, bank, category, sender, transaction_type, query
        )
        params.append(limit)
        return self.conn.execute(
            f"""
            SELECT id, bank, sender, transaction_type, amount, currency, merchant,
                   card_last4, account_last4, transaction_time, balance, category,
                   created_at
            FROM transactions
            WHERE 1=1
            {extra}
            ORDER BY COALESCE(transaction_time, created_at) DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    def get_transaction(self, txn_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM transactions WHERE id = ?",
            (txn_id,),
        ).fetchone()

    def delete_transaction(self, txn_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def purge_duplicates(self) -> int:
        before = self.conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
        self.conn.execute(
            """
            DELETE FROM transactions
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM transactions
                GROUP BY
                    IFNULL(sender, ''),
                    ROUND(COALESCE(amount, 0), 2),
                    IFNULL(merchant, ''),
                    IFNULL(currency, ''),
                    date(COALESCE(transaction_time, created_at))
            )
            """
        )
        self.conn.commit()
        after = self.conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
        return int(before) - int(after)

    def filter_options(self) -> dict:
        def column_values(column: str) -> list[str]:
            rows = self.conn.execute(
                f"""
                SELECT DISTINCT {column} AS value
                FROM transactions
                WHERE {column} IS NOT NULL AND TRIM({column}) != ''
                ORDER BY value
                """
            ).fetchall()
            return [row["value"] for row in rows]

        years = [
            row["value"]
            for row in self.conn.execute(
                """
                SELECT DISTINCT strftime('%Y', COALESCE(transaction_time, created_at)) AS value
                FROM transactions
                WHERE COALESCE(transaction_time, created_at) IS NOT NULL
                ORDER BY value DESC
                """
            ).fetchall()
            if row["value"]
        ]
        return {
            "years": years,
            "banks": column_values("bank"),
            "categories": column_values("category"),
            "senders": column_values("sender"),
            "types": column_values("transaction_type"),
        }

    def sender_rule(self, sender: str) -> sqlite3.Row | None:
        if not sender:
            return None
        return self.conn.execute(
            "SELECT * FROM sender_rules WHERE sender = ?",
            (sender,),
        ).fetchone()

    def upsert_sender_rule(
        self,
        sender: str,
        category: str | None = None,
        bank: str | None = None,
        apply_existing: bool = True,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat(sep=" ")
        self.conn.execute(
            """
            INSERT INTO sender_rules (sender, category, bank, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sender) DO UPDATE SET
                category = excluded.category,
                bank = COALESCE(excluded.bank, sender_rules.bank),
                updated_at = excluded.updated_at
            """,
            (sender, category, bank, now),
        )
        if apply_existing:
            if category:
                self.conn.execute(
                    "UPDATE transactions SET category = ? WHERE sender = ?",
                    (category, sender),
                )
            if bank:
                self.conn.execute(
                    "UPDATE transactions SET bank = ? WHERE sender = ?",
                    (bank, sender),
                )
        self.conn.commit()

    def summary(
        self,
        year: str | None = None,
        month: str | None = None,
        bank: str | None = None,
        category: str | None = None,
        sender: str | None = None,
        transaction_type: str | None = None,
        query: str | None = None,
    ) -> dict:
        extra, params = self._period_clause(
            year, month, bank, category, sender, transaction_type, query
        )
        total_row = self.conn.execute(
            f"""
            SELECT
                COUNT(*) AS txn_count,
                COALESCE(SUM(CASE WHEN amount IS NOT NULL THEN amount ELSE 0 END), 0) AS total_amount
            FROM transactions
            WHERE 1=1
            {extra}
            """,
            params,
        ).fetchone()
        by_category = self.conn.execute(
            f"""
            SELECT COALESCE(category, 'Other') AS label,
                   COUNT(*) AS txn_count,
                   COALESCE(SUM(amount), 0) AS total_amount
            FROM transactions
            WHERE 1=1
            {extra}
            GROUP BY COALESCE(category, 'Other')
            ORDER BY total_amount DESC
            """,
            params,
        ).fetchall()
        by_bank = self.conn.execute(
            f"""
            SELECT COALESCE(bank, 'Unknown') AS label,
                   COUNT(*) AS txn_count,
                   COALESCE(SUM(amount), 0) AS total_amount
            FROM transactions
            WHERE 1=1
            {extra}
            GROUP BY COALESCE(bank, 'Unknown')
            ORDER BY total_amount DESC
            """,
            params,
        ).fetchall()
        checkpoint = self.conn.execute(
            "SELECT source, last_message_id, last_checked_at FROM collector_state"
        ).fetchall()
        return {
            "txn_count": int(total_row["txn_count"]),
            "total_amount": float(total_row["total_amount"]),
            "by_category": [dict(row) for row in by_category],
            "by_bank": [dict(row) for row in by_bank],
            "checkpoint": [dict(row) for row in checkpoint],
        }


