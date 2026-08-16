from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.project_paths import SPENDING_DB_PATH
from database.db import SpendingDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description="Show recently stored spending transactions")
    parser.add_argument("--spending-db", type=Path, default=SPENDING_DB_PATH)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    with SpendingDatabase(args.spending_db) as db:
        rows = db.recent_transactions(limit=args.limit)
    if not rows:
        print("No transactions stored yet.")
        return 0
    print(f"{'id':<6} {'bank':<10} {'type':<18} {'amount':>10} {'ccy':<4} {'merchant':<20} {'guid'}")
    for row in rows:
        amount = f"{row['amount']:.2f}" if row["amount"] is not None else "-"
        merchant = (row["merchant"] or "-")[:20]
        guid = (row["source_message_guid"] or "")[:12]
        print(
            f"{row['id']:<6} {(row['bank'] or '-'):<10} {(row['transaction_type'] or '-'):<18} "
            f"{amount:>10} {(row['currency'] or '-'):<4} {merchant:<20} {guid}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
