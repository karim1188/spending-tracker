from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from notify.settings import TelegramSettings


MAINTENANCE_IDLE_SECONDS = 900  # 15 min when far from digest
MAINTENANCE_NEAR_DIGEST_SECONDS = 60
NEAR_DIGEST_WINDOW_MINUTES = 10
THERMAL_INTERVAL_SECONDS = 900


def seconds_until_digest_window(
    settings: TelegramSettings,
    *,
    now: datetime | None = None,
) -> float:
    """Seconds until we enter the daily digest check window (or 0 if already inside)."""
    tz = ZoneInfo(settings.timezone)
    stamp = now.astimezone(tz) if now else datetime.now(tz)
    target = stamp.replace(
        hour=settings.daily_hour,
        minute=settings.daily_minute,
        second=0,
        microsecond=0,
    )
    window = timedelta(minutes=NEAR_DIGEST_WINDOW_MINUTES)
    if target - window <= stamp <= target + timedelta(minutes=5):
        return 0.0
    if stamp > target + timedelta(minutes=5):
        target = target + timedelta(days=1)
    start = target - window
    return max(0.0, (start - stamp).total_seconds())


def next_maintenance_sleep_seconds(
    settings: TelegramSettings | None,
    *,
    now: datetime | None = None,
    last_thermal_at: float | None = None,
    monotonic_now: float | None = None,
) -> float:
    """How long the idle loop can sleep before digest or thermal work."""
    import time

    clock = monotonic_now if monotonic_now is not None else time.monotonic()
    thermal_wait = THERMAL_INTERVAL_SECONDS
    if last_thermal_at is not None:
        thermal_wait = max(30.0, THERMAL_INTERVAL_SECONDS - (clock - last_thermal_at))

    if settings is None:
        return min(MAINTENANCE_IDLE_SECONDS, thermal_wait)

    until_digest = seconds_until_digest_window(settings, now=now)
    if until_digest <= 0:
        return min(MAINTENANCE_NEAR_DIGEST_SECONDS, thermal_wait)
    return min(MAINTENANCE_IDLE_SECONDS, until_digest, thermal_wait)
