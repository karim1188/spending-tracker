from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_month_day_chart_png(
    series: dict,
    *,
    monthly_limit: float,
    daily_limit: float,
) -> Path:
    """Render the month-to-date chart to a temp PNG; caller must delete the file."""
    fd, raw = tempfile.mkstemp(suffix=".png", prefix="monthly1-chart-")
    os.close(fd)
    path = Path(raw)
    try:
        _render_month_day_chart(path, series, monthly_limit, daily_limit)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _render_month_day_chart(
    path: Path,
    series: dict,
    monthly_limit: float,
    daily_limit: float,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    days = list(series.get("days") or [])
    if not days:
        raise ValueError("No day rows to chart")

    day_nums = [int(row["day"]) for row in days]
    cum_spend = [float(row.get("cumulative_spending") or 0) for row in days]
    cum_income = [float(row.get("cumulative_income") or 0) for row in days]
    allowed_mtd = [float(row.get("allowed_mtd") or (int(row["day"]) * daily_limit)) for row in days]
    remaining_mtd = [max(0.0, float(row.get("remaining_mtd") or 0)) for row in days]
    daily_spend = [float(row.get("spending") or 0) for row in days]

    month_cap = float(monthly_limit) or 6000.0
    y_max = max(
        max(cum_spend) if cum_spend else 0,
        max(cum_income) if cum_income else 0,
        max(allowed_mtd) if allowed_mtd else 0,
        month_cap,
        float(daily_limit),
        1.0,
    )

    label = str(series.get("label") or series.get("period") or "This month")
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=120)
    fig.patch.set_facecolor("#f4f0e8")
    ax.set_facecolor("#faf7f2")

    ax.axhline(month_cap, color="#16130f", linestyle=(0, (4, 4)), linewidth=1.2, alpha=0.55, label=f"Cap {month_cap:,.0f}")
    ax.plot(day_nums, cum_income, color="#4f5d3c", linewidth=2.2, label="Income (cum.)")
    ax.plot(day_nums, cum_spend, color="#c45c26", linewidth=2.4, label="Spending (cum.)")
    ax.plot(
        day_nums,
        allowed_mtd,
        color="#3d6b8c",
        linewidth=1.8,
        linestyle=(0, (5, 4)),
        label="Daily budget (cum.)",
    )
    ax.plot(day_nums, remaining_mtd, color="#5a7a38", linewidth=2.0, label="Left month-to-date")
    ax.bar(day_nums, daily_spend, width=0.55, color="#c45c26", alpha=0.22, label="Daily spend")

    ax.set_ylim(0, y_max * 1.08)
    ax.set_xlim(min(day_nums) - 0.6, max(day_nums) + 0.6)
    ax.set_xlabel("Day of month")
    ax.set_ylabel("SAR")
    ax.set_title(f"{label} · day by day", fontsize=13, fontweight="bold", color="#16130f")
    ax.grid(axis="y", color="#cbbfa6", alpha=0.35, linewidth=0.8)
    ax.legend(loc="upper left", fontsize=7.5, framealpha=0.92)
    fig.tight_layout()
    fig.savefig(path, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
