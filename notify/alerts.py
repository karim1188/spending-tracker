from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from collector.logging_config import get_logger
from database.db import SpendingDatabase
from notify.settings import TelegramSettings, load_telegram_settings
from notify.shutdown import request_shutdown
from notify.telegram import sender_from_settings
from notify.thermal import ThermalStatus, read_thermal_status

WARNING_KEY = "last_warning_day"
NEAR_LIMIT_KEY = "last_near_limit_day"
DIGEST_KEY = "last_digest_day"

NEAR_LIMIT_LINES = (
    "Hey — you're near the limit. Put the card down like it owes you rent.",
    "Heads up: almost at the wall. Your wallet just filed a restraining order.",
    "Slow down, cowboy — only a little runway left before the daily siren.",
    "Friendly nudge from Future You: stop spending. Leftovers are a lifestyle.",
    "So close to the limit I can hear your bank account whispering 'please'.",
    "Almost at the ceiling. Treat the next purchase like it's optional (it is).",
)


def format_sar(amount: float) -> str:
    return f"SAR {amount:,.2f}"


def format_day_report(report: dict, limit: float) -> str:
    remaining = limit - report["total_amount"]
    lines = [
        f"Spending for {report.get('day') or report.get('title') or 'today'}",
        f"{format_sar(report['total_amount'])} · {report['txn_count']} purchases",
    ]
    if remaining >= 0:
        lines.append(f"{format_sar(remaining)} left before the {format_sar(limit)} daily warning")
    else:
        lines.append(f"Over the {format_sar(limit)} daily warning by {format_sar(-remaining)}")
    if report.get("merchants"):
        lines.append("")
        lines.append("Top")
        for row in report["merchants"]:
            lines.append(f"· {row['label']}: {format_sar(row['total_amount'])}")
    return "\n".join(lines)


def format_period_report(report: dict, limit: float | None = None) -> str:
    lines = [
        f"Spending report · {report['title']}",
        f"{format_sar(report['total_amount'])} · {report['txn_count']} purchases",
    ]
    if report.get("period") == "day" and limit is not None:
        remaining = limit - report["total_amount"]
        if remaining >= 0:
            lines.append(f"{format_sar(remaining)} left before the {format_sar(limit)} daily warning")
        else:
            lines.append(f"Over the {format_sar(limit)} daily warning by {format_sar(-remaining)}")
    if report.get("categories"):
        lines.append("")
        lines.append("By category")
        for row in report["categories"]:
            lines.append(f"· {row['label']}: {format_sar(row['total_amount'])}")
    if report.get("merchants"):
        lines.append("")
        lines.append("Top merchants")
        for row in report["merchants"]:
            lines.append(f"· {row['label']}: {format_sar(row['total_amount'])}")
    return "\n".join(lines)


def format_warning(report: dict, limit: float) -> str:
    return (
        f"Daily spending warning\n"
        f"Today is {format_sar(report['total_amount'])} — over {format_sar(limit)}.\n\n"
        f"{format_day_report(report, limit)}"
    )


def format_near_limit(
    report: dict,
    limit: float,
    cushion: float,
    line: str | None = None,
) -> str:
    remaining = max(0.0, limit - report["total_amount"])
    pick = line if line is not None else random.choice(NEAR_LIMIT_LINES)
    return (
        f"{pick}\n\n"
        f"Today: {format_sar(report['total_amount'])} · "
        f"{format_sar(remaining)} left (warning kicks in under {format_sar(cushion)} of {format_sar(limit)})."
    )


def format_overheat(
    status: ThermalStatus,
    threshold: float,
    *,
    test: bool = False,
    will_kill: bool = False,
) -> str:
    prefix = "[TEST] " if test else ""
    temp = f"{status.celsius:.1f}°C" if status.celsius is not None else "unknown"
    lines = [
        f"{prefix}Mac overheat warning",
        f"CPU: {temp} (threshold {threshold:.0f}°C)",
        f"Source: {status.source}",
    ]
    if status.cpu_speed_limit is not None:
        lines.append(f"CPU speed limit: {status.cpu_speed_limit}%")
    if status.detail:
        lines.append(status.detail)
    if will_kill:
        lines.append("Stopping the spending tracker to cool down.")
    elif test:
        lines.append("Test only — app will not stop.")
    return "\n".join(lines)


def thermal_payload(status: ThermalStatus, threshold: float) -> dict:
    return {
        "celsius": status.celsius,
        "source": status.source,
        "cpu_speed_limit": status.cpu_speed_limit,
        "detail": status.detail,
        "available": status.available,
        "threshold_celsius": threshold,
        "overheating": status.is_overheating(threshold),
    }


def send_overheat_test(
    settings: TelegramSettings | None = None,
    send: Callable[[str], None] | None = None,
    status: ThermalStatus | None = None,
) -> dict:
    """Send a Telegram overheat test message. Never triggers the kill switch."""
    settings = settings if settings is not None else load_telegram_settings()
    if send is None:
        send = sender_from_settings(settings)
    if settings is None or send is None:
        raise RuntimeError("Telegram is not configured. Add config/telegram.json and run telegram_login.py once.")
    status = status if status is not None else read_thermal_status()
    threshold = settings.overheat_celsius
    text = format_overheat(status, threshold, test=True, will_kill=False)
    send(text)
    return {"ok": True, "test": True, "killed": False, **thermal_payload(status, threshold)}


def check_thermal(
    settings: TelegramSettings,
    send: Callable[[str], None],
    status: ThermalStatus | None = None,
    kill: Callable[[str], bool] | None = None,
) -> list[str]:
    """Warn on Telegram when overheating; optionally request app shutdown."""
    status = status if status is not None else read_thermal_status()
    threshold = settings.overheat_celsius
    if not status.is_overheating(threshold):
        return []
    will_kill = bool(settings.overheat_kill)
    send(format_overheat(status, threshold, test=False, will_kill=will_kill))
    results = ["overheat"]
    if will_kill:
        kill_fn = kill if kill is not None else request_shutdown
        temp = f"{status.celsius:.1f}°C" if status.celsius is not None else "throttling"
        kill_fn(f"Mac overheating ({temp}, threshold {threshold:.0f}°C)")
        results.append("kill")
    return results


def send_period_report(
    db: SpendingDatabase,
    period: str,
    settings: TelegramSettings | None = None,
    send: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> dict:
    settings = settings if settings is not None else load_telegram_settings()
    if send is None:
        send = sender_from_settings(settings)
    if settings is None or send is None:
        raise RuntimeError("Telegram is not configured. Add config/telegram.json and run telegram_login.py once.")
    report = db.period_spending_report(
        period,
        timezone_name=settings.timezone,
        now=now,
    )
    text = format_period_report(report, settings.daily_limit_sar if period == "day" else None)
    send(text)
    return {"ok": True, "period": period, "title": report["title"], "total_amount": report["total_amount"]}


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
    spent = report["total_amount"]
    limit = settings.daily_limit_sar
    cushion = settings.near_limit_sar
    near_floor = max(0.0, limit - cushion)
    if spent >= limit and db.notify_value(WARNING_KEY) != day:
        send(format_warning(report, limit))
        db.set_notify_value(WARNING_KEY, day)
        sent.append("warning")
    elif (
        spent >= near_floor
        and spent < limit
        and db.notify_value(NEAR_LIMIT_KEY) != day
    ):
        send(format_near_limit(report, limit, cushion))
        db.set_notify_value(NEAR_LIMIT_KEY, day)
        sent.append("near_limit")
    digest_due = (stamp.hour, stamp.minute) >= (settings.daily_hour, settings.daily_minute)
    if digest_due and db.notify_value(DIGEST_KEY) != day:
        send(format_day_report(report, limit))
        db.set_notify_value(DIGEST_KEY, day)
        sent.append("digest")
    return sent


def run_loop(interval: float = 60.0) -> None:
    """Idle runtime: Messages file-watch + Telegram menu. `interval` unused."""
    del interval
    from notify.idle import start_idle_runtime

    start_idle_runtime()


def _sync_quietly() -> None:
    from notify.idle import sync_messages_once

    sync_messages_once()
