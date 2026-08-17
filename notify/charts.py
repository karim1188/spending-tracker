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
    from PIL import Image, ImageDraw

    days = list(series.get("days") or [])
    if not days:
        raise ValueError("No day rows to chart")

    day_nums = [int(row["day"]) for row in days]
    cum_spend = [float(row.get("cumulative_spending") or 0) for row in days]
    cum_income = [float(row.get("cumulative_income") or 0) for row in days]
    allowed_mtd = [float(row.get("allowed_mtd") or (int(row["day"]) * daily_limit)) for row in days]
    remaining_mtd = [max(0.0, float(row.get("remaining_mtd") or 0)) for row in days]

    month_cap = float(monthly_limit) or 6000.0
    y_max = max(
        max(cum_spend) if cum_spend else 0,
        max(cum_income) if cum_income else 0,
        max(allowed_mtd) if allowed_mtd else 0,
        month_cap,
        float(daily_limit),
        1.0,
    )

    width, height = 900, 420
    left, top, right, bottom = 48, 36, 20, 44
    plot_w = width - left - right
    plot_h = height - top - bottom

    img = Image.new("RGB", (width, height), "#f4f0e8")
    draw = ImageDraw.Draw(img)
    draw.rectangle((left, top, left + plot_w, top + plot_h), fill="#faf7f2", outline="#cbbfa6")

    def point(index: int, value: float) -> tuple[float, float]:
        span = max(len(days) - 1, 1)
        x = left + (index / span) * plot_w
        y = top + plot_h - (max(value, 0) / y_max) * plot_h
        return x, y

    def polyline(values: list[float], color: str, width: int = 2) -> None:
        if len(values) < 2:
            return
        draw.line([point(i, values[i]) for i in range(len(values))], fill=color, width=width)

    cap_y = top + plot_h - (month_cap / y_max) * plot_h
    for x in range(left, left + plot_w, 6):
        draw.line((x, cap_y, min(x + 3, left + plot_w), cap_y), fill="#16130f", width=1)

    for step in range(5):
        gy = top + plot_h - (plot_h * step / 4)
        draw.line((left, gy, left + plot_w, gy), fill="#e8e0d0", width=1)

    polyline(cum_income, "#4f5d3c", 3)
    polyline(cum_spend, "#c45c26", 3)
    polyline(allowed_mtd, "#3d6b8c", 2)
    polyline(remaining_mtd, "#5a7a38", 2)

    label = str(series.get("label") or series.get("period") or "This month")
    draw.text((left, 8), f"{label} · day by day", fill="#16130f")
    draw.text((left, height - 28), "Day", fill="#6d5a3c")
    draw.text((8, top), "SAR", fill="#6d5a3c")

    label_every = 5 if len(day_nums) > 20 else 2 if len(day_nums) > 12 else 1
    for index, day_n in enumerate(day_nums):
        if index % label_every != 0 and index != len(day_nums) - 1:
            continue
        x, _ = point(index, 0)
        draw.text((x - 4, top + plot_h + 6), str(day_n), fill="#6d5a3c")

    legend = [
        ("Income", "#4f5d3c"),
        ("Spending", "#c45c26"),
        ("Budget", "#3d6b8c"),
        ("Left", "#5a7a38"),
        ("Cap", "#16130f"),
    ]
    lx = left + plot_w - 250
    ly = top + 6
    for name, color in legend:
        draw.rectangle((lx, ly + 4, lx + 14, ly + 14), fill=color)
        draw.text((lx + 18, ly + 2), name, fill="#16130f")
        lx += 50

    img.save(path, format="PNG", optimize=True)
