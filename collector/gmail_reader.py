from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
import imaplib
import json
import os
import re
from pathlib import Path
from typing import Iterable

from collector.project_paths import GMAIL_CONFIG_PATH

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993
ICLOUD_HOSTS = frozenset({"imap.mail.me.com", "imap.mail.icloud.com"})


class GmailConfigError(Exception):
    """Missing or invalid Gmail configuration."""


@dataclass(frozen=True)
class GmailAccessResult:
    ok: bool
    message: str
    email: str | None = None
    unread_count: int | None = None


@dataclass(frozen=True)
class GmailMessage:
    uid: str
    from_addr: str
    subject: str
    date: datetime | None
    snippet: str
    unread: bool


def load_gmail_config(path: Path | None = None) -> dict:
    cfg_path = path or GMAIL_CONFIG_PATH
    if cfg_path.is_file():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        data = {}
    email = os.environ.get("GMAIL_USER") or data.get("email") or data.get("user")
    password = os.environ.get("GMAIL_APP_PASSWORD") or data.get("app_password")
    if not email or not password:
        raise GmailConfigError(
            "Gmail credentials missing. Copy config/gmail.example.json to "
            "config/gmail.json (or set GMAIL_USER and GMAIL_APP_PASSWORD). "
            "Use a Gmail App Password — not your normal login password."
        )
    host = (os.environ.get("GMAIL_IMAP_HOST") or data.get("imap_host") or GMAIL_IMAP_HOST).strip()
    if host.lower() in ICLOUD_HOSTS:
        raise GmailConfigError(
            f"Refusing iCloud host {host!r}. This tool only checks Gmail (imap.gmail.com)."
        )
    return {
        "email": str(email).strip(),
        "app_password": str(password).strip(),
        "imap_host": host,
        "mailbox": str(data.get("mailbox") or "INBOX").strip() or "INBOX",
    }


def mask_email(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "(empty)"
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    if not match:
        return text[:48]
    addr = match.group(0)
    local, _, domain = addr.partition("@")
    if len(local) <= 2:
        masked_local = local[:1] + "***"
    else:
        masked_local = local[:2] + "***" + local[-1:]
    return text.replace(addr, f"{masked_local}@{domain}")


def _decode_header_value(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except (UnicodeError, ValueError, TypeError):
        return raw


def _message_snippet(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() != "text/plain":
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except LookupError:
                text = payload.decode("utf-8", errors="replace")
            return " ".join(text.split())[:240]
        return ""
    payload = msg.get_payload(decode=True)
    if not payload:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    try:
        text = payload.decode(charset, errors="replace")
    except LookupError:
        text = payload.decode("utf-8", errors="replace")
    return " ".join(text.split())[:240]


def _parse_message_date(msg) -> datetime | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


class GmailReader:
    """Read-only Gmail inbox checker via IMAP (Gmail only — not iCloud)."""

    def __init__(
        self,
        email: str,
        app_password: str,
        *,
        imap_host: str = GMAIL_IMAP_HOST,
        mailbox: str = "INBOX",
    ):
        if imap_host.lower() in ICLOUD_HOSTS:
            raise GmailConfigError(
                f"Refusing iCloud host {imap_host!r}. Use Gmail IMAP (imap.gmail.com)."
            )
        self.email = email.strip()
        self.app_password = app_password.strip()
        self.imap_host = imap_host.strip()
        self.mailbox = mailbox.strip() or "INBOX"
        self._client: imaplib.IMAP4_SSL | None = None

    @classmethod
    def from_config(cls, path: Path | None = None) -> GmailReader:
        cfg = load_gmail_config(path)
        return cls(
            email=cfg["email"],
            app_password=cfg["app_password"],
            imap_host=cfg["imap_host"],
            mailbox=cfg["mailbox"],
        )

    def connect(self) -> None:
        if self._client is not None:
            return
        client = imaplib.IMAP4_SSL(self.imap_host, GMAIL_IMAP_PORT)
        client.login(self.email, self.app_password)
        status, _ = client.select(self.mailbox, readonly=True)
        if status != "OK":
            client.logout()
            raise GmailConfigError(f"Could not open mailbox {self.mailbox!r}.")
        self._client = client

    def close(self) -> None:
        if self._client is None:
            return
        try:
            self._client.close()
        except imaplib.IMAP4.error:
            pass
        try:
            self._client.logout()
        except imaplib.IMAP4.error:
            pass
        self._client = None

    def __enter__(self) -> GmailReader:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def test_access(self) -> GmailAccessResult:
        try:
            with self:
                unread = self._unread_count()
                return GmailAccessResult(
                    ok=True,
                    message=f"Gmail OK — {self.mailbox} readable via {self.imap_host}",
                    email=self.email,
                    unread_count=unread,
                )
        except imaplib.IMAP4.error as exc:
            return GmailAccessResult(
                ok=False,
                message=(
                    f"Gmail login failed: {exc}. "
                    "Enable IMAP in Gmail settings and use an App Password."
                ),
                email=self.email,
            )
        except OSError as exc:
            return GmailAccessResult(ok=False, message=f"Network error: {exc}", email=self.email)

    def _unread_count(self) -> int:
        client = self._require_client()
        status, data = client.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return 0
        return len(data[0].split())

    def _require_client(self) -> imaplib.IMAP4_SSL:
        if self._client is None:
            raise RuntimeError("GmailReader is not connected")
        return self._client

    def list_messages(
        self,
        *,
        limit: int = 20,
        unread_only: bool = False,
        since: datetime | None = None,
        from_pattern: str | None = None,
    ) -> list[GmailMessage]:
        self.connect()
        client = self._require_client()
        criteria = ["ALL"]
        if unread_only:
            criteria = ["UNSEEN"]
        if since is not None:
            criteria.append(f'SINCE {since.strftime("%d-%b-%Y")}')
        status, data = client.search(None, *criteria)
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()
        uids = uids[-limit:]
        uids.reverse()
        messages: list[GmailMessage] = []
        for uid in uids:
            msg = self._fetch_message(client, uid.decode("ascii", errors="ignore"))
            if msg is None:
                continue
            if from_pattern and from_pattern.lower() not in msg.from_addr.lower():
                continue
            messages.append(msg)
        return messages

    def _fetch_message(self, client: imaplib.IMAP4_SSL, uid: str) -> GmailMessage | None:
        status, data = client.fetch(uid, "(BODY.PEEK[] FLAGS)")
        if status != "OK" or not data:
            return None
        raw = _extract_body_bytes(data)
        if raw is None:
            return None
        msg = message_from_bytes(raw)
        flags = _extract_flags(data)
        return GmailMessage(
            uid=uid,
            from_addr=_decode_header_value(msg.get("From")),
            subject=_decode_header_value(msg.get("Subject")) or "(no subject)",
            date=_parse_message_date(msg),
            snippet=_message_snippet(msg),
            unread=b"\\Seen" not in flags,
        )


def _extract_body_bytes(fetch_data: Iterable) -> bytes | None:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return None


def _extract_flags(fetch_data: Iterable) -> bytes:
    for item in fetch_data:
        if isinstance(item, bytes):
            return item
        if isinstance(item, tuple) and item and isinstance(item[0], bytes):
            return item[0]
    return b""
