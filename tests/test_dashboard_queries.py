from __future__ import annotations

from database.db import SpendingDatabase
from models.transaction import Transaction
from datetime import datetime, timezone


def test_summary_and_list_transactions(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    assert db.summary()["txn_count"] == 0
    db.insert_transaction(
        Transaction(
            source_message_guid="g1",
            bank="SNB",
            transaction_type="card_purchase",
            amount=74.5,
            currency="SAR",
            merchant="HungerStation",
            category="Food & Dining",
            transaction_time=datetime.now(timezone.utc),
        )
    )
    summary = db.summary()
    assert summary["txn_count"] == 1
    assert summary["total_amount"] == 74.5
    assert summary["by_category"][0]["label"] == "Food & Dining"
    rows = db.list_transactions(bank="SNB")
    assert len(rows) == 1
    assert "raw_message" not in rows[0].keys()
    db.close()
