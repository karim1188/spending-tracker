from __future__ import annotations

from collections.abc import Iterable, Sequence

BRAND = "PRIVATE LEDGER"
RULE = "────────────────"
RULE_HEAVY = "━━━━━━━━━━━━━━━━"


def format_sar(amount: float) -> str:
    return f"SAR {amount:,.2f}"


def card(
    kind: str,
    *,
    subtitle: str | None = None,
    sections: Sequence[Sequence[str]] | None = None,
    footer: str | None = None,
    badge: str | None = None,
) -> str:
    """
    Shared Telegram layout:

        PRIVATE LEDGER
        ━━━━━━━━━━━━━━━━
        DAY REPORT
        16 Aug 2026
        ────────────────
        …section…
        ────────────────
        …section…
        ━━━━━━━━━━━━━━━━
        footer
    """
    lines: list[str] = [BRAND, RULE_HEAVY]
    title = kind.strip().upper()
    if badge:
        lines.append(f"{title}  ·  {badge.strip().upper()}")
    else:
        lines.append(title)
    if subtitle:
        lines.append(subtitle.strip())
    blocks = [list(section) for section in (sections or []) if section]
    for section in blocks:
        lines.append(RULE)
        lines.extend(section)
    lines.append(RULE_HEAVY)
    if footer:
        lines.append(footer.strip())
    return "\n".join(lines)


def kv(label: str, value: str, width: int = 11) -> str:
    label = label.strip()
    pad = max(1, width - len(label))
    return f"{label}{' ' * pad}{value}"


def bullet_rows(
    rows: Iterable[dict],
    *,
    label_key: str = "label",
    amount_key: str = "total_amount",
    limit: int = 6,
) -> list[str]:
    out: list[str] = []
    for row in list(rows)[:limit]:
        label = str(row.get(label_key) or "—").strip() or "—"
        amount = row.get(amount_key)
        if amount is None:
            out.append(f"· {label}")
        else:
            out.append(f"· {label}  ·  {format_sar(float(amount))}")
    return out


def section(title: str, body: Sequence[str]) -> list[str]:
    if not body:
        return []
    return [title.upper(), *body]


def progress_bar(ratio: float, width: int = 10) -> str:
    clamped = max(0.0, min(1.0, ratio))
    filled = int(round(clamped * width))
    return "█" * filled + "░" * (width - filled)


def budget_lines(spent: float, limit: float) -> list[str]:
    remaining = limit - spent
    ratio = (spent / limit) if limit > 0 else 0.0
    bar = progress_bar(ratio)
    lines = [
        kv("Spent", format_sar(spent)),
        kv("Limit", format_sar(limit)),
        f"[{bar}] {min(ratio, 1.0) * 100:.0f}%",
    ]
    if remaining >= 0:
        lines.append(kv("Left", format_sar(remaining)))
    else:
        lines.append(kv("Over", format_sar(-remaining)))
    return lines
