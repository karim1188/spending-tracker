from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence


def is_macos() -> bool:
    return sys.platform == "darwin"


def caffeinate_available() -> bool:
    return is_macos() and shutil.which("caffeinate") is not None


def reexec_under_caffeinate(
    argv: Sequence[str] | None = None,
    *,
    prevent_idle: bool = True,
    prevent_display: bool = False,
    prevent_system: bool = False,
) -> None:
    """
    Replace this process with `caffeinate … python …` so idle sleep cannot
    kill the server. No-op if already wrapped or not on macOS.
    """
    if os.environ.get("SPENDING_CAFFEINATED") == "1":
        return
    if not caffeinate_available():
        return
    if not (prevent_idle or prevent_display or prevent_system):
        return

    flags: list[str] = []
    if prevent_idle:
        flags.append("-i")
    if prevent_display:
        flags.append("-d")
    if prevent_system:
        flags.append("-s")

    env = os.environ.copy()
    env["SPENDING_CAFFEINATED"] = "1"
    cmd = ["caffeinate", *flags, sys.executable, *(argv if argv is not None else sys.argv)]
    os.execvpe(cmd[0], cmd, env)


def describe_power_policy(*, prevent_idle: bool, prevent_display: bool, prevent_system: bool) -> str:
    if not is_macos():
        return "Power: sleep prevention is macOS-only"
    if not (prevent_idle or prevent_display or prevent_system):
        return "Power: Mac may sleep (server pauses until wake)"
    parts = []
    if prevent_idle:
        parts.append("idle sleep blocked")
    if prevent_display:
        parts.append("display stays on")
    else:
        parts.append("display may sleep")
    if prevent_system:
        parts.append("system sleep blocked (best on power adapter)")
    return "Power: " + " · ".join(parts) + " via caffeinate"
