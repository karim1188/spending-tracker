from __future__ import annotations

import re

MENU_PERIODS = ("day", "week", "month", "year")
MENU_ACTIONS = (*MENU_PERIODS, "thermal", "menu")

_CALLBACK_PREFIX = "rpt:"

_COMMAND_ALIASES = {
    "menu": "menu",
    "start": "menu",
    "help": "menu",
    "reports": "menu",
    "day": "day",
    "today": "day",
    "week": "week",
    "month": "month",
    "year": "year",
    "thermal": "thermal",
    "temp": "thermal",
    "temperature": "thermal",
    "overheat": "thermal",
}


def menu_message() -> str:
    return (
        "Spending tracker menu\n"
        "Tap a button, or send: day · week · month · year · temp\n"
        "Send menu anytime to open this again."
    )


def menu_button_rows() -> list[list[tuple[str, bytes]]]:
    """Label + callback payload pairs for Telethon Button.inline."""
    return [
        [("Day", f"{_CALLBACK_PREFIX}day".encode()), ("Week", f"{_CALLBACK_PREFIX}week".encode())],
        [("Month", f"{_CALLBACK_PREFIX}month".encode()), ("Year", f"{_CALLBACK_PREFIX}year".encode())],
        [("Mac temp", f"{_CALLBACK_PREFIX}thermal".encode()), ("Menu", f"{_CALLBACK_PREFIX}menu".encode())],
    ]


def parse_callback_data(data: bytes | str | None) -> str | None:
    if data is None:
        return None
    raw = data.decode() if isinstance(data, (bytes, bytearray)) else str(data)
    if not raw.startswith(_CALLBACK_PREFIX):
        return None
    action = raw.removeprefix(_CALLBACK_PREFIX).strip().lower()
    return action if action in MENU_ACTIONS else None


def parse_menu_command(text: str | None) -> str | None:
    """Return menu action from a short user message, or None if not a command."""
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 64:
        return None
    cleaned = cleaned.lower()
    cleaned = re.sub(r"^[/!.]+", "", cleaned)
    cleaned = cleaned.split("@", 1)[0].strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if " " in cleaned:
        # Allow "/report day" style
        parts = cleaned.split(" ", 1)
        if parts[0] in {"report", "rpt", "spending"} and parts[1] in _COMMAND_ALIASES:
            return _COMMAND_ALIASES[parts[1]]
        return None
    return _COMMAND_ALIASES.get(cleaned)
