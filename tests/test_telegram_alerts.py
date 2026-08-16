from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from database.db import SpendingDatabase
from models.transaction import Transaction
from notify.alerts import tick
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
    )


def _spend(db: SpendingDatabase, guid: str, amount: float) -> None:
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
            transaction_time=datetime(2026, 8, 16, 9, 0, tzinfo=ZoneInfo("UTC")),
        )
    )


def test_warning_sends_once_at_200(tmp_path):
    db = SpendingDatabase(tmp_path / "spending.db")
    sent: list[str] = []
    settings = _settings()
    noon = datetime(2026, 8, 16, 12, 0, tzinfo=RIYADH)
    _spend(db, "a", 150)
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    _spend(db, "b", 60)
    assert tick(db, settings=settings, send=sent.append, now=noon) == ["warning"]
    assert "200" in sent[0]
    assert tick(db, settings=settings, send=sent.append, now=noon) == []
    db.close()


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
