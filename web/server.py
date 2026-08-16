from __future__ import annotations

import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from categorizer.categorizer import CATEGORIES
from collector.imessage_reader import IMessageReader, MessagesAccessError
from collector.logging_config import setup_logging
from collector.message_collector import MessageCollector
from collector.project_paths import PROJECT_ROOT
from config.loader import BankRegistry
from database.db import SpendingDatabase

STATIC_DIR = Path(__file__).resolve().parent / "static"
HOST = "0.0.0.0"
PORT = 8787
_sync_lock = threading.Lock()
TXN_PATH = re.compile(r"^/api/transactions/(\d+)$")
EXCLUDE_PATH = re.compile(r"^/api/transactions/(\d+)/exclude$")
RECURRING_TXN_PATH = re.compile(r"^/api/transactions/(\d+)/recurring$")
RECURRING_ITEM_PATH = re.compile(r"^/api/recurring/(\d+)$")


def lan_ipv4() -> list[str]:
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            found.append(sock.getsockname()[0])
    except OSError:
        pass
    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if hostname_ip and not hostname_ip.startswith("127."):
            found.append(hostname_ip)
    except OSError:
        pass
    unique: list[str] = []
    for ip in found:
        if ip not in unique and not ip.startswith("127."):
            unique.append(ip)
    return unique


def advertised_urls(host: str, port: int) -> list[str]:
    urls = [f"http://127.0.0.1:{port}"]
    if host in {"0.0.0.0", "::", ""}:
        urls.extend(f"http://{ip}:{port}" for ip in lan_ipv4())
    elif host not in {"127.0.0.1", "localhost"}:
        urls.append(f"http://{host}:{port}")
    seen: list[str] = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


def row_to_public(row, include_raw: bool = False) -> dict:
    payload = dict(row)
    if not include_raw:
        payload.pop("raw_message", None)
    if "is_recurring" in payload:
        payload["is_recurring"] = bool(payload["is_recurring"])
    for key, value in list(payload.items()):
        if hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
    return payload


def _first(query: dict[str, list[str]], key: str) -> str | None:
    value = (query.get(key) or [None])[0]
    return value or None


def _filters(query: dict[str, list[str]]) -> dict:
    return {
        "year": _first(query, "year"),
        "month": _first(query, "month"),
        "bank": _first(query, "bank"),
        "category": _first(query, "category"),
        "sender": _first(query, "sender"),
        "transaction_type": _first(query, "type"),
        "query": _first(query, "q"),
    }


class LedgerHandler(BaseHTTPRequestHandler):
    server_version = "SpendingLedger/0.1"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/static/"):
            relative = parsed.path.removeprefix("/static/")
            target = (STATIC_DIR / relative).resolve()
            if STATIC_DIR not in target.parents and target != STATIC_DIR:
                self._send_json({"error": "not found"}, 404)
                return
            content_type = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".svg": "image/svg+xml",
            }.get(target.suffix, "application/octet-stream")
            self._send_file(target, content_type)
            return
        query = parse_qs(parsed.query)
        if parsed.path == "/api/summary":
            with SpendingDatabase() as db:
                self._send_json(db.summary(**_filters(query)))
            return
        if parsed.path == "/api/filters":
            with SpendingDatabase() as db:
                payload = db.filter_options()
            payload["all_categories"] = list(CATEGORIES)
            self._send_json(payload)
            return
        if parsed.path == "/api/transactions":
            filters = _filters(query)
            limit = int((_first(query, "limit") or "1000"))
            with SpendingDatabase() as db:
                rows = db.list_transactions(limit=min(limit, 2000), **filters)
            self._send_json({"transactions": [row_to_public(row) for row in rows]})
            return
        match = TXN_PATH.match(parsed.path)
        if match:
            with SpendingDatabase() as db:
                row = db.get_transaction(int(match.group(1)))
            if not row:
                self._send_json({"error": "not found"}, 404)
                return
            self._send_json({"transaction": row_to_public(row, include_raw=True)})
            return
        if parsed.path == "/api/recurring":
            with SpendingDatabase() as db:
                self._send_json(db.recurring_summary())
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/sync":
            self._sync()
            return
        if parsed.path == "/api/duplicates/purge":
            with SpendingDatabase() as db:
                removed = db.purge_duplicates()
            self._send_json({"ok": True, "removed": removed})
            return
        if parsed.path == "/api/merchant-rules":
            body = self._read_json()
            merchant = str(body.get("merchant") or "").strip()
            category = str(body.get("category") or "").strip()
            if not category:
                self._send_json({"error": "category required"}, 400)
                return
            with SpendingDatabase() as db:
                if merchant:
                    db.upsert_merchant_rule(merchant, category, apply_existing=True)
                txn_id = body.get("transaction_id")
                if txn_id and not merchant:
                    db.set_transaction_category(int(txn_id), category)
            self._send_json({"ok": True})
            return
        recurring = RECURRING_TXN_PATH.match(parsed.path)
        if recurring:
            with SpendingDatabase() as db:
                summary = db.mark_recurring(int(recurring.group(1)))
            if summary is None:
                self._send_json({"error": "cannot mark salary or incoming transfers as spending"}, 400)
                return
            self._send_json({"ok": True, **summary})
            return
        exclude = EXCLUDE_PATH.match(parsed.path)
        if exclude:
            with SpendingDatabase() as db:
                ok = db.exclude_transaction(int(exclude.group(1)), "excluded from detail page")
            self._send_json({"ok": ok}, 200 if ok else 404)
            return
        self._send_json({"error": "not found"}, 404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        recurring_txn = RECURRING_TXN_PATH.match(parsed.path)
        if recurring_txn:
            with SpendingDatabase() as db:
                summary = db.unmark_recurring(int(recurring_txn.group(1)))
            if summary is None:
                self._send_json({"error": "not found"}, 404)
                return
            self._send_json({"ok": True, **summary})
            return
        recurring_item = RECURRING_ITEM_PATH.match(parsed.path)
        if recurring_item:
            with SpendingDatabase() as db:
                summary = db.delete_recurring_item(int(recurring_item.group(1)))
            if summary is None:
                self._send_json({"error": "not found"}, 404)
                return
            self._send_json({"ok": True, **summary})
            return
        match = TXN_PATH.match(parsed.path)
        if not match:
            self._send_json({"error": "not found"}, 404)
            return
        with SpendingDatabase() as db:
            deleted = db.delete_transaction(int(match.group(1)))
        self._send_json({"ok": deleted}, 200 if deleted else 404)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _sync(self) -> None:
        if not _sync_lock.acquire(blocking=False):
            self._send_json({"error": "sync already running"}, 409)
            return
        try:
            setup_logging()
            reader = IMessageReader()
            access = reader.test_access()
            if not access.ok:
                self._send_json(
                    {
                        "ok": False,
                        "error": access.message,
                        "full_disk_access_required": access.full_disk_access_required,
                    },
                    503,
                )
                return
            with SpendingDatabase() as db:
                collector = MessageCollector(
                    db=db,
                    reader=reader,
                    registry=BankRegistry.load(),
                )
                stats = collector.sync_once(limit=200)
            self._send_json(
                {
                    "ok": True,
                    "scanned": stats.scanned,
                    "stored": stats.stored,
                    "ignored_non_bank": stats.ignored_non_bank,
                    "duplicates": stats.skipped_duplicate,
                    "unknown": stats.unknown,
                }
            )
        except MessagesAccessError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 503)
        finally:
            _sync_lock.release()

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class ReusableLedgerServer(ThreadingHTTPServer):
    allow_reuse_address = True


def serve(host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    return ReusableLedgerServer((host, port), LedgerHandler)
