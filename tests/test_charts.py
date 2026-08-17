from __future__ import annotations

import pytest

from collector.daily_budget import enrich_month_days
from notify.charts import write_month_day_chart_png


pytest.importorskip("matplotlib")


def test_write_month_day_chart_png_creates_and_removes(tmp_path):
    series = enrich_month_days(
        {
            "label": "Aug 2026",
            "through_day": 3,
            "days_in_month": 31,
            "income": 1000,
            "spending": 250,
            "days": [
                {"day": 1, "income": 1000, "spending": 0, "cumulative_income": 1000, "cumulative_spending": 0},
                {"day": 2, "income": 0, "spending": 100, "cumulative_income": 1000, "cumulative_spending": 100},
                {"day": 3, "income": 0, "spending": 150, "cumulative_income": 1000, "cumulative_spending": 250},
            ],
        },
        200,
    )
    path = write_month_day_chart_png(series, monthly_limit=6000, daily_limit=200)
    try:
        assert path.is_file()
        assert path.suffix == ".png"
        assert path.stat().st_size > 500
    finally:
        path.unlink(missing_ok=True)
        assert not path.exists()


def test_write_month_day_chart_png_empty_days_raises():
    with pytest.raises(ValueError, match="No day rows"):
        write_month_day_chart_png({"days": []}, monthly_limit=6000, daily_limit=200)
