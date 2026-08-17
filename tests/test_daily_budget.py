from collector.daily_budget import enrich_month_days


def test_rollover_accumulates_unused_days():
    series = {
        "through_day": 3,
        "days": [
            {"day": 1, "spending": 150, "cumulative_spending": 150},
            {"day": 2, "spending": 0, "cumulative_spending": 150},
            {"day": 3, "spending": 100, "cumulative_spending": 250},
        ],
    }
    out = enrich_month_days(series, 200)
    d1, d2, d3 = out["days"]
    assert d1["daily_allowance"] == 200
    assert d1["daily_remaining"] == 50
    assert d1["rollover_out"] == 50
    assert d2["rollover_in"] == 50
    assert d2["daily_allowance"] == 250
    assert d2["rollover_out"] == 250
    assert d3["rollover_in"] == 250
    assert d3["daily_allowance"] == 450
    assert d3["daily_remaining"] == 350
    assert d3["remaining_mtd"] == 350


def test_overspend_does_not_carry_negative_rollover():
    series = {
        "through_day": 2,
        "days": [
            {"day": 1, "spending": 250, "cumulative_spending": 250},
            {"day": 2, "spending": 50, "cumulative_spending": 300},
        ],
    }
    out = enrich_month_days(series, 200)
    d1, d2 = out["days"]
    assert d1["daily_remaining"] == -50
    assert d1["rollover_out"] == 0
    assert d2["rollover_in"] == 0
    assert d2["daily_allowance"] == 200
    assert d2["remaining_mtd"] == 100


def test_daily_budget_summary_on_last_day():
    series = {
        "through_day": 2,
        "days": [
            {"day": 1, "spending": 120, "cumulative_spending": 120},
            {"day": 2, "spending": 30, "cumulative_spending": 150},
        ],
    }
    out = enrich_month_days(series, 200)
    budget = out["daily_budget"]
    assert budget["day"] == 2
    assert budget["rollover_in"] == 80
    assert budget["daily_allowance"] == 280
    assert budget["daily_remaining"] == 250
