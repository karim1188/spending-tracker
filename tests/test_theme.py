from __future__ import annotations

from notify.theme import budget_lines, card, format_sar, progress_bar


def test_card_structure():
    text = card(
        "Day report",
        subtitle="2026-08-16",
        sections=[["Total  SAR 10.00"], ["TOP MERCHANTS", "· Cafe  ·  SAR 10.00"]],
        footer="Reply menu anytime",
    )
    assert text.startswith("PRIVATE LEDGER")
    assert "DAY REPORT" in text
    assert "2026-08-16" in text
    assert "Reply menu anytime" in text
    assert "━━━━━━━━━━━━━━━━" in text


def test_budget_and_progress():
    assert format_sar(12.5) == "SAR 12.50"
    assert progress_bar(0.5, width=10) == "█████░░░░░"
    lines = budget_lines(150, 200)
    assert any("Left" in line for line in lines)
    assert any("75%" in line for line in lines)
