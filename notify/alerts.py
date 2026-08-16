from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from database.db import SpendingDatabase
from notify.settings import TelegramSettings, load_telegram_settings
from notify.shutdown import request_shutdown
from notify.telegram import sender_from_settings
from notify.theme import BRAND, bullet_rows, budget_lines, card, format_sar, kv, section
from notify.thermal import ThermalStatus, read_thermal_status

WARNING_KEY = "last_warning_day"
NEAR_LIMIT_KEY = "last_near_limit_day"
DIGEST_KEY = "last_digest_day"
MONTHLY_WARNING_KEY = "last_monthly_warning_month"

NEAR_LIMIT_LINES = (
    "Hey — you're near the limit. Put the card down like it owes you rent.",
    "Heads up: almost at the wall. Your wallet just filed a restraining order.",
    "Slow down, cowboy — only a little runway left before the daily siren.",
    "Friendly nudge from Future You: stop spending. Leftovers are a lifestyle.",
    "So close to the limit I can hear your bank account whispering 'please'.",
    "Almost at the ceiling. Treat the next purchase like it's optional (it is).",
)


def format_day_report(report: dict, limit: float) -> str:
    title = str(report.get("day") or report.get("title") or "today")
    body = [
        kv("Total", format_sar(report["total_amount"])),
        kv("Buys", str(report.get("txn_count") or 0)),
        *budget_lines(float(report["total_amount"]), limit),
    ]
    merchants = bullet_rows(report.get("merchants") or [])
    sections = [body]
    if merchants:
        sections.append(section("Top merchants", merchants))
    return card(
        "Day report",
        subtitle=title,
        sections=sections,
        footer="Reply menu for week · month · year · server",
    )


def format_period_report(report: dict, limit: float | None = None) -> str:
    period = str(report.get("period") or "report").upper()
    kind = {
        "DAY": "Day report",
        "WEEK": "Week report",
        "MONTH": "Month report",
        "YEAR": "Year report",
    }.get(period, "Spending report")
    body = [
        kv("Total", format_sar(report["total_amount"])),
        kv("Buys", str(report.get("txn_count") or 0)),
    ]
    if report.get("period") == "day" and limit is not None:
        body.extend(budget_lines(float(report["total_amount"]), limit))
    sections: list[list[str]] = [body]
    categories = bullet_rows(report.get("categories") or [])
    merchants = bullet_rows(report.get("merchants") or [])
    if categories:
        sections.append(section("Categories", categories))
    if merchants:
        sections.append(section("Top merchants", merchants))
    return card(
        kind,
        subtitle=str(report.get("title") or period.title()),
        sections=sections,
        footer="Reply menu anytime",
    )


def format_warning(report: dict, limit: float) -> str:
    over = float(report["total_amount"]) - limit
    body = [
        "Daily limit reached.",
        kv("Today", format_sar(report["total_amount"])),
        kv("Limit", format_sar(limit)),
        kv("Over", format_sar(max(0.0, over))),
        *budget_lines(float(report["total_amount"]), limit),
    ]
    merchants = bullet_rows(report.get("merchants") or [])
    sections = [body]
    if merchants:
        sections.append(section("Top merchants", merchants))
    return card(
        "Spending alert",
        subtitle=str(report.get("day") or report.get("title") or "today"),
        sections=sections,
        badge="over limit",
        footer="Ease up — tomorrow resets the daily budget",
    )


def format_near_limit(
    report: dict,
    limit: float,
    cushion: float,
    line: str | None = None,
) -> str:
    remaining = max(0.0, limit - report["total_amount"])
    pick = line if line is not None else random.choice(NEAR_LIMIT_LINES)
    body = [
        pick,
        "",
        kv("Today", format_sar(report["total_amount"])),
        kv("Left", format_sar(remaining)),
        kv("Warn @", f"under {format_sar(cushion)} of {format_sar(limit)}"),
        *budget_lines(float(report["total_amount"]), limit),
    ]
    return card(
        "Near limit",
        subtitle=str(report.get("day") or "today"),
        sections=[body],
        badge="nudge",
        footer="One good skip beats one more purchase",
    )


def format_monthly1_report(series: dict, monthly_limit: float) -> str:
    spending = float(series.get("spending") or 0)
    income = float(series.get("income") or 0)
    body = [
        kv("Income", format_sar(income)),
        kv("Spent", format_sar(spending)),
        kv("Net", format_sar(income - spending)),
        *budget_lines(spending, monthly_limit),
        kv("Through", f"day {series.get('through_day')} / {series.get('days_in_month')}"),
    ]
    day_lines: list[str] = []
    for row in series.get("days") or []:
        if not row["income"] and not row["spending"]:
            continue
        day_lines.append(
            f"D{row['day']:02d}  in {format_sar(row['income'])}  "
            f"out {format_sar(row['spending'])}  "
            f"cum {format_sar(row['cumulative_spending'])}"
        )
    if not day_lines:
        day_lines = ["No income or spending yet this month."]
    # Keep Telegram readable — show latest active days if the month is busy.
    if len(day_lines) > 14:
        day_lines = ["… earlier quiet days omitted", *day_lines[-13:]]
    return card(
        "Monthly1",
        subtitle=str(series.get("label") or series.get("period") or "This month"),
        sections=[body, section("Day by day", day_lines)],
        badge="month to date",
        footer=f"Monthly warn at {format_sar(monthly_limit)} · reply menu",
    )


def format_monthly_warning(series: dict, monthly_limit: float) -> str:
    spending = float(series.get("spending") or 0)
    over = max(0.0, spending - monthly_limit)
    body = [
        "Month-to-date spending crossed the limit.",
        kv("Spent", format_sar(spending)),
        kv("Limit", format_sar(monthly_limit)),
        kv("Over", format_sar(over)),
        *budget_lines(spending, monthly_limit),
        kv("Through", f"day {series.get('through_day')}"),
    ]
    return card(
        "Monthly alert",
        subtitle=str(series.get("label") or "This month"),
        sections=[body],
        badge="6000+",
        footer="Slow the month down — daily limit still applies too",
    )


def format_overheat(
    status: ThermalStatus,
    threshold: float,
    *,
    test: bool = False,
    will_kill: bool = False,
) -> str:
    temp = f"{status.celsius:.1f}°C" if status.celsius is not None else "unknown"
    body = [
        kv("CPU", temp),
        kv("Limit", f"{threshold:.0f}°C"),
        kv("Source", status.source),
    ]
    if status.cpu_speed_limit is not None:
        body.append(kv("Throttle", f"{status.cpu_speed_limit}%"))
    if status.detail:
        body.append(status.detail)
    if will_kill:
        body.append("")
        body.append("Stopping the spending tracker to cool down.")
    elif test:
        body.append("")
        body.append("Test only — app will not stop.")
    return card(
        "Overheat",
        subtitle="Mac thermal status",
        sections=[body],
        badge="test" if test else ("kill switch" if will_kill else "warning"),
        footer=BRAND,
    )


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
    month_key = stamp.strftime("%Y-%m")
    series = db.month_day_series(timezone_name=settings.timezone, now=stamp)
    monthly_limit = settings.monthly_limit_sar
    if (
        float(series["spending"]) >= monthly_limit
        and db.notify_value(MONTHLY_WARNING_KEY) != month_key
    ):
        send(format_monthly_warning(series, monthly_limit))
        db.set_notify_value(MONTHLY_WARNING_KEY, month_key)
        sent.append("monthly_warning")
    return sent


def run_loop(interval: float = 60.0) -> None:
    """Idle runtime: Messages file-watch + Telegram menu. `interval` unused."""
    del interval
    from notify.idle import start_idle_runtime

    start_idle_runtime()


def _sync_quietly() -> None:
    from notify.idle import sync_messages_once

    sync_messages_once()
