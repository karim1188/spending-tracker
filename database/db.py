from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from collector.project_paths import SCHEMA_PATH, SPENDING_DB_PATH
from models.transaction import Transaction

NON_SPENDING_TYPES = ("salary", "bank_transfer_in", "wallet_topup")
NON_SPENDING_SQL = "('salary', 'bank_transfer_in', 'wallet_topup')"
RECURRING_FREQUENCIES = ("daily", "weekly", "monthly")

COLLECTOR_SOURCE = "macos_messages"
MONTH_LABELS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _month_label(period: str) -> str:
    try:
        month = int(period.split("-")[1])
    except (IndexError, ValueError):
        return period
    if 1 <= month <= 12:
        return MONTH_LABELS[month - 1]
    return period


def monthly_from_frequency(amount: float, frequency: str) -> float:
    freq = (frequency or "monthly").strip().lower()
    if freq == "daily":
        return float(amount) * 30
    if freq == "weekly":
        return float(amount) * 52 / 12
    return float(amount)


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
        self._migrate()
        self.conn.commit()
        self.exclude_guid(
            "781A1E6A-0B82-B291-7EEB-ED6DDC8E2788",
            "SNB activation PIN, not a transfer",
        )
        self.purge_pin_messages()
        self.repair_classifications()

    def _migrate(self) -> None:
        txn_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(transactions)")}
        if "is_recurring" not in txn_columns:
            self.conn.execute(
                "ALTER TABLE transactions ADD COLUMN is_recurring INTEGER NOT NULL DEFAULT 0"
            )
        recurring_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(recurring_items)")
        }
        if "frequency" not in recurring_columns:
            self.conn.execute(
                "ALTER TABLE recurring_items ADD COLUMN frequency TEXT NOT NULL DEFAULT 'monthly'"
            )
        if "source" not in recurring_columns:
            self.conn.execute(
                "ALTER TABLE recurring_items ADD COLUMN source TEXT NOT NULL DEFAULT 'transaction'"
            )
        if "monthly_amount" not in recurring_columns:
            self.conn.execute(
                "ALTER TABLE recurring_items ADD COLUMN monthly_amount REAL NOT NULL DEFAULT 0"
            )
            self.conn.execute(
                """
                UPDATE recurring_items
                SET monthly_amount = amount
                WHERE monthly_amount = 0 OR monthly_amount IS NULL
                """
            )

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
            cursor = self.conn.execute(
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
            self._flag_if_known_recurring(cursor.lastrowid, tx.merchant)
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

    def upsert_merchant_rule(self, pattern: str, category: str, apply_existing: bool = False) -> None:
        pattern = (pattern or "").strip().upper()
        category = (category or "").strip()
        if not pattern or not category:
            return
        self.conn.execute(
            """
            INSERT INTO merchant_rules (pattern, category) VALUES (?, ?)
            ON CONFLICT(pattern) DO UPDATE SET category = excluded.category
            """,
            (pattern, category),
        )
        if apply_existing:
            self.conn.execute(
                """
                UPDATE transactions
                SET category = ?
                WHERE instr(UPPER(IFNULL(merchant, '')), UPPER(?)) > 0
                """,
                (category, pattern),
            )
        self.conn.commit()

    def set_transaction_category(self, txn_id: int, category: str) -> bool:
        category = (category or "").strip()
        if not category:
            return False
        cursor = self.conn.execute(
            "UPDATE transactions SET category = ? WHERE id = ?",
            (category, txn_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

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
                   created_at, is_recurring
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

    def exclude_guid(self, guid: str, reason: str = "excluded") -> None:
        guid = guid.strip()
        if not guid:
            return
        self.conn.execute(
            """
            INSERT OR IGNORE INTO excluded_messages (guid, reason) VALUES (?, ?)
            """,
            (guid, reason),
        )
        self.conn.execute(
            "DELETE FROM transactions WHERE source_message_guid = ?",
            (guid,),
        )
        self.conn.commit()

    def is_excluded(self, guid: str) -> bool:
        if not guid:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM excluded_messages WHERE guid = ? LIMIT 1",
            (guid,),
        ).fetchone()
        return row is not None

    def exclude_transaction(self, txn_id: int, reason: str = "excluded") -> bool:
        row = self.get_transaction(txn_id)
        if not row:
            return False
        self.exclude_guid(row["source_message_guid"], reason)
        return True

    def repair_classifications(self) -> None:
        from categorizer.categorizer import Categorizer
        from parsers.generic import classify_transaction_type

        categorizer = Categorizer(dict(self.merchant_rules()))
        rows = self.conn.execute(
            "SELECT id, bank, merchant, transaction_type, raw_message FROM transactions"
        ).fetchall()
        for row in rows:
            tx_type = row["transaction_type"] or "unknown"
            if row["raw_message"]:
                inferred = classify_transaction_type(row["raw_message"], bank=row["bank"])
                if inferred != "unknown":
                    tx_type = inferred
            category = categorizer.categorize(row["merchant"], tx_type)
            self.conn.execute(
                """
                UPDATE transactions
                SET transaction_type = ?, category = ?
                WHERE id = ?
                """,
                (tx_type, category, row["id"]),
            )
        if rows:
            self.conn.commit()

    def purge_pin_messages(self) -> int:
        from parsers.generic import looks_non_financial

        rows = self.conn.execute(
            "SELECT id, raw_message FROM transactions WHERE raw_message IS NOT NULL"
        ).fetchall()
        removed = 0
        for row in rows:
            if looks_non_financial(row["raw_message"]):
                self.conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))
                removed += 1
        if removed:
            self.conn.commit()
        return removed

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
        if transaction_type not in NON_SPENDING_TYPES and category != "Salary":
            extra = f"{extra}\nAND IFNULL(transaction_type, '') NOT IN {NON_SPENDING_SQL}"
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
        rec = self.recurring_summary()
        return {
            "txn_count": int(total_row["txn_count"]),
            "total_amount": float(total_row["total_amount"]),
            "by_category": [dict(row) for row in by_category],
            "by_bank": [dict(row) for row in by_bank],
            "checkpoint": [dict(row) for row in checkpoint],
            "recurring_monthly": rec["monthly_total"],
            "recurring_count": rec["item_count"],
        }

    def dashboard(
        self,
        year: str | None = None,
        month: str | None = None,
        bank: str | None = None,
        timezone_name: str = "Asia/Riyadh",
        now: datetime | None = None,
    ) -> dict:
        """Dashboard totals for the scoped month; income-vs-spending chart uses rolling 12 months."""
        from zoneinfo import ZoneInfo

        from collector.salary_period import pay_month_for_salary

        tz = ZoneInfo(timezone_name)
        stamp = now.astimezone(tz) if now else datetime.now(tz)
        scope_year = int(year) if year else stamp.year
        scope_month = int(month) if month else stamp.month
        bank_extra = ""
        bank_params: list = []
        if bank:
            bank_extra = " AND bank = ?"
            bank_params.append(bank)

        rows = self.conn.execute(
            f"""
            SELECT
                COALESCE(transaction_time, created_at) AS stamp,
                amount,
                transaction_type,
                category,
                balance,
                bank
            FROM transactions
            WHERE amount IS NOT NULL
              AND COALESCE(transaction_time, created_at) IS NOT NULL
              {bank_extra}
            """,
            bank_params,
        ).fetchall()

        periods = self._dashboard_periods(None)
        period_set = set(periods)
        month_income = {p: 0.0 for p in periods}
        month_spend = {p: 0.0 for p in periods}
        category_totals: dict[str, float] = {}
        salary = 0.0
        transfers_in = 0.0
        spending = 0.0
        txn_count = 0
        latest_balance = None
        latest_balance_at = None
        latest_balance_bank = None
        latest_stamp = None

        for row in rows:
            local_day = self._local_date(row["stamp"], tz)
            if local_day is None:
                continue
            amount = float(row["amount"] or 0)
            ttype = row["transaction_type"] or ""

            if ttype == "salary":
                pay_y, pay_m = pay_month_for_salary(local_day)
                period = f"{pay_y:04d}-{pay_m:02d}"
                if period in period_set:
                    month_income[period] += amount
                if pay_y == scope_year and pay_m == scope_month:
                    salary += amount
                    txn_count += 1
            else:
                cal_y, cal_m = local_day.year, local_day.month
                period = f"{cal_y:04d}-{cal_m:02d}"
                if period in period_set:
                    if ttype == "bank_transfer_in":
                        month_income[period] += amount
                    elif ttype not in NON_SPENDING_TYPES:
                        month_spend[period] += amount
                if cal_y != scope_year or cal_m != scope_month:
                    continue
                txn_count += 1
                if ttype == "bank_transfer_in":
                    transfers_in += amount
                elif ttype not in NON_SPENDING_TYPES:
                    spending += amount
                    label = row["category"] or "Other"
                    category_totals[label] = category_totals.get(label, 0.0) + amount

            if row["balance"] is not None:
                stamp_row = str(row["stamp"])
                if latest_stamp is None or stamp_row > latest_stamp:
                    latest_stamp = stamp_row
                    latest_balance = float(row["balance"])
                    latest_balance_at = stamp_row
                    latest_balance_bank = row["bank"]

        income = salary + transfers_in
        by_category = [
            {"label": label, "total_amount": total}
            for label, total in sorted(
                category_totals.items(), key=lambda item: item[1], reverse=True
            )
        ]
        by_month = [
            {
                "period": period,
                "label": _month_label(period),
                "income": month_income[period],
                "spending": month_spend[period],
            }
            for period in periods
        ]
        rec = self.recurring_summary()
        return {
            "income": income,
            "spending": spending,
            "net": income - spending,
            "salary": salary,
            "transfers_in": transfers_in,
            "txn_count": txn_count,
            "latest_balance": latest_balance,
            "latest_balance_at": latest_balance_at,
            "latest_balance_bank": latest_balance_bank,
            "by_category": by_category,
            "by_month": by_month,
            "scope_period": f"{scope_year:04d}-{scope_month:02d}",
            "scope_label": f"{MONTH_LABELS[scope_month - 1]} {scope_year}",
            "month_days": self.month_day_series(
                year=str(scope_year),
                month=f"{scope_month:02d}",
                bank=bank,
                timezone_name=timezone_name,
                now=stamp,
            ),
            "recurring_monthly": rec["monthly_total"],
        }

    def month_day_series(
        self,
        year: str | None = None,
        month: str | None = None,
        bank: str | None = None,
        timezone_name: str = "Asia/Riyadh",
        now: datetime | None = None,
    ) -> dict:
        """Day-by-day income/spending from day 1 of the selected (or current) month.

        Salary uses a pay window: 5 days before month-start through day 5 of the month.
        Early salary (before the 1st) is shown on day 1.
        """
        import calendar
        from zoneinfo import ZoneInfo

        from collector.salary_period import salary_chart_day, salary_window

        tz = ZoneInfo(timezone_name)
        stamp = now.astimezone(tz) if now else datetime.now(tz)
        year_n = int(year) if year else stamp.year
        if month:
            month_n = int(month)
        elif year and int(year) == stamp.year:
            month_n = stamp.month
        elif year:
            month_n = 12
        else:
            month_n = stamp.month
        last_day = calendar.monthrange(year_n, month_n)[1]
        is_current = year_n == stamp.year and month_n == stamp.month
        through = stamp.day if is_current else last_day
        month_start = date(year_n, month_n, 1)
        month_end = date(year_n, month_n, last_day)
        sal_start, sal_end = salary_window(year_n, month_n)

        bank_extra = ""
        bank_params: list = []
        if bank:
            bank_extra = " AND bank = ?"
            bank_params.append(bank)

        # Non-salary rows in the calendar month (spending + other incoming transfers).
        cal_rows = self.conn.execute(
            f"""
            SELECT
                COALESCE(transaction_time, created_at) AS stamp,
                amount,
                transaction_type
            FROM transactions
            WHERE amount IS NOT NULL
              AND COALESCE(transaction_time, created_at) IS NOT NULL
              AND IFNULL(transaction_type, '') != 'salary'
              {bank_extra}
            """,
            bank_params,
        ).fetchall()
        day_income: dict[int, float] = {d: 0.0 for d in range(1, through + 1)}
        day_spend: dict[int, float] = {d: 0.0 for d in range(1, through + 1)}
        for row in cal_rows:
            local_day = self._local_date(row["stamp"], tz)
            if local_day is None or not (month_start <= local_day <= month_end):
                continue
            if local_day.day > through:
                continue
            amount = float(row["amount"] or 0)
            if row["transaction_type"] == "bank_transfer_in":
                day_income[local_day.day] += amount
            elif (row["transaction_type"] or "") not in NON_SPENDING_TYPES:
                day_spend[local_day.day] += amount

        # Salary in the pay window (may spill from the previous calendar month).
        salary_rows = self.conn.execute(
            f"""
            SELECT COALESCE(transaction_time, created_at) AS stamp, amount
            FROM transactions
            WHERE amount IS NOT NULL
              AND transaction_type = 'salary'
              AND COALESCE(transaction_time, created_at) IS NOT NULL
              {bank_extra}
            """,
            bank_params,
        ).fetchall()
        salary_total = 0.0
        for row in salary_rows:
            local_day = self._local_date(row["stamp"], tz)
            if local_day is None:
                continue
            chart_day = salary_chart_day(local_day, year_n, month_n)
            if chart_day is None or chart_day > through:
                continue
            amount = float(row["amount"] or 0)
            day_income[chart_day] += amount
            salary_total += amount

        days = []
        cum_in = 0.0
        cum_out = 0.0
        for day_n in range(1, through + 1):
            income = day_income.get(day_n, 0.0)
            spending = day_spend.get(day_n, 0.0)
            cum_in += income
            cum_out += spending
            days.append(
                {
                    "day": day_n,
                    "label": str(day_n),
                    "income": income,
                    "spending": spending,
                    "cumulative_income": cum_in,
                    "cumulative_spending": cum_out,
                }
            )
        return {
            "year": year_n,
            "month": month_n,
            "period": f"{year_n:04d}-{month_n:02d}",
            "label": f"{MONTH_LABELS[month_n - 1]} {year_n}",
            "through_day": through,
            "days_in_month": last_day,
            "income": cum_in,
            "spending": cum_out,
            "salary": salary_total,
            "salary_window_start": sal_start.isoformat(),
            "salary_window_end": sal_end.isoformat(),
            "days": days,
        }

    def _local_date(self, raw: object, tz) -> date | None:
        if not raw:
            return None
        when = datetime.fromisoformat(str(raw).replace(" ", "T"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.astimezone(tz).date()

    def _dashboard_periods(self, year: str | None) -> list[str]:
        if year:
            return [f"{year}-{month:02d}" for month in range(1, 13)]
        today = datetime.now(timezone.utc)
        year_n, month_n = today.year, today.month
        periods: list[str] = []
        for _ in range(12):
            periods.append(f"{year_n}-{month_n:02d}")
            month_n -= 1
            if month_n == 0:
                month_n = 12
                year_n -= 1
        periods.reverse()
        return periods

    def recurring_key(self, row: sqlite3.Row) -> str:
        merchant = (row["merchant"] or "").strip().upper()
        if merchant:
            return f"merchant:{merchant}"
        return f"id:{row['id']}"

    def _flag_if_known_recurring(self, txn_id: int, merchant: str | None) -> None:
        if not txn_id or not merchant:
            return
        key = f"merchant:{merchant.strip().upper()}"
        exists = self.conn.execute(
            """
            SELECT 1 FROM recurring_items
            WHERE item_key = ? AND IFNULL(source, 'transaction') = 'transaction'
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        if exists:
            self.conn.execute(
                "UPDATE transactions SET is_recurring = 1 WHERE id = ?",
                (txn_id,),
            )

    def mark_recurring(self, txn_id: int) -> dict | None:
        row = self.get_transaction(txn_id)
        if not row or row["amount"] is None:
            return None
        if (row["transaction_type"] or "") in NON_SPENDING_TYPES:
            return None
        key = self.recurring_key(row)
        label = (row["merchant"] or row["category"] or row["transaction_type"] or "Monthly bill").strip()
        amount = float(row["amount"])
        now = datetime.now(timezone.utc).isoformat(sep=" ")
        self.conn.execute(
            """
            INSERT INTO recurring_items (
                item_key, label, amount, currency, category, frequency, source,
                monthly_amount, source_transaction_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'monthly', 'transaction', ?, ?, ?)
            ON CONFLICT(item_key) DO UPDATE SET
                label = excluded.label,
                amount = excluded.amount,
                currency = excluded.currency,
                category = excluded.category,
                frequency = 'monthly',
                source = 'transaction',
                monthly_amount = excluded.monthly_amount,
                source_transaction_id = excluded.source_transaction_id,
                updated_at = excluded.updated_at
            """,
            (
                key,
                label,
                amount,
                row["currency"],
                row["category"],
                amount,
                txn_id,
                now,
            ),
        )
        merchant = (row["merchant"] or "").strip()
        if merchant:
            self.conn.execute(
                "UPDATE transactions SET is_recurring = 1 WHERE UPPER(IFNULL(merchant, '')) = ?",
                (merchant.upper(),),
            )
        else:
            self.conn.execute(
                "UPDATE transactions SET is_recurring = 1 WHERE id = ?",
                (txn_id,),
            )
        self.conn.commit()
        return self.recurring_summary()

    def add_manual_habit(
        self,
        label: str,
        amount: float,
        frequency: str = "daily",
        category: str | None = None,
        currency: str = "SAR",
    ) -> dict | None:
        label = (label or "").strip()
        frequency = (frequency or "daily").strip().lower()
        if not label or amount is None or amount <= 0:
            return None
        if frequency not in RECURRING_FREQUENCIES:
            return None
        key = f"manual:{label.casefold()}"
        monthly = monthly_from_frequency(amount, frequency)
        now = datetime.now(timezone.utc).isoformat(sep=" ")
        self.conn.execute(
            """
            INSERT INTO recurring_items (
                item_key, label, amount, currency, category, frequency, source,
                monthly_amount, source_transaction_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'manual', ?, NULL, ?)
            ON CONFLICT(item_key) DO UPDATE SET
                label = excluded.label,
                amount = excluded.amount,
                currency = excluded.currency,
                category = excluded.category,
                frequency = excluded.frequency,
                source = 'manual',
                monthly_amount = excluded.monthly_amount,
                source_transaction_id = NULL,
                updated_at = excluded.updated_at
            """,
            (
                key,
                label,
                float(amount),
                currency or "SAR",
                (category or "").strip() or None,
                frequency,
                monthly,
                now,
            ),
        )
        self.conn.commit()
        return self.recurring_summary()

    def unmark_recurring(self, txn_id: int) -> dict | None:
        row = self.get_transaction(txn_id)
        if not row:
            return None
        return self.delete_recurring_key(self.recurring_key(row))

    def delete_recurring_item(self, item_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT item_key FROM recurring_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        return self.delete_recurring_key(row["item_key"])

    def delete_recurring_key(self, key: str) -> dict:
        self.conn.execute("DELETE FROM recurring_items WHERE item_key = ?", (key,))
        if key.startswith("merchant:"):
            merchant = key.split(":", 1)[1]
            self.conn.execute(
                "UPDATE transactions SET is_recurring = 0 WHERE UPPER(IFNULL(merchant, '')) = ?",
                (merchant,),
            )
        elif key.startswith("id:"):
            self.conn.execute(
                "UPDATE transactions SET is_recurring = 0 WHERE id = ?",
                (int(key.split(":", 1)[1]),),
            )
        self.conn.commit()
        return self.recurring_summary()

    def recurring_summary(self) -> dict:
        items = self.conn.execute(
            """
            SELECT id, item_key, label, amount, currency, category, frequency, source,
                   monthly_amount, source_transaction_id, updated_at
            FROM recurring_items
            ORDER BY monthly_amount DESC, label
            """
        ).fetchall()
        public_items = []
        monthly = 0.0
        by_category: dict[str, float] = {}
        for row in items:
            amount = float(row["amount"] or 0)
            frequency = (row["frequency"] or "monthly").lower()
            monthly_amount = float(row["monthly_amount"] or 0)
            if monthly_amount <= 0:
                monthly_amount = monthly_from_frequency(amount, frequency)
            monthly += monthly_amount
            cat = row["category"] or "Other"
            by_category[cat] = by_category.get(cat, 0) + monthly_amount
            public_items.append(
                {
                    "id": row["id"],
                    "item_key": row["item_key"],
                    "label": row["label"],
                    "amount": amount,
                    "currency": row["currency"],
                    "category": row["category"],
                    "frequency": frequency,
                    "source": row["source"] or "transaction",
                    "monthly_amount": monthly_amount,
                    "source_transaction_id": row["source_transaction_id"],
                    "updated_at": row["updated_at"],
                }
            )
        return {
            "item_count": len(public_items),
            "monthly_total": monthly,
            "yearly_total": monthly * 12,
            "items": public_items,
            "by_category": [
                {"label": label, "total_amount": total}
                for label, total in sorted(by_category.items(), key=lambda item: item[1], reverse=True)
            ],
        }

    def notify_value(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM notify_state WHERE key = ?",
            (key,),
        ).fetchone()
        return row["value"] if row else None

    def set_notify_value(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat(sep=" ")
        self.conn.execute(
            """
            INSERT INTO notify_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        self.conn.commit()

    def day_spending_report(self, day: str) -> dict:
        from zoneinfo import ZoneInfo

        noon = datetime.fromisoformat(day).replace(hour=12, tzinfo=ZoneInfo("Asia/Riyadh"))
        report = self.period_spending_report("day", timezone_name="Asia/Riyadh", now=noon)
        report["day"] = day
        return report

    def period_spending_report(
        self,
        period: str,
        timezone_name: str = "Asia/Riyadh",
        now: datetime | None = None,
    ) -> dict:
        from zoneinfo import ZoneInfo

        period = (period or "day").strip().lower()
        if period not in {"day", "week", "month", "year"}:
            raise ValueError("period must be day, week, month, or year")
        tz = ZoneInfo(timezone_name)
        stamp = now.astimezone(tz) if now else datetime.now(tz)
        today = stamp.date()
        if period == "day":
            start = today
            end = today
            title = f"Day · {today.isoformat()}"
        elif period == "week":
            # Last 7 days ending today (never extends into future dates).
            end = today
            start = today.fromordinal(today.toordinal() - 6)
            title = f"Week · {start.isoformat()} → {end.isoformat()}"
        elif period == "month":
            start = today.replace(day=1)
            end = today
            title = f"Month · {start.isoformat()} → {end.isoformat()}"
        else:
            start = today.replace(month=1, day=1)
            end = today
            title = f"Year · {start.isoformat()} → {end.isoformat()}"

        spend_end = end

        rows = self.conn.execute(
            """
            SELECT amount, merchant, category, transaction_time, created_at, transaction_type
            FROM transactions
            WHERE amount IS NOT NULL
              AND IFNULL(transaction_type, '') NOT IN ('salary', 'bank_transfer_in', 'wallet_topup')
            """
        ).fetchall()
        matched = []
        for row in rows:
            raw = row["transaction_time"] or row["created_at"]
            if not raw:
                continue
            when = datetime.fromisoformat(str(raw).replace(" ", "T"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            local_day = when.astimezone(tz).date()
            if start <= local_day <= spend_end:
                matched.append(row)

        total = sum(float(row["amount"] or 0) for row in matched)
        by_merchant: dict[str, float] = {}
        by_category: dict[str, float] = {}
        for row in matched:
            merchant = (row["merchant"] or "").strip() or row["category"] or "Other"
            category = row["category"] or "Other"
            amount = float(row["amount"] or 0)
            by_merchant[merchant] = by_merchant.get(merchant, 0) + amount
            by_category[category] = by_category.get(category, 0) + amount

        def top(mapping: dict[str, float], limit: int = 5) -> list[dict]:
            return [
                {"label": label, "total_amount": amount}
                for label, amount in sorted(mapping.items(), key=lambda item: item[1], reverse=True)[:limit]
            ]

        return {
            "period": period,
            "title": title,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "spend_end": spend_end.isoformat(),
            "day": today.isoformat() if period == "day" else None,
            "total_amount": total,
            "txn_count": len(matched),
            "merchants": top(by_merchant),
            "categories": top(by_category),
        }




