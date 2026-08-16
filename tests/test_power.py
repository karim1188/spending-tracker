from __future__ import annotations

from collector.power import caffeinate_available, describe_power_policy, is_macos


def test_describe_power_policy_allow_sleep():
    text = describe_power_policy(prevent_idle=False, prevent_display=False, prevent_system=False)
    assert "sleep" in text.lower()


def test_describe_power_policy_idle_only():
    text = describe_power_policy(prevent_idle=True, prevent_display=False, prevent_system=False)
    if is_macos():
        assert "idle sleep blocked" in text
        assert "display may sleep" in text
    else:
        assert "macOS-only" in text


def test_caffeinate_probe_does_not_crash():
    assert isinstance(is_macos(), bool)
    assert isinstance(caffeinate_available(), bool)
