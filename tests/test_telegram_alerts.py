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


def test_warning_sends_once_at_200(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    sent: list[str] = []
    settings = _settings()
    noon = datetime(2026, 8, 16, 12, 0, tzinfo=RIYADH)
    _spend(db, "a", 100)
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "b", 110)
    assert tick(db, settings=settings, send=sent.append, now=noon) == ["warning"]
    assert "200" in sent[0]
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    db.close()


def test_near_limit_sends_once_within_50(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    sent: list[str] = []
    settings = _settings()
    noon = datetime(2026, 8, 16, 12, 0, tzinfo=RIYADH)
    _spend(db, "near-a", 140)
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "near-b", 20)
    assert tick(db, settings=settings, send=sent.append, now=noon) == ["near_limit"]
    assert any(line in sent[0] for line in NEAR_LIMIT_LINES)
    assert "40.00" in sent[0]
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "near-c", 50)
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
    sent: list[str] = []
    result = send_period_report(db, "month", settings=_settings(), send=sent.append, now=now)
    assert result["ok"] is True
    assert "Month" in sent[0]
    assert "100.00" in sent[0]
    assert "CATEGORIES" in format_period_report(month)
    db.close()
