from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
import imaplib

import pytest

from collector.gmail_reader import (
    GmailConfigError,
    GmailReader,
    find_all_mail_mailbox,
    load_gmail_config,
    mask_email,
    parse_imap_list_line,
)


def test_mask_email_hides_local_part():
    assert "@" in mask_email("SNB Alerts <alerts@snb.com.sa>")
    assert "alerts@snb.com.sa" not in mask_email("alerts@snb.com.sa")


def test_load_gmail_config_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    cfg_path = tmp_path / "gmail.json"
    cfg_path.write_text(
        '{"email":"test@gmail.com","app_password":"abcd-efgh-ijkl-mnop"}',
        encoding="utf-8",
    )
    cfg = load_gmail_config(cfg_path)
    assert cfg["email"] == "test@gmail.com"
    assert cfg["imap_host"] == "imap.gmail.com"


def test_load_gmail_config_rejects_icloud_host(tmp_path, monkeypatch):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    cfg_path = tmp_path / "gmail.json"
    cfg_path.write_text(
        '{"email":"x@icloud.com","app_password":"secret","imap_host":"imap.mail.me.com"}',
        encoding="utf-8",
    )
    with pytest.raises(GmailConfigError, match="iCloud"):
        load_gmail_config(cfg_path)


def test_gmail_reader_refuses_icloud_host():
    with pytest.raises(GmailConfigError, match="iCloud"):
        GmailReader("x@gmail.com", "secret", imap_host="imap.mail.me.com")


class FakeImapClient:
    def __init__(self):
        self.selected = None
        self.logged_out = False

    def login(self, user, password):
        if password == "bad":
            raise imaplib.IMAP4.error("Invalid credentials")

    def list(self, directory='""', pattern="*"):
        return "OK", [b'(\\HasNoChildren) "/" INBOX']

    def select(self, mailbox, readonly=False):
        self.selected = mailbox
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        return "OK", [b"1 2"]

    def fetch(self, uid, query):
        msg = EmailMessage()
        msg["From"] = "SNB <alerts@snb.com.sa>"
        msg["Subject"] = "Card purchase"
        msg["Date"] = "Mon, 18 Aug 2026 10:00:00 +0000"
        msg.set_content("Purchase SAR 50.00 at HungerStation")
        payload = msg.as_bytes()
        meta = f"1 (FLAGS (\\Seen) BODY[] {{{len(payload)}}}".encode("ascii")
        return "OK", [(meta, payload)]

    def close(self):
        return "OK", [b""]

    def logout(self):
        self.logged_out = True
        return "BYE", [b""]


def test_gmail_reader_test_access_ok(monkeypatch):
    fake = FakeImapClient()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port: fake)
    reader = GmailReader("you@gmail.com", "good")
    result = reader.test_access()
    assert result.ok is True
    assert result.unread_count == 2


def test_gmail_reader_list_messages(monkeypatch):
    fake = FakeImapClient()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port: fake)
    reader = GmailReader("you@gmail.com", "good")
    with reader:
        rows = reader.list_messages(limit=5, from_pattern="snb")
    assert len(rows) == 2
    assert rows[0].subject == "Card purchase"
    assert rows[0].date == datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)


def test_parse_imap_list_finds_all_mail():
    parsed = parse_imap_list_line(b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"')
    assert parsed is not None
    flags, name = parsed
    assert "\\All" in flags.split()
    assert name == "[Gmail]/All Mail"


class FakeListClient:
    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" INBOX',
            b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
        ]


def test_find_all_mail_mailbox():
    assert find_all_mail_mailbox(FakeListClient()) == "[Gmail]/All Mail"
