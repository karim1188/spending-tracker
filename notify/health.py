from __future__ import annotations

import os
import platform
import shutil
import socket
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from collector.project_paths import SPENDING_DB_PATH
from notify.thermal import read_thermal_status

PROCESS_STARTED_AT = time.time()


@dataclass(frozen=True)
class HealthSnapshot:
    hostname: str
    platform: str
    python: str
    cpu_percent: float | None
    cpu_count: int | None
    load_1m: float | None
    load_5m: float | None
    load_15m: float | None
    ram_used_gb: float | None
    ram_total_gb: float | None
    ram_percent: float | None
    process_rss_mb: float | None
    process_uptime_seconds: float
    disk_free_gb: float | None
    disk_total_gb: float | None
    disk_percent_used: float | None
    spending_db_mb: float | None
    transaction_count: int | None
    last_message_id: int | None
    thermal_celsius: float | None
    thermal_source: str
    cpu_speed_limit: int | None
    overheat_threshold_celsius: float
    overheating: bool
    collected_at: str

    def as_public_dict(self) -> dict:
        return asdict(self)


def read_health(
    *,
    overheat_threshold: float = 90.0,
    include_db_stats: bool = True,
) -> HealthSnapshot:
    thermal = read_thermal_status()
    ram = _ram_stats()
    disk = _disk_stats(Path.home())
    load = _load_avg()
    db_mb, txn_count, last_msg = (None, None, None)
    if include_db_stats:
        db_mb, txn_count, last_msg = _spending_stats()
    return HealthSnapshot(
        hostname=socket.gethostname(),
        platform=f"{platform.system()} {platform.machine()}",
        python=platform.python_version(),
        cpu_percent=_cpu_percent(),
        cpu_count=os.cpu_count(),
        load_1m=load[0],
        load_5m=load[1],
        load_15m=load[2],
        ram_used_gb=ram[0],
        ram_total_gb=ram[1],
        ram_percent=ram[2],
        process_rss_mb=_process_rss_mb(),
        process_uptime_seconds=max(0.0, time.time() - PROCESS_STARTED_AT),
        disk_free_gb=disk[0],
        disk_total_gb=disk[1],
        disk_percent_used=disk[2],
        spending_db_mb=db_mb,
        transaction_count=txn_count,
        last_message_id=last_msg,
        thermal_celsius=thermal.celsius,
        thermal_source=thermal.source,
        cpu_speed_limit=thermal.cpu_speed_limit,
        overheat_threshold_celsius=overheat_threshold,
        overheating=thermal.is_overheating(overheat_threshold),
        collected_at=datetime.now(timezone.utc).isoformat(),
    )


def format_health_report(snap: HealthSnapshot) -> str:
    lines = [
        "Server health",
        f"{snap.hostname} · {snap.platform}",
        "",
        f"CPU: {_fmt_pct(snap.cpu_percent)}"
        + (f" · {snap.cpu_count} cores" if snap.cpu_count else ""),
    ]
    if snap.load_1m is not None:
        lines.append(
            f"Load: {snap.load_1m:.2f} / {snap.load_5m:.2f} / {snap.load_15m:.2f} (1/5/15m)"
        )
    lines.append(
        f"RAM: {_fmt_gb(snap.ram_used_gb)} / {_fmt_gb(snap.ram_total_gb)}"
        + (f" ({snap.ram_percent:.0f}%)" if snap.ram_percent is not None else "")
    )
    lines.append(f"App RSS: {_fmt_mb(snap.process_rss_mb)} · up {_fmt_uptime(snap.process_uptime_seconds)}")
    lines.append(
        f"Disk: {_fmt_gb(snap.disk_free_gb)} free of {_fmt_gb(snap.disk_total_gb)}"
        + (f" ({snap.disk_percent_used:.0f}% used)" if snap.disk_percent_used is not None else "")
    )
    if snap.thermal_celsius is not None:
        flag = " · HOT" if snap.overheating else ""
        lines.append(
            f"Temp: {snap.thermal_celsius:.1f}°C (limit {snap.overheat_threshold_celsius:.0f}°C){flag}"
        )
    elif snap.cpu_speed_limit is not None:
        flag = " · THROTTLING" if snap.overheating else ""
        lines.append(f"CPU speed limit: {snap.cpu_speed_limit}%{flag}")
    else:
        lines.append(f"Temp: unavailable ({snap.thermal_source})")
    if snap.spending_db_mb is not None or snap.transaction_count is not None:
        bits = []
        if snap.transaction_count is not None:
            bits.append(f"{snap.transaction_count} txns")
        if snap.spending_db_mb is not None:
            bits.append(f"DB {_fmt_mb(snap.spending_db_mb)}")
        if snap.last_message_id is not None:
            bits.append(f"msg #{snap.last_message_id}")
        lines.append("Ledger: " + " · ".join(bits))
    lines.append(f"Python {snap.python}")
    return "\n".join(lines)


def _fmt_pct(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "—"


def _fmt_gb(value: float | None) -> str:
    return f"{value:.1f} GB" if value is not None else "—"


def _fmt_mb(value: float | None) -> str:
    return f"{value:.1f} MB" if value is not None else "—"


def _fmt_uptime(seconds: float) -> str:
    secs = int(seconds)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, sec = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {mins}m"
    if hours:
        return f"{hours}h {mins}m"
    if mins:
        return f"{mins}m {sec}s"
    return f"{sec}s"


def _cpu_percent() -> float | None:
    try:
        import psutil

        # First call after import can be 0.0; brief interval for a real sample.
        psutil.cpu_percent(interval=None)
        return float(psutil.cpu_percent(interval=0.15))
    except Exception:
        pass
    return _cpu_percent_fallback()


def _cpu_percent_fallback() -> float | None:
    if platform.system() != "Darwin":
        return None
    try:
        import subprocess

        completed = subprocess.run(
            ["top", "-l", "1", "-n", "0", "-s", "0"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        import re

        match = re.search(
            r"CPU usage:\s*([0-9.]+)%\s*user,\s*([0-9.]+)%\s*sys",
            completed.stdout or "",
        )
        if not match:
            return None
        return float(match.group(1)) + float(match.group(2))
    except Exception:
        return None


def _ram_stats() -> tuple[float | None, float | None, float | None]:
    try:
        import psutil

        mem = psutil.virtual_memory()
        used = mem.used / (1024**3)
        total = mem.total / (1024**3)
        return used, total, float(mem.percent)
    except Exception:
        pass
    return _ram_stats_fallback()


def _ram_stats_fallback() -> tuple[float | None, float | None, float | None]:
    if platform.system() != "Darwin":
        return None, None, None
    try:
        import subprocess
        import re

        total_out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        total_bytes = int((total_out.stdout or "0").strip() or "0")
        if total_bytes <= 0:
            return None, None, None
        vm = subprocess.run(
            ["vm_stat"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        page_match = re.search(r"page size of (\d+) bytes", vm.stdout or "")
        page = int(page_match.group(1)) if page_match else 4096
        free = _vm_pages(vm.stdout or "", "Pages free")
        speculative = _vm_pages(vm.stdout or "", "Pages speculative")
        free_bytes = (free + speculative) * page
        used_bytes = max(0, total_bytes - free_bytes)
        used_gb = used_bytes / (1024**3)
        total_gb = total_bytes / (1024**3)
        pct = (used_bytes / total_bytes) * 100.0
        return used_gb, total_gb, pct
    except Exception:
        return None, None, None


def _vm_pages(text: str, label: str) -> int:
    import re

    match = re.search(rf"{re.escape(label)}:\s*([0-9]+)", text)
    return int(match.group(1)) if match else 0


def _process_rss_mb() -> float | None:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024**2)
    except Exception:
        pass
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS: bytes; Linux: kilobytes
        if platform.system() == "Darwin":
            return usage / (1024**2)
        return usage / 1024.0
    except Exception:
        return None


def _disk_stats(path: Path) -> tuple[float | None, float | None, float | None]:
    try:
        usage = shutil.disk_usage(path)
        free = usage.free / (1024**3)
        total = usage.total / (1024**3)
        used_pct = ((usage.total - usage.free) / usage.total) * 100.0 if usage.total else None
        return free, total, used_pct
    except OSError:
        return None, None, None


def _load_avg() -> tuple[float | None, float | None, float | None]:
    try:
        one, five, fifteen = os.getloadavg()
        return float(one), float(five), float(fifteen)
    except (AttributeError, OSError):
        return None, None, None


def _spending_stats() -> tuple[float | None, int | None, int | None]:
    db_mb = None
    try:
        if SPENDING_DB_PATH.is_file():
            db_mb = SPENDING_DB_PATH.stat().st_size / (1024**2)
    except OSError:
        db_mb = None
    txn_count = None
    last_msg = None
    try:
        from database.db import SpendingDatabase

        with SpendingDatabase() as db:
            row = db.conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()
            txn_count = int(row["c"]) if row else 0
            last_msg = db.get_checkpoint() or None
    except Exception:
        pass
    return db_mb, txn_count, last_msg
