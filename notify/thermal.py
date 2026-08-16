from __future__ import annotations

import platform
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ThermalStatus:
    celsius: float | None
    source: str
    cpu_speed_limit: int | None = None
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.celsius is not None or self.cpu_speed_limit is not None

    def is_overheating(self, threshold_celsius: float) -> bool:
        if self.celsius is not None and self.celsius >= threshold_celsius:
            return True
        # Thermal throttle without a die temp still means the Mac is protecting itself.
        if self.cpu_speed_limit is not None and self.cpu_speed_limit < 100:
            return True
        return False


def read_thermal_status() -> ThermalStatus:
    if platform.system() != "Darwin":
        return ThermalStatus(celsius=None, source="unsupported", detail="Temperature reading works on macOS only")
    for reader in (_from_osx_cpu_temp, _from_powermetrics, _from_pmset_therm):
        status = reader()
        if status is not None and status.available:
            return status
    return ThermalStatus(celsius=None, source="unavailable", detail="Install osx-cpu-temp or allow powermetrics")


def _run(command: list[str], timeout: float = 4.0) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 and not completed.stdout:
        return None
    return (completed.stdout or "") + "\n" + (completed.stderr or "")


def _from_osx_cpu_temp() -> ThermalStatus | None:
    binary = shutil.which("osx-cpu-temp")
    if not binary:
        return None
    output = _run([binary])
    if not output:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*°?\s*C", output, re.I)
    if not match:
        return None
    return ThermalStatus(celsius=float(match.group(1)), source="osx-cpu-temp")


def _from_powermetrics() -> ThermalStatus | None:
    # Non-interactive sudo only — never prompt for a password from the daemon.
    output = _run(["sudo", "-n", "powermetrics", "--samplers", "smc", "-i1", "-n1"], timeout=6.0)
    if not output:
        return None
    match = re.search(
        r"(?:CPU die temperature|CPU temp(?:erature)?|Die temperature)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*C",
        output,
        re.I,
    )
    if not match:
        return None
    return ThermalStatus(celsius=float(match.group(1)), source="powermetrics")


def _from_pmset_therm() -> ThermalStatus | None:
    output = _run(["pmset", "-g", "therm"])
    if not output:
        return None
    limit_match = re.search(r"CPU_Speed_Limit\s*=\s*([0-9]+)", output)
    limit = int(limit_match.group(1)) if limit_match else None
    if limit is None:
        return None
    detail = "CPU speed limited" if limit < 100 else "CPU not throttling"
    return ThermalStatus(celsius=None, source="pmset", cpu_speed_limit=limit, detail=detail)
