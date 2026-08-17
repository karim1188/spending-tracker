from __future__ import annotations


def enrich_month_days(series: dict, daily_limit: float) -> dict:
    """
    Add daily rollover fields to month_day_series rows.

    Each day gets SAR `daily_limit`. Unspent budget rolls into the next day.
    Overspend on a day does not carry negative rollover — the next day starts
    at the base daily limit again, while month-to-date remaining still reflects debt.
    """
    limit = float(daily_limit)
    rollover_in = 0.0
    enriched_days: list[dict] = []
    for row in series.get("days") or []:
        spending = float(row.get("spending") or 0)
        cumulative = float(row.get("cumulative_spending") or 0)
        day_n = int(row["day"])
        daily_allowance = limit + rollover_in
        daily_remaining = daily_allowance - spending
        rollover_out = max(0.0, daily_remaining)
        allowed_mtd = day_n * limit
        remaining_mtd = allowed_mtd - cumulative
        enriched_days.append(
            {
                **row,
                "daily_limit": limit,
                "rollover_in": rollover_in,
                "daily_allowance": daily_allowance,
                "daily_remaining": daily_remaining,
                "rollover_out": rollover_out,
                "allowed_mtd": allowed_mtd,
                "remaining_mtd": remaining_mtd,
            }
        )
        rollover_in = rollover_out

    out = dict(series)
    out["days"] = enriched_days
    out["daily_limit_sar"] = limit
    if enriched_days:
        focus = enriched_days[-1]
        out["daily_budget"] = {
            "day": focus["day"],
            "spent_today": focus["spending"],
            "daily_limit": limit,
            "rollover_in": focus["rollover_in"],
            "daily_allowance": focus["daily_allowance"],
            "daily_remaining": focus["daily_remaining"],
            "remaining_mtd": focus["remaining_mtd"],
            "allowed_mtd": focus["allowed_mtd"],
        }
    else:
        out["daily_budget"] = None
    return out
