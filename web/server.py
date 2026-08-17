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
        if parsed.path == "/api/dashboard":
            from collector.daily_budget import enrich_month_days
            from notify.settings import load_telegram_settings

            with SpendingDatabase() as db:
                payload = db.dashboard(
                    year=_first(query, "year"),
                    month=_first(query, "month"),
                    bank=_first(query, "bank"),
                )
            settings = load_telegram_settings()
            payload["monthly_limit_sar"] = (
                float(settings.monthly_limit_sar) if settings else 6000.0
            )
            daily_limit = float(settings.daily_limit_sar) if settings else 200.0
            payload["daily_limit_sar"] = daily_limit
            if payload.get("month_days"):
                payload["month_days"] = enrich_month_days(payload["month_days"], daily_limit)
            self._send_json(payload)
            return
        if parsed.path == "/api/recurring":
            with SpendingDatabase() as db:
                self._send_json(db.recurring_summary())
            return
        if parsed.path in {"/api/health", "/api/thermal"}:
            from notify.health import read_health
            from notify.settings import load_telegram_settings

            settings = load_telegram_settings()
            threshold = settings.overheat_celsius if settings else 90.0
            snap = read_health(overheat_threshold=threshold)
            payload = snap.as_public_dict()
            payload["ok"] = True
            payload["available"] = (
                snap.cpu_percent is not None
                or snap.ram_percent is not None
                or snap.thermal_celsius is not None
                or snap.cpu_speed_limit is not None
            )
            payload["celsius"] = snap.thermal_celsius
            payload["source"] = snap.thermal_source
            payload["overheat_kill"] = bool(settings.overheat_kill) if settings else True
            self._send_json(payload)
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
        if parsed.path == "/api/recurring":
            body = self._read_json()
            try:
                amount = float(body.get("amount"))
            except (TypeError, ValueError):
                self._send_json({"error": "amount required"}, 400)
                return
            with SpendingDatabase() as db:
                summary = db.add_manual_habit(
                    label=str(body.get("label") or "").strip(),
                    amount=amount,
                    frequency=str(body.get("frequency") or "daily"),
                    category=str(body.get("category") or "").strip() or None,
                    currency=str(body.get("currency") or "SAR"),
                )
            if summary is None:
                self._send_json({"error": "label, positive amount, and daily/weekly/monthly required"}, 400)
                return
            self._send_json({"ok": True, **summary})
            return
        if parsed.path == "/api/telegram/report":
            body = self._read_json()
            period = str(body.get("period") or "").strip().lower()
            if period not in {"day", "week", "month", "year"}:
                self._send_json({"error": "period must be day, week, month, or year"}, 400)
                return
            try:
                from notify.alerts import send_period_report

                with SpendingDatabase() as db:
                    result = send_period_report(db, period)
                self._send_json(result)
            except Exception as exc:  # noqa: BLE001 — surface setup errors to UI
                self._send_json({"error": str(exc)}, 503)
            return
        if parsed.path == "/api/telegram/menu":
            try:
                from notify.hub import get_hub
                from notify.menu import menu_message
                from notify.settings import load_telegram_settings
                from notify.telegram import sender_from_settings

                hub = get_hub()
                if hub is not None and hub.ready:
                    hub.send_menu()
                else:
                    settings = load_telegram_settings()
                    send = sender_from_settings(settings)
                    if send is None:
                        raise RuntimeError("Telegram is not configured")
                    send(menu_message() + "\n\n(Buttons available after the Mac app is running with Telethon.)")
                self._send_json({"ok": True})
            except Exception as exc:  # noqa: BLE001 — surface setup errors to UI
                self._send_json({"error": str(exc)}, 503)
            return
        if parsed.path == "/api/telegram/health":
            try:
                from notify.health import format_health_report, read_health
                from notify.settings import load_telegram_settings
                from notify.telegram import sender_from_settings

                settings = load_telegram_settings()
                send = sender_from_settings(settings)
                if send is None:
                    raise RuntimeError("Telegram is not configured")
                threshold = settings.overheat_celsius if settings else 90.0
                snap = read_health(overheat_threshold=threshold)
                send(format_health_report(snap))
                self._send_json({"ok": True, **snap.as_public_dict()})
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 503)
            return
        if parsed.path == "/api/telegram/overheat-test":
            try:
                from notify.alerts import send_overheat_test

                result = send_overheat_test()
                self._send_json(result)
            except Exception as exc:  # noqa: BLE001 — surface setup errors to UI
                self._send_json({"error": str(exc)}, 503)
            return
        if parsed.path == "/api/deploy":
            self._deploy()
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

    def _header_map(self) -> dict[str, str]:
        return {key: value for key, value in self.headers.items()}

    def _deploy(self) -> None:
        from collector.deploy import (
            DeployConfigError,
            extract_deploy_token,
            prepare_deploy_restart,
            schedule_deploy_shutdown,
            token_is_valid,
        )

        body = self._read_json()
        token = extract_deploy_token(self._header_map(), body)
        try:
            if not token_is_valid(token):
                self._send_json({"ok": False, "error": "invalid or missing deploy token"}, 401)
                return
            result = prepare_deploy_restart()
            self._send_json(result)
            schedule_deploy_shutdown("deploy API: git pull restart")
        except DeployConfigError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 503)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)}, 500)

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
                stats = collector.sync_all()
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
