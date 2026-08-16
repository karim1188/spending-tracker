from __future__ import annotations

from notify.menu import (
    menu_button_rows,
    menu_message,
    parse_callback_data,
    parse_menu_command,
)


def test_parse_menu_commands():
    assert parse_menu_command("menu") == "menu"
    assert parse_menu_command("/menu") == "menu"
    assert parse_menu_command("/start") == "menu"
    assert parse_menu_command("Day") == "day"
    assert parse_menu_command("/week") == "week"
    assert parse_menu_command("report month") == "month"
    assert parse_menu_command("monthly1") == "monthly1"
    assert parse_menu_command("mtd") == "monthly1"
    assert parse_menu_command("what did I spend on coffee?") is None
    assert parse_menu_command("") is None
    assert parse_menu_command("x" * 80) is None


def test_parse_callback_data():
    assert parse_callback_data(b"rpt:day") == "day"
    assert parse_callback_data("rpt:year") == "year"
    assert parse_callback_data(b"rpt:monthly1") == "monthly1"
    assert parse_callback_data(b"rpt:health") == "health"
    assert parse_callback_data(b"rpt:nope") is None
    assert parse_callback_data(b"other") is None


def test_menu_buttons_cover_reports():
    labels = {label for row in menu_button_rows() for label, _ in row}
    assert {"Day", "Week", "Month", "Year", "Monthly1", "Server", "Menu"} <= labels
    assert "PRIVATE LEDGER" in menu_message()
    assert "MENU" in menu_message()
    assert "monthly1" in menu_message().lower()
