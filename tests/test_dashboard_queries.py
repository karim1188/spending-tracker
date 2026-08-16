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


def test_year_filter_and_duplicates_and_merchant_rule(tmp_path):
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
    db.upsert_merchant_rule("HungerStation", "Shopping", apply_existing=True)
    row = db.get_transaction(db.list_transactions()[0]["id"])
    assert row["category"] == "Shopping"
    assert db.delete_transaction(row["id"]) is True
    db.close()


def test_salary_and_incoming_transfer_excluded_from_spending(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    when = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    db.insert_transaction(
        Transaction(
            source_message_guid="pay",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="card_purchase",
            amount=80,
            currency="SAR",
            merchant="HungerStation",
            category="Food & Dining",
            transaction_time=when,
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="salary",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="bank_transfer_in",
            amount=10000,
            currency="SAR",
            category="Transfers",
            raw_message="حوالة واردة راتب\nمبلغ SAR 10000",
            transaction_time=when,
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="in",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="bank_transfer_in",
            amount=500,
            currency="SAR",
            category="Transfers",
            raw_message="حوالة واردة مبلغ SAR 500",
            transaction_time=when,
        )
    )
    db.close()
    db = SpendingDatabase(tmp_path / "spending.db")
    salary = db.conn.execute(
        "SELECT transaction_type, category FROM transactions WHERE source_message_guid = 'salary'"
    ).fetchone()
    assert salary["transaction_type"] == "salary"
    assert salary["category"] == "Salary"
    summary = db.summary()
    assert summary["total_amount"] == 80
    assert summary["txn_count"] == 1
    assert db.summary(transaction_type="salary")["total_amount"] == 10000
    assert len(db.list_transactions()) == 3
    db.close()


def test_activation_pin_guid_is_removed_on_init(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    db.insert_transaction(
        Transaction(
            source_message_guid="781A1E6A-0B82-B291-7EEB-ED6DDC8E2788",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="unknown",
            amount=1000,
            currency="SAR",
            raw_message="لا تشارك رمز التفعيل 1093\nتحويل لبنك محلي\nمبلغ SAR 1000",
        )
    )
    db.close()
    db = SpendingDatabase(tmp_path / "spending.db")
    assert db.is_excluded("781A1E6A-0B82-B291-7EEB-ED6DDC8E2788")
    assert db.list_transactions() == []
    db.close()


def test_recurring_monthly_bills_do_not_double_count(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    when = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    db.insert_transaction(
        Transaction(
            source_message_guid="net1",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="card_purchase",
            amount=45,
            currency="SAR",
            merchant="Netflix",
            category="Subscriptions",
            transaction_time=when,
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="net2",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="card_purchase",
            amount=45,
            currency="SAR",
            merchant="Netflix",
            category="Subscriptions",
            transaction_time=when,
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="stc",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="bill_payment",
            amount=120,
            currency="SAR",
            merchant="STC",
            category="Bills & Utilities",
            transaction_time=when,
        )
    )
    netflix_id = db.list_transactions(query="Netflix")[0]["id"]
    stc_id = db.list_transactions(query="STC")[0]["id"]
    summary = db.mark_recurring(netflix_id)
    assert summary["monthly_total"] == 45
    summary = db.mark_recurring(stc_id)
    assert summary["monthly_total"] == 165
    assert summary["yearly_total"] == 165 * 12
    assert summary["item_count"] == 2
    assert db.summary()["recurring_monthly"] == 165
    flagged = [row["is_recurring"] for row in db.list_transactions() if row["merchant"] == "Netflix"]
    assert flagged == [1, 1]
    db.unmark_recurring(netflix_id)
    assert db.recurring_summary()["monthly_total"] == 120
    salary_id = None
    db.insert_transaction(
        Transaction(
            source_message_guid="sal",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="salary",
            amount=10000,
            currency="SAR",
            category="Salary",
            transaction_time=when,
        )
    )
    salary_id = db.conn.execute(
        "SELECT id FROM transactions WHERE source_message_guid = 'sal'"
    ).fetchone()["id"]
    assert db.mark_recurring(salary_id) is None
    db.close()
