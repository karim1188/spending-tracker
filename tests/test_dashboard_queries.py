from __future__ import annotations

from database.db import SpendingDatabase
from models.transaction import Transaction
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


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
    db.insert_transaction(
        Transaction(
            source_message_guid="topup",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="bank_transfer_out",
            amount=200,
            currency="SAR",
            merchant="Mobily Pay",
            category="Transfers",
            raw_message="تحويل إلى Mobily Pay بمبلغ 200.00 SAR",
            transaction_time=when,
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="mobily-buy",
            bank="MobilyPay",
            sender="Mobily Pay",
            transaction_type="card_purchase",
            amount=32,
            currency="SAR",
            merchant="HungerStation",
            category="Food & Dining",
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
    topup = db.conn.execute(
        "SELECT transaction_type FROM transactions WHERE source_message_guid = 'topup'"
    ).fetchone()
    assert topup["transaction_type"] == "wallet_topup"
    summary = db.summary()
    assert summary["total_amount"] == 112
    assert summary["txn_count"] == 2
    assert db.summary(transaction_type="salary")["total_amount"] == 10000
    assert len(db.list_transactions()) == 5
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


def test_manual_daily_habit_does_not_tag_transactions(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    when = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    db.insert_transaction(
        Transaction(
            source_message_guid="food",
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="card_purchase",
            amount=40,
            currency="SAR",
            merchant="HungerStation",
            category="Food & Dining",
            transaction_time=when,
        )
    )
    summary = db.add_manual_habit("Cigarettes", 25, frequency="daily", category="Other")
    assert summary["monthly_total"] == 750
    assert summary["yearly_total"] == 750 * 12
    item = summary["items"][0]
    assert item["source"] == "manual"
    assert item["frequency"] == "daily"
    assert item["amount"] == 25
    assert item["monthly_amount"] == 750
    assert db.list_transactions()[0]["is_recurring"] in (0, False)
    summary = db.mark_recurring(db.list_transactions()[0]["id"])
    assert summary["monthly_total"] == 790
    assert any(row["source"] == "transaction" for row in summary["items"])
    assert db.add_manual_habit("", 25, frequency="daily") is None
    db.close()


def test_dashboard_income_versus_spending(tmp_path):
    from zoneinfo import ZoneInfo

    db = SpendingDatabase(tmp_path / "spending.db")
    when = datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 10, 12, tzinfo=ZoneInfo("Asia/Riyadh"))
    db.insert_transaction(
        Transaction(
            source_message_guid="sal-d",
            bank="SNB",
            transaction_type="salary",
            amount=12000,
            currency="SAR",
            category="Salary",
            balance=18500,
            transaction_time=when,
            raw_message="حوالة واردة راتب مبلغ SAR 12000",
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="in-d",
            bank="SNB",
            transaction_type="bank_transfer_in",
            amount=400,
            currency="SAR",
            category="Transfers",
            transaction_time=when,
            raw_message="حوالة واردة مبلغ SAR 400",
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="out-d",
            bank="SNB",
            transaction_type="card_purchase",
            amount=250,
            currency="SAR",
            merchant="HungerStation",
            category="Food & Dining",
            transaction_time=when,
        )
    )
    dash = db.dashboard(now=now)
    assert dash["income"] == 12400
    assert dash["salary"] == 12000
    assert dash["transfers_in"] == 400
    assert dash["spending"] == 250
    assert dash["net"] == 12150
    assert dash["latest_balance"] == 18500
    assert dash["scope_period"] == "2026-08"
    year_dash = db.dashboard(year="2026", now=now)
    august = next(row for row in year_dash["by_month"] if row["period"] == "2026-08")
    assert august["income"] == 12400
    assert august["spending"] == 250
    assert db.dashboard(year="2025", now=now)["income"] == 0
    series = db.month_day_series(year="2026", month="08", now=now)
    assert series["period"] == "2026-08"
    assert series["through_day"] == 10
    assert series["days"][0]["day"] == 1
    assert series["days"][1]["income"] == 12400
    assert series["days"][1]["spending"] == 250
    assert series["days"][1]["cumulative_spending"] == 250
    assert series["spending"] == 250
    db.close()


def test_salary_pay_window_across_month_boundary(tmp_path):
    """Salary in the last 5 days before the 1st counts for the next month."""
    from zoneinfo import ZoneInfo

    db = SpendingDatabase(tmp_path / "spending.db")
    db.insert_transaction(
        Transaction(
            source_message_guid="sal-early",
            bank="SNB",
            transaction_type="salary",
            amount=11000,
            currency="SAR",
            category="Salary",
            transaction_time=datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc),
            raw_message="حوالة واردة راتب مبلغ SAR 11000",
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="sal-late",
            bank="SNB",
            transaction_type="salary",
            amount=500,
            currency="SAR",
            category="Salary",
            transaction_time=datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc),
            raw_message="راتب مبلغ SAR 500",
        )
    )
    now = datetime(2026, 8, 10, 12, tzinfo=ZoneInfo("Asia/Riyadh"))
    series = db.month_day_series(year="2026", month="08", now=now)
    assert series["salary"] == 11500
    assert series["days"][0]["income"] == 11000  # early salary on day 1
    assert series["days"][2]["income"] == 500  # Aug 3
    july = db.month_day_series(
        year="2026",
        month="07",
        now=datetime(2026, 7, 31, 12, tzinfo=ZoneInfo("Asia/Riyadh")),
    )
    assert july["salary"] == 0
    dash_aug = db.dashboard(year="2026", month="08", now=now)
    assert dash_aug["salary"] == 11500
    dash_year = db.dashboard(year="2026", now=now)
    august = next(row for row in dash_year["by_month"] if row["period"] == "2026-08")
    july_row = next(row for row in dash_year["by_month"] if row["period"] == "2026-07")
    assert august["income"] == 11500
    assert july_row["income"] == 0
    db.close()


def test_month_day_series_starts_at_day_one(tmp_path):
    from zoneinfo import ZoneInfo

    db = SpendingDatabase(tmp_path / "spending.db")
    db.insert_transaction(
        Transaction(
            source_message_guid="d1",
            bank="SNB",
            transaction_type="card_purchase",
            amount=100,
            currency="SAR",
            merchant="A",
            category="Food & Dining",
            transaction_time=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        )
    )
    db.insert_transaction(
        Transaction(
            source_message_guid="d5",
            bank="SNB",
            transaction_type="card_purchase",
            amount=200,
            currency="SAR",
            merchant="B",
            category="Food & Dining",
            transaction_time=datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc),
        )
    )
    series = db.month_day_series(
        year="2026",
        month="08",
        now=datetime(2026, 8, 5, 12, tzinfo=ZoneInfo("Asia/Riyadh")),
    )
    assert [row["day"] for row in series["days"]] == [1, 2, 3, 4, 5]
    assert series["days"][0]["spending"] == 100
    assert series["days"][4]["cumulative_spending"] == 300
    db.close()
