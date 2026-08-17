from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from database.db import SpendingDatabase
from models.transaction import Transaction
from notify.alerts import (
    NEAR_LIMIT_LINES,
    format_near_limit,
    format_period_report,
    send_period_report,
    tick,
)
from notify.settings import TelegramSettings


RIYADH = ZoneInfo("Asia/Riyadh")


def _settings() -> TelegramSettings:
    return TelegramSettings(
        api_id=1,
        api_hash="hash",
        phone="+10000000000",
        chat="me",
        timezone="Asia/Riyadh",
        daily_hour=21,
        daily_minute=0,
        daily_limit_sar=200,
        near_limit_sar=50,
        monthly_limit_sar=6000,
    )


def _spend(db: SpendingDatabase, guid: str, amount: float, when: datetime | None = None) -> None:
    db.insert_transaction(
        Transaction(
            source_message_guid=guid,
            bank="SNB",
            sender="SNB-AlAhli",
            transaction_type="card_purchase",
            amount=amount,
            currency="SAR",
            merchant="HungerStation",
            category="Food & Dining",
            transaction_time=when or datetime(2026, 8, 16, 9, 0, tzinfo=ZoneInfo("UTC")),
        )
    )


def test_warning_sends_once_at_daily_allowance(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    sent: list[str] = []
    settings = _settings()
    noon = datetime(2026, 8, 1, 12, 0, tzinfo=RIYADH)
    when = datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
    _spend(db, "a", 100, when=when)
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "b", 110, when=when)
    assert tick(db, settings=settings, send=sent.append, now=noon) == ["warning"]
    assert "210.00" in sent[0]
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    db.close()


def test_warning_uses_rollover_on_later_days(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    sent: list[str] = []
    settings = _settings()
    _spend(db, "d1", 150, when=datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("UTC")))
    noon = datetime(2026, 8, 2, 12, 0, tzinfo=RIYADH)
    when = datetime(2026, 8, 2, 9, 0, tzinfo=ZoneInfo("UTC"))
    _spend(db, "d2a", 140, when=when)
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "d2b", 120, when=when)
    assert tick(db, settings=settings, send=sent.append, now=noon) == ["warning"]
    db.close()


def test_near_limit_sends_once_within_50(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    sent: list[str] = []
    settings = _settings()
    noon = datetime(2026, 8, 1, 12, 0, tzinfo=RIYADH)
    when = datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
    _spend(db, "near-a", 140, when=when)
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "near-b", 20, when=when)
    assert tick(db, settings=settings, send=sent.append, now=noon) == ["near_limit"]
    assert any(line in sent[0] for line in NEAR_LIMIT_LINES)
    assert "40.00" in sent[0]
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "near-c", 50, when=when)
    assert tick(db, settings=settings, send=sent.append, now=noon) == ["warning"]
    db.close()


def test_near_limit_lines_are_funny_and_include_remaining():
    report = {"total_amount": 165.0, "txn_count": 3, "day": "2026-08-16"}
    text = format_near_limit(report, limit=200, cushion=50, line=NEAR_LIMIT_LINES[0])
    assert NEAR_LIMIT_LINES[0] in text
    assert "35.00" in text
    assert len(NEAR_LIMIT_LINES) >= 5


def test_daily_digest_sends_after_nine(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    sent: list[str] = []
    settings = _settings()
    _spend(db, "c", 80)
    before = datetime(2026, 8, 16, 20, 59, tzinfo=RIYADH)
    assert tick(db, settings=settings, send=sent.append, now=before) == []
    after = datetime(2026, 8, 16, 21, 0, tzinfo=RIYADH)
    assert tick(db, settings=settings, send=sent.append, now=after) == ["digest"]
    assert "80.00" in sent[0]
    assert tick(db, settings=settings, send=sent.append, now=after) == []
    db.close()


def test_period_reports_day_week_month_year(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    now = datetime(2026, 8, 16, 12, 0, tzinfo=RIYADH)
    _spend(db, "today", 50, datetime(2026, 8, 16, 8, 0, tzinfo=ZoneInfo("UTC")))
    _spend(db, "earlier-week", 30, datetime(2026, 8, 12, 8, 0, tzinfo=ZoneInfo("UTC")))
    _spend(db, "earlier-month", 20, datetime(2026, 8, 2, 8, 0, tzinfo=ZoneInfo("UTC")))
    _spend(db, "earlier-year", 10, datetime(2026, 1, 5, 8, 0, tzinfo=ZoneInfo("UTC")))
    day = db.period_spending_report("day", now=now)
    week = db.period_spending_report("week", now=now)
    month = db.period_spending_report("month", now=now)
    year = db.period_spending_report("year", now=now)
    assert day["total_amount"] == 50
    assert week["total_amount"] == 80
    assert month["total_amount"] == 100
    assert year["total_amount"] == 110
    assert week["start"] == "2026-08-10"
    assert week["end"] == "2026-08-16"
    assert "2026-08-10 → 2026-08-16" in week["title"]
    sent: list[str] = []
    result = send_period_report(db, "month", settings=_settings(), send=sent.append, now=now)
    assert result["ok"] is True
    assert "Month" in sent[0]
    assert "100.00" in sent[0]
    assert "CATEGORIES" in format_period_report(month)
    db.close()


def test_monthly_spending_warning_at_6000(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    sent: list[str] = []
    settings = _settings()
    noon = datetime(2026, 8, 16, 12, 0, tzinfo=RIYADH)
    _spend(db, "m1", 3000, datetime(2026, 8, 2, 8, 0, tzinfo=ZoneInfo("UTC")))
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "m2", 3500, datetime(2026, 8, 10, 8, 0, tzinfo=ZoneInfo("UTC")))
    assert tick(db, settings=settings, send=sent.append, now=noon) == ["monthly_warning"]
    assert "MONTHLY ALERT" in sent[0] or "Monthly alert" in sent[0] or "6000" in sent[0]
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    db.close()


def test_format_monthly1_report_includes_day_rows():
    from collector.daily_budget import enrich_month_days
    from notify.alerts import format_monthly1_report

    series = enrich_month_days(
        {
            "label": "Aug 2026",
            "through_day": 3,
            "days_in_month": 31,
            "income": 1000,
            "spending": 250,
            "days": [
                {"day": 1, "income": 1000, "spending": 0, "cumulative_spending": 0},
                {"day": 2, "income": 0, "spending": 100, "cumulative_spending": 100},
                {"day": 3, "income": 0, "spending": 150, "cumulative_spending": 250},
            ],
        },
        200,
    )
    text = format_monthly1_report(series, 6000)
    assert "MONTHLY1" in text
    assert "D02" in text
    assert "250.00" in text
    assert "roll" in text.lower()
    assert "6,000" in text or "6000" in text


def test_week_report_looks_back_seven_days(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    monday = datetime(2026, 8, 17, 12, 0, tzinfo=RIYADH)
    _spend(db, "mon", 40, datetime(2026, 8, 17, 8, 0, tzinfo=ZoneInfo("UTC")))
    _spend(db, "sun", 25, datetime(2026, 8, 16, 8, 0, tzinfo=ZoneInfo("UTC")))
    _spend(db, "old", 15, datetime(2026, 8, 10, 8, 0, tzinfo=ZoneInfo("UTC")))
    _spend(db, "too-old", 99, datetime(2026, 8, 9, 8, 0, tzinfo=ZoneInfo("UTC")))
    week = db.period_spending_report("week", now=monday)
    assert week["start"] == "2026-08-11"
    assert week["end"] == "2026-08-17"
    assert week["start"] < week["end"]
    assert week["total_amount"] == 65
    assert "2026-08-11 → 2026-08-17" in week["title"]
    db.close()
