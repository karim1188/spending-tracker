from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from collector.logging_config import get_logger
from database.db import SpendingDatabase
from notify.settings import TelegramSettings, load_telegram_settings
from notify.telegram import sender_from_settings

WARNING_KEY = "last_warning_day"
DIGEST_KEY = "last_digest_day"


def format_sar(amount: float) -> str:
    return f"SAR {amount:,.2f}"


def format_day_report(report: dict, limit: float) -> str:
    remaining = limit - report["total_amount"]
    lines = [
        f"Spending for {report['day']}",
        f"{format_sar(report['total_amount'])} · {report['txn_count']} purchases",
    ]
    if remaining >= 0:
        lines.append(f"{format_sar(remaining)} left before the {format_sar(limit)} daily warning")
    else:
        lines.append(f"Over the {format_sar(limit)} daily warning by {format_sar(-remaining)}")
    if report["merchants"]:
        lines.append("")
        lines.append("Top")
        for row in report["merchants"]:
            lines.append(f"· {row['label']}: {format_sar(row['total_amount'])}")
    return "\n".join(lines)


def format_warning(report: dict, limit: float) -> str:
    return (
        f"Daily spending warning\n"
        f"Today is {format_sar(report['total_amount'])} — over {format_sar(limit)}.\n\n"
        f"{format_day_report(report, limit)}"
    )


def tick(
    db: SpendingDatabase,
    settings: TelegramSettings | None = None,
    send: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> list[str]:
    settings = settings if settings is not None else load_telegram_settings()
    if send is None:
        send = sender_from_settings(settings)
    if settings is None or send is None:
        return []
    tz = ZoneInfo(settings.timezone)
    stamp = now.astimezone(tz) if now else datetime.now(tz)
    day = stamp.date().isoformat()
    report = db.day_spending_report(day)
    sent: list[str] = []
    if report["total_amount"] >= settings.daily_limit_sar and db.notify_value(WARNING_KEY) != day:
        send(format_warning(report, settings.daily_limit_sar))
        db.set_notify_value(WARNING_KEY, day)
        sent.append("warning")
    digest_due = (stamp.hour, stamp.minute) >= (settings.daily_hour, settings.daily_minute)
    if digest_due and db.notify_value(DIGEST_KEY) != day:
        send(format_day_report(report, settings.daily_limit_sar))
        db.set_notify_value(DIGEST_KEY, day)
        sent.append("digest")
    return sent


def run_loop(interval: float = 60.0) -> None:
    logger = get_logger()
    settings = load_telegram_settings()
    if settings is None:
        logger.info("Telegram alerts off: copy config/telegram.example.json to config/telegram.json")
        return
    logger.info("Telegram alerts on. Daily digest at %02d:%02d, warning at SAR %.0f", settings.daily_hour, settings.daily_minute, settings.daily_limit_sar)
    while True:
        try:
            _sync_quietly()
            with SpendingDatabase() as db:
                sent = tick(db, settings=settings)
            if sent:
                logger.info("Telegram sent: %s", ", ".join(sent))
        except Exception as exc:  # noqa: BLE001 — keep the ledger running
            logger.info("Telegram alert cycle failed: %s", exc)
        time.sleep(interval)


def _sync_quietly() -> None:
    try:
        from collector.imessage_reader import IMessageReader, MessagesAccessError
        from collector.message_collector import MessageCollector
        from config.loader import BankRegistry
        from database.db import SpendingDatabase

        reader = IMessageReader()
        access = reader.test_access()
        if not access.ok:
            return
        with SpendingDatabase() as db:
            MessageCollector(db=db, reader=reader, registry=BankRegistry.load()).sync_once(limit=100)
    except Exception:
        return
