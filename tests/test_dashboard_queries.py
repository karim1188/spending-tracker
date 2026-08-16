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


def test_year_filter_and_duplicates_and_sender_rule(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    when = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    for guid in ("g1", "g2", "g3"):
        db.insert_transaction(
            Transaction(
                source_message_guid=guid,
                bank="SNB",
                sender="SNB-AlAhli",
                transaction_type="card_purchase",
                amount=20,
                currency="SAR",
                merchant="HungerStation",
                category="Food & Dining",
                transaction_time=when,
            )
        )
    assert db.summary()["txn_count"] == 3
    assert db.purge_duplicates() == 2
    assert db.summary()["txn_count"] == 1
    assert db.list_transactions(year="2026", month="03")
    assert db.list_transactions(year="2025") == []
    db.upsert_sender_rule("SNB-AlAhli", category="Shopping")
    row = db.get_transaction(db.list_transactions()[0]["id"])
    assert row["category"] == "Shopping"
    assert db.sender_rule("SNB-AlAhli")["category"] == "Shopping"
    assert db.delete_transaction(row["id"]) is True
    db.close()
