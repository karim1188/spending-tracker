from __future__ import annotations

from datetime import date, timedelta

# Salary SMS can land a few days before month-start or in the first days of the month.
SALARY_DAYS_BEFORE = 5
SALARY_DAYS_THROUGH = 5


def salary_window(year: int, month: int) -> tuple[date, date]:
    """Inclusive date range that counts as this month's salary."""
    month_start = date(year, month, 1)
    start = month_start - timedelta(days=SALARY_DAYS_BEFORE)
    end = month_start + timedelta(days=SALARY_DAYS_THROUGH - 1)
    return start, end


def salary_chart_day(txn_day: date, year: int, month: int) -> int | None:
    """
    Map a salary transaction date onto a day-of-month chart bucket.
    Early arrivals (before the 1st) count as day 1 of the pay month.
    """
    pay_y, pay_m = pay_month_for_salary(txn_day)
    if (pay_y, pay_m) != (year, month):
        return None
    month_start = date(year, month, 1)
    if txn_day < month_start:
        return 1
    return txn_day.day


def pay_month_for_salary(txn_day: date) -> tuple[int, int]:
    """
    Which (year, month) a salary SMS belongs to.
    Days 1–5 → that calendar month.
    Last 5 days of a month → next calendar month.
    Otherwise → calendar month of the SMS.
    """
    if txn_day.day <= SALARY_DAYS_THROUGH:
        return txn_day.year, txn_day.month
    # Near month end: treat as next month's salary if within the early window.
    if txn_day.month == 12:
        next_month_start = date(txn_day.year + 1, 1, 1)
    else:
        next_month_start = date(txn_day.year, txn_day.month + 1, 1)
    early_start = next_month_start - timedelta(days=SALARY_DAYS_BEFORE)
    if early_start <= txn_day < next_month_start:
        return next_month_start.year, next_month_start.month
    return txn_day.year, txn_day.month
