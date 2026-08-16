from __future__ import annotations

from datetime import datetime, timezone

from collector.imessage_reader import IMessageReader
from collector.message_collector import MessageCollector
from database.db import SpendingDatabase
from tests.helpers import create_mock_chat_db, make_bank_registry


SNB_TEXT = "شراء بمبلغ 74.50 SAR من HungerStation بطاقة *1234"


def _collector(tmp_path, rows, senders=("SNB",)):
    chat = tmp_path / "chat.db"
    create_mock_chat_db(chat, rows)
    spending = SpendingDatabase(tmp_path / "spending.db")
    reader = IMessageReader(db_path=chat, use_rust=False)
    registry = make_bank_registry(SNB=senders)
    collector = MessageCollector(db=spending, reader=reader, registry=registry)
    return collector, spending


def test_duplicate_guid_not_inserted_twice(tmp_path):
    rows = [
        {"id": 84024, "guid": "same-guid", "sender": "SNB", "text": SNB_TEXT},
    ]
    collector, spending = _collector(tmp_path, rows)
    first = collector.sync_once(limit=10)
    assert first.stored == 1
    collector.checkpoint.reset()
    second = collector.sync_once(limit=10)
    assert second.stored == 0
    assert second.skipped_duplicate == 1
    count = spending.conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    assert count == 1
    spending.close()


def test_checkpoint_advances_and_recovers(tmp_path):
    rows = [
        {"id": 10, "guid": "g10", "sender": "Amazon", "text": "Your order"},
        {"id": 11, "guid": "g11", "sender": "SNB", "text": SNB_TEXT},
        {"id": 12, "guid": "g12", "sender": "HungerStation", "text": "hello"},
    ]
    collector, spending = _collector(tmp_path, rows)
    stats = collector.sync_once(limit=50)
    assert stats.last_message_id == 12
    assert spending.get_checkpoint() == 12
    assert stats.stored == 1
    assert stats.ignored_non_bank == 2
    third_pass = collector.sync_once(limit=50)
    assert third_pass.scanned == 0
    spending.close()


def test_sender_filtering_ignores_non_bank(tmp_path):
    rows = [
        {"id": 1, "guid": "amz", "sender": "Amazon", "text": "شراء بمبلغ 10.00 SAR من Amazon بطاقة *0000"},
        {"id": 2, "guid": "snb", "sender": "SNB", "text": SNB_TEXT},
    ]
    collector, spending = _collector(tmp_path, rows)
    stats = collector.sync_once()
    assert stats.ignored_non_bank == 1
    assert stats.stored == 1
    banks = [row["bank"] for row in spending.recent_transactions()]
    assert banks == ["SNB"]
    spending.close()


def test_empty_bank_senders_imports_nothing(tmp_path):
    rows = [{"id": 1, "guid": "snb", "sender": "SNB", "text": SNB_TEXT}]
    collector, spending = _collector(tmp_path, rows, senders=())
    stats = collector.sync_once()
    assert stats.stored == 0
    assert stats.ignored_non_bank == 1
    spending.close()


def test_malformed_bank_message_not_stored(tmp_path):
    rows = [{"id": 5, "guid": "otp", "sender": "SNB", "text": "رمز التحقق 123456"}]
    collector, spending = _collector(tmp_path, rows)
    stats = collector.sync_once()
    assert stats.stored == 0
    assert stats.unknown == 1
    assert spending.recent_transactions() == []
    spending.close()


def test_transaction_time_preserved(tmp_path):
    when = datetime(2026, 3, 1, 9, 30, tzinfo=timezone.utc)
    from tests.helpers import unix_to_apple

    rows = [
        {
            "id": 9,
            "guid": "timed",
            "sender": "SNB",
            "text": SNB_TEXT,
            "date": unix_to_apple(when),
        }
    ]
    collector, spending = _collector(tmp_path, rows)
    collector.sync_once()
    row = spending.recent_transactions()[0]
    assert "2026-03-01" in row["transaction_time"]
    spending.close()
