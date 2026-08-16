from __future__ import annotations

import threading
import time

from collector.logging_config import get_logger
from notify.settings import TelegramSettings, load_telegram_settings

logger = get_logger()

_cycle_lock = threading.Lock()
_watcher_started = False


def sync_messages_once() -> int:
    """Import new Messages. Returns number of transactions stored (0 on skip/error)."""
    try:
        from collector.imessage_reader import IMessageReader
        from collector.message_collector import MessageCollector
        from config.loader import BankRegistry
        from database.db import SpendingDatabase

        reader = IMessageReader()
        access = reader.test_access()
        if not access.ok:
            return 0
        with SpendingDatabase() as db:
            stats = MessageCollector(db=db, reader=reader, registry=BankRegistry.load()).sync_all()
        return int(stats.stored)
    except Exception as exc:  # noqa: BLE001
        logger.info("Idle sync failed: %s", exc)
        return 0


def run_alert_tick(settings: TelegramSettings | None = None) -> list[str]:
    from database.db import SpendingDatabase
    from notify.alerts import tick
    from notify.telegram import sender_from_settings

    settings = settings if settings is not None else load_telegram_settings()
    if settings is None:
        return []
    send = sender_from_settings(settings)
    if send is None:
        return []
    with SpendingDatabase() as db:
        return tick(db, settings=settings, send=send)


def run_thermal_check(settings: TelegramSettings | None = None) -> list[str]:
    from notify.alerts import check_thermal
    from notify.telegram import sender_from_settings

    settings = settings if settings is not None else load_telegram_settings()
    if settings is None:
        return []
    send = sender_from_settings(settings)
    if send is None:
        return []
    return check_thermal(settings, send=send)


def on_messages_activity(settings: TelegramSettings | None = None, *, reason: str = "messages") -> None:
    """Wake path: new SMS (or startup catch-up) → sync spending DB → alerts."""
    with _cycle_lock:
        settings = settings if settings is not None else load_telegram_settings()
        stored = sync_messages_once()
        if stored:
            logger.info("Idle sync (%s): stored %s new transaction(s)", reason, stored)
        else:
            logger.info("Idle sync (%s): no new bank transactions", reason)
        if settings is None:
            return
        sent = run_alert_tick(settings)
        if sent:
            logger.info("Telegram sent: %s", ", ".join(sent))
        thermal = run_thermal_check(settings)
        if thermal:
            logger.info("Thermal: %s", ", ".join(thermal))


def lightweight_maintenance(settings: TelegramSettings | None = None) -> None:
    """Cheap wake: spending.db digest/near-limit + thermal. Does not open chat.db."""
    with _cycle_lock:
        settings = settings if settings is not None else load_telegram_settings()
        if settings is None:
            return
        sent = run_alert_tick(settings)
        if sent:
            logger.info("Telegram sent: %s", ", ".join(sent))
        thermal = run_thermal_check(settings)
        if thermal:
            logger.info("Thermal: %s", ", ".join(thermal))


def start_messages_watcher(settings: TelegramSettings | None = None) -> None:
    global _watcher_started
    if _watcher_started:
        return
    from collector.messages_watch import MessagesWatcher

    settings = settings if settings is not None else load_telegram_settings()

    def _on_change() -> None:
        on_messages_activity(settings, reason="watch")

    watcher = MessagesWatcher(on_change=_on_change)
    watcher.start()
    _watcher_started = True
    logger.info("Idle mode: sync only when Messages changes (or you use Telegram / Sync)")


def start_idle_runtime() -> None:
    """Telegram menu (event-driven) + Messages file watch + light digest/thermal timer."""
    settings = load_telegram_settings()
    from notify.hub import start_telegram_hub

    # Catch up once, then sleep until chat.db or Telegram wakes us.
    on_messages_activity(settings, reason="startup")
    start_messages_watcher(settings)

    if settings is None:
        logger.info("Telegram off — Messages watch still idle-syncs locally")
        _digest_loop(None)
        return

    hub = start_telegram_hub(settings)
    if hub is None:
        logger.info("Telegram session not ready — Messages watch only (run telegram_login.py)")
        _digest_loop(settings)
        return

    logger.info(
        "Idle runtime on. Telegram menu live · Messages watch live · digest %02d:%02d · "
        "no timed chat.db polling",
        settings.daily_hour,
        settings.daily_minute,
    )
    _digest_loop(settings)


def _digest_loop(settings: TelegramSettings | None) -> None:
    # Rare light checks for daily digest / overheat without touching chat.db.
    while True:
        try:
            lightweight_maintenance(settings)
        except Exception as exc:  # noqa: BLE001
            logger.info("Idle maintenance failed: %s", exc)
        time.sleep(60)
