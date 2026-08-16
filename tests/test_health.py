from __future__ import annotations

from notify.health import format_health_report, read_health


def test_read_health_returns_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("notify.health.SPENDING_DB_PATH", tmp_path / "missing.db")
    snap = read_health(overheat_threshold=90.0, include_db_stats=False)
    assert snap.hostname
    assert snap.process_uptime_seconds >= 0
    assert snap.platform
    text = format_health_report(snap)
    assert "Server health" in text
    assert "CPU:" in text
    assert "RAM:" in text
    assert "App RSS:" in text
    assert "Disk:" in text


def test_health_public_dict_keys():
    snap = read_health(include_db_stats=False)
    data = snap.as_public_dict()
    for key in ("cpu_percent", "ram_percent", "process_rss_mb", "disk_free_gb", "overheating"):
        assert key in data
