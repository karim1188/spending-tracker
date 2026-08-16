from __future__ import annotations

from notify.alerts import check_thermal, format_overheat, send_overheat_test
from notify.settings import TelegramSettings
from notify.thermal import ThermalStatus


def _settings(*, kill: bool = True, threshold: float = 90.0) -> TelegramSettings:
    return TelegramSettings(
        api_id=1,
        api_hash="hash",
        phone="+10000000000",
        chat="me",
        overheat_celsius=threshold,
        overheat_kill=kill,
    )


def test_thermal_status_is_overheating_by_temp():
    hot = ThermalStatus(celsius=95.0, source="mock")
    cool = ThermalStatus(celsius=70.0, source="mock")
    assert hot.is_overheating(90.0) is True
    assert cool.is_overheating(90.0) is False


def test_thermal_status_is_overheating_by_throttle():
    throttled = ThermalStatus(celsius=None, source="pmset", cpu_speed_limit=80, detail="limited")
    ok = ThermalStatus(celsius=None, source="pmset", cpu_speed_limit=100)
    assert throttled.is_overheating(90.0) is True
    assert ok.is_overheating(90.0) is False


def test_check_thermal_sends_and_kills_when_over_limit():
    sent: list[str] = []
    kills: list[str] = []
    status = ThermalStatus(celsius=96.0, source="mock")
    results = check_thermal(
        _settings(kill=True),
        send=sent.append,
        status=status,
        kill=lambda reason: kills.append(reason) or True,
    )
    assert results == ["overheat", "kill"]
    assert len(sent) == 1
    assert "overheat" in sent[0].lower()
    assert "96.0" in sent[0]
    assert kills and "overheating" in kills[0].lower()


def test_check_thermal_does_not_kill_when_disabled():
    sent: list[str] = []
    kills: list[str] = []
    status = ThermalStatus(celsius=99.0, source="mock")
    results = check_thermal(
        _settings(kill=False),
        send=sent.append,
        status=status,
        kill=lambda reason: kills.append(reason) or True,
    )
    assert results == ["overheat"]
    assert len(sent) == 1
    assert kills == []


def test_check_thermal_noop_when_cool():
    sent: list[str] = []
    kills: list[str] = []
    status = ThermalStatus(celsius=60.0, source="mock")
    results = check_thermal(
        _settings(kill=True),
        send=sent.append,
        status=status,
        kill=lambda reason: kills.append(reason) or True,
    )
    assert results == []
    assert sent == []
    assert kills == []


def test_send_overheat_test_never_kills():
    sent: list[str] = []
    status = ThermalStatus(celsius=100.0, source="mock")
    result = send_overheat_test(settings=_settings(kill=True), send=sent.append, status=status)
    assert result["ok"] is True
    assert result["killed"] is False
    assert result["test"] is True
    assert sent and "OVERHEAT" in sent[0] and "TEST" in sent[0]
    assert "Test only" in sent[0]
    assert "Stopping" not in format_overheat(status, 90.0, test=True, will_kill=False)
