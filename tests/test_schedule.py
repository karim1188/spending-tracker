from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from notify.schedule import (
    MAINTENANCE_IDLE_SECONDS,
    MAINTENANCE_NEAR_DIGEST_SECONDS,
    next_maintenance_sleep_seconds,
    seconds_until_digest_window,
)
from notify.settings import TelegramSettings


def _settings() -> TelegramSettings:
    return TelegramSettings(
        api_id=1,
        api_hash="hash",
        phone="+10000000000",
        timezone="Asia/Riyadh",
        daily_hour=21,
        daily_minute=0,
    )


def test_seconds_until_digest_inside_window():
    settings = _settings()
    now = datetime(2026, 8, 16, 20, 55, tzinfo=ZoneInfo("Asia/Riyadh"))
    assert seconds_until_digest_window(settings, now=now) == 0.0


def test_seconds_until_digest_before_window():
    settings = _settings()
    now = datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
    wait = seconds_until_digest_window(settings, now=now)
    # Window starts 20:50; from 12:00 that is 8h50m = 31800s
    assert 30000 < wait < 33000


def test_next_maintenance_sleep_near_digest():
    settings = _settings()
    now = datetime(2026, 8, 16, 20, 55, tzinfo=ZoneInfo("Asia/Riyadh"))
    sleep_for = next_maintenance_sleep_seconds(
        settings,
        now=now,
        last_thermal_at=0.0,
        monotonic_now=0.0,
    )
    assert sleep_for == MAINTENANCE_NEAR_DIGEST_SECONDS


def test_next_maintenance_sleep_far_from_digest():
    settings = _settings()
    now = datetime(2026, 8, 16, 12, 0, tzinfo=ZoneInfo("Asia/Riyadh"))
    sleep_for = next_maintenance_sleep_seconds(
        settings,
        now=now,
        last_thermal_at=0.0,
        monotonic_now=0.0,
    )
    assert sleep_for == MAINTENANCE_IDLE_SECONDS
