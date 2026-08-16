from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from collector.imessage_reader import IMessageReader, MessagesAccessError
from collector.logging_config import setup_logging
from collector.message_collector import MessageCollector
from collector.project_paths import PROJECT_ROOT
from config.loader import BankRegistry
from database.db import SpendingDatabase

STATIC_DIR = Path(__file__).resolve().parent / "static"
HOST = "127.0.0.1"
PORT = 8787
_sync_lock = threading.Lock()


def row_to_public(row) -> dict:
    payload = dict(row)
    for key, value in list(payload.items()):
        if hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
    return payload


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
        if parsed.path == "/api/summary":
            self._summary()
            return
        if parsed.path == "/api/transactions":
            self._transactions(parse_qs(parsed.query))
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/sync":
            self._sync()
            return
        self._send_json({"error": "not found"}, 404)

    def _summary(self) -> None:
        with SpendingDatabase() as db:
            payload = db.summary()
        self._send_json(payload)

    def _transactions(self, query: dict[str, list[str]]) -> None:
        bank = (query.get("bank") or [None])[0] or None
        category = (query.get("category") or [None])[0] or None
        limit = int((query.get("limit") or ["200"])[0])
        with SpendingDatabase() as db:
            rows = db.list_transactions(limit=min(limit, 500), bank=bank, category=category)
        self._send_json({"transactions": [row_to_public(row) for row in rows]})

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


def serve(host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    return ThreadingHTTPServer((host, port), LedgerHandler)


def main() -> None:
    httpd = serve()
    print(f"Spending ledger: http://{HOST}:{PORT}")
    print("Local only. Apple Messages DB is never written.")
    print(f"Project: {PROJECT_ROOT}")
    httpd.serve_forever()
