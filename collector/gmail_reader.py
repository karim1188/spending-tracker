from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
import imaplib
import json
import os
import re
from pathlib import Path
from typing import Iterable, Sequence

from collector.project_paths import GMAIL_CONFIG_PATH

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993
ICLOUD_HOSTS = frozenset({"imap.mail.me.com", "imap.mail.icloud.com"})
ALL_MAIL_CANDIDATES = ("[Gmail]/All Mail", "[Google Mail]/All Mail", "All Mail")


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


@dataclass(frozen=True)
class GmailPdfAttachment:
    uid: str
    from_addr: str
    subject: str
    date: datetime | None
    filename: str
    data: bytes


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


def parse_imap_list_line(raw: bytes | str) -> tuple[str, str] | None:
    """Return (flags, mailbox_name) from an IMAP LIST line."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    text = text.strip()
    if text.startswith("* "):
        text = text[2:]
    if text.upper().startswith("LIST "):
        text = text[5:]
    match = re.match(r"^\((?P<flags>[^)]*)\)\s+(\"(?:\\.|[^\"])*\"|\S+)\s+(?P<name>.+)$", text)
    if not match:
        return None
    name = match.group("name").strip()
    if name.startswith('"') and name.endswith('"') and len(name) >= 2:
        name = name[1:-1].replace('\\"', '"')
    return match.group("flags"), name


def find_all_mail_mailbox(client: imaplib.IMAP4_SSL) -> str | None:
    try:
        status, rows = client.list()
    except imaplib.IMAP4.error:
        return None
    if status != "OK":
        return None
    names: list[str] = []
    for row in rows or []:
        if row is None:
            continue
        parsed = parse_imap_list_line(row)
        if parsed is None:
            continue
        flags, name = parsed
        names.append(name)
        if re.search(r"(^|\s)\\\\All(\s|$)", flags) or "\\All" in flags.split():
            return name
    for candidate in ALL_MAIL_CANDIDATES:
        if candidate in names:
            return candidate
    return None


def _decode_header_value(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except (UnicodeError, ValueError, TypeError):
        return raw


def _decode_text(part) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _message_snippet(msg) -> str:
    parts = msg.walk() if msg.is_multipart() else (msg,)
    for part in parts:
        if part.get_content_maintype() == "multipart" or part.get_content_type() != "text/plain":
            continue
        text = " ".join(_decode_text(part).split())
        if text:
            return text[:240]
    return ""


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
        self._client = client
        try:
            self.select_mailbox(self.mailbox)
        except GmailConfigError:
            try:
                client.logout()
            except imaplib.IMAP4.error:
                pass
            self._client = None
            raise

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

    def select_mailbox(self, mailbox: str) -> None:
        client = self._require_client()
        name = (mailbox or "INBOX").strip() or "INBOX"
        status, _ = client.select(name, readonly=True)
        if status != "OK":
            raise GmailConfigError(f"Could not open mailbox {name!r}.")
        self.mailbox = name

    def prefer_all_mail(self) -> str:
        """Use All Mail so archived Thndr invoices are included, not just INBOX."""
        self.connect()
        all_mail = find_all_mail_mailbox(self._require_client())
        if all_mail and all_mail != self.mailbox:
            try:
                self.select_mailbox(all_mail)
            except GmailConfigError:
                return self.mailbox
        return self.mailbox

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

    def search_gmail_uids(
        self,
        queries: Sequence[str],
        *,
        since: datetime | None = None,
        fallback_from: str | None = None,
    ) -> tuple[str, list[str]]:
        self.connect()
        client = self._require_client()
        last_query = ""
        for raw in queries:
            query = raw.strip()
            if not query:
                continue
            if since is not None:
                query = f"{query} after:{since.strftime('%Y/%m/%d')}"
            last_query = query
            try:
                status, data = client.uid("SEARCH", "X-GM-RAW", query)
            except imaplib.IMAP4.error:
                continue
            ids = _uids_from_search(status, data)
            if ids:
                return query, ids

        fallbacks: list[tuple[str, tuple[str, ...]]] = []
        if fallback_from:
            fallbacks.append((f"FROM {fallback_from}", ("FROM", fallback_from)))
        fallbacks.append(("OR FROM thndr SUBJECT thndr", ("OR", "FROM", "thndr", "SUBJECT", "thndr")))
        fallbacks.append(("TEXT THNDR", ("TEXT", "THNDR")))
        since_token = f'SINCE {since.strftime("%d-%b-%Y")}' if since is not None else None
        for label, criteria in fallbacks:
            args = list(criteria)
            if since_token:
                args.append(since_token)
            try:
                status, data = client.uid("SEARCH", *args)
            except imaplib.IMAP4.error:
                continue
            ids = _uids_from_search(status, data)
            if ids:
                return label, ids
        return last_query or (queries[0] if queries else ""), []

    def peek_headers(self, uids: Sequence[str]) -> list[GmailMessage]:
        self.connect()
        client = self._require_client()
        messages: list[GmailMessage] = []
        for uid in uids:
            raw = self._fetch_raw_uid(
                client,
                uid,
                specs=("BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)]", "BODY.PEEK[]"),
            )
            if raw is None:
                continue
            msg = message_from_bytes(raw)
            messages.append(
                GmailMessage(
                    uid=uid,
                    from_addr=_decode_header_value(msg.get("From")),
                    subject=_decode_header_value(msg.get("Subject")) or "(no subject)",
                    date=_parse_message_date(msg),
                    snippet="",
                    unread=False,
                )
            )
        return messages

    def fetch_pdf_attachments(self, uids: Sequence[str]) -> list[GmailPdfAttachment]:
        self.connect()
        client = self._require_client()
        attachments: list[GmailPdfAttachment] = []
        for uid in uids:
            raw_msg = self._fetch_raw_uid(client, uid)
            if raw_msg is None:
                continue
            msg = message_from_bytes(raw_msg)
            from_addr = _decode_header_value(msg.get("From"))
            subject = _decode_header_value(msg.get("Subject")) or "(no subject)"
            when = _parse_message_date(msg)
            for filename, data in iter_pdf_attachments(msg):
                attachments.append(
                    GmailPdfAttachment(
                        uid=uid,
                        from_addr=from_addr,
                        subject=subject,
                        date=when,
                        filename=filename,
                        data=data,
                    )
                )
        return attachments

    def list_pdf_attachments(
        self,
        *,
        gmail_query: str,
        limit: int = 10,
        since: datetime | None = None,
        fallback_from: str | None = None,
        prefer_all_mail: bool = True,
    ) -> list[GmailPdfAttachment]:
        """Fetch PDF attachments without marking messages read (BODY.PEEK / UID FETCH)."""
        self.connect()
        if prefer_all_mail:
            self.prefer_all_mail()
        _query, ids = self.search_gmail_uids(
            [gmail_query],
            since=since,
            fallback_from=fallback_from,
        )
        if not ids:
            return []
        chosen = ids[-max(1, limit) :]
        chosen.reverse()
        return self.fetch_pdf_attachments(chosen)

    def _fetch_raw_uid(
        self,
        client: imaplib.IMAP4_SSL,
        uid: str,
        specs: Sequence[str] = ("BODY.PEEK[]", "RFC822"),
    ) -> bytes | None:
        for spec in specs:
            wrapped = spec if spec.startswith("(") else f"({spec})"
            try:
                status, data = client.uid("FETCH", uid, wrapped)
            except imaplib.IMAP4.error:
                continue
            if status != "OK" or not data:
                continue
            raw = _extract_body_bytes(data)
            if raw:
                return raw
        return None

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


def _uids_from_search(status: str, data) -> list[str]:
    if status != "OK" or not data or not data[0]:
        return []
    return [item.decode("ascii", errors="ignore") for item in data[0].split() if item]


def _extract_body_bytes(fetch_data: Iterable) -> bytes | None:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            raw = bytes(item[1])
            if raw:
                return raw
    return None


def _extract_flags(fetch_data: Iterable) -> bytes:
    for item in fetch_data:
        if isinstance(item, bytes):
            return item
        if isinstance(item, tuple) and item and isinstance(item[0], bytes):
            return item[0]
    return b""


def iter_pdf_attachments(msg: Message) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename() or ""
        content_type = (part.get_content_type() or "").lower()
        is_pdf = filename.lower().endswith(".pdf") or content_type == "application/pdf"
        if not is_pdf:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        found.append((filename or "attachment.pdf", bytes(payload)))
    return found
