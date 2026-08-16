from __future__ import annotations

from datetime import datetime, timezone

from collector.imessage_reader import IMessageReader
from collector.macos_access import apple_timestamp_to_datetime
from collector.streamtyped import parse_streamtyped
from tests.helpers import create_mock_chat_db, make_streamtyped_blob, unix_to_apple


def test_reader_incoming_only_and_text(tmp_path):
    db_path = tmp_path / "chat.db"
    create_mock_chat_db(
        db_path,
        [
            {
                "id": 10,
                "guid": "g-in",
                "sender": "SNB",
                "text": "شراء بمبلغ 74.50 SAR من HungerStation بطاقة *1234",
                "service": "SMS",
            },
            {
                "id": 11,
                "guid": "g-out",
                "sender": "SNB",
                "text": "from me",
                "is_from_me": True,
            },
        ],
    )
    reader = IMessageReader(db_path=db_path, use_rust=False)
    messages = reader.get_messages(after_id=0, limit=50)
    assert [m.guid for m in messages] == ["g-in"]
    assert messages[0].sender == "SNB"
    assert messages[0].service == "SMS"
    assert messages[0].is_from_me is False
    assert "74.50" in messages[0].text


def test_reader_after_id_and_guid(tmp_path):
    db_path = tmp_path / "chat.db"
    create_mock_chat_db(
        db_path,
        [
            {"id": 1, "guid": "a", "sender": "SNB", "text": "one"},
            {"id": 2, "guid": "b", "sender": "SNB", "text": "two"},
            {"id": 3, "guid": "c", "sender": "AlRajhi", "text": "three"},
        ],
    )
    reader = IMessageReader(db_path=db_path, use_rust=False)
    messages = reader.get_messages(after_id=1, limit=10)
    assert [m.id for m in messages] == [2, 3]
    assert messages[0].guid == "b"


def test_reader_attributed_body_streamtyped(tmp_path):
    blob = make_streamtyped_blob("HungerStation 20.00 SAR")
    assert parse_streamtyped(blob) == "HungerStation 20.00 SAR"
    db_path = tmp_path / "chat.db"
    create_mock_chat_db(
        db_path,
        [
            {
                "id": 40,
                "guid": "attr-1",
                "sender": "SNB",
                "text": None,
                "attributed_body": blob,
            }
        ],
    )
    reader = IMessageReader(db_path=db_path, use_rust=False)
    messages = reader.get_messages(after_id=0, limit=5)
    assert messages[0].text == "HungerStation 20.00 SAR"


def test_reader_is_read_only(tmp_path):
    db_path = tmp_path / "chat.db"
    create_mock_chat_db(db_path, [{"id": 1, "guid": "x", "sender": "SNB", "text": "hi"}])
    reader = IMessageReader(db_path=db_path, use_rust=False)
    access = reader.test_access()
    assert access.ok
    assert access.read_only
    conn = reader._connect_readonly()
    try:
        try:
            conn.execute("INSERT INTO message (guid) VALUES ('nope')")
            conn.commit()
            raised = False
        except Exception:
            raised = True
        assert raised
    finally:
        conn.close()


def test_list_senders_counts_incoming_only(tmp_path):
    db_path = tmp_path / "chat.db"
    create_mock_chat_db(
        db_path,
        [
            {"id": 1, "guid": "a", "sender": "SNB", "text": "one"},
            {"id": 2, "guid": "b", "sender": "SNB", "text": "two"},
            {"id": 3, "guid": "c", "sender": "Amazon", "text": "ad"},
            {"id": 4, "guid": "d", "sender": "SNB", "text": "from me", "is_from_me": True},
        ],
    )
    reader = IMessageReader(db_path=db_path, use_rust=False)
    senders = reader.list_senders()
    assert senders[0] == ("SNB", 2)
    assert senders[1] == ("Amazon", 1)


def test_apple_timestamp_conversion():
    dt = datetime(2022, 5, 17, 17, 29, 42, tzinfo=timezone.utc)
    apple = unix_to_apple(dt)
    converted = apple_timestamp_to_datetime(apple)
    assert converted.replace(microsecond=0) == dt
