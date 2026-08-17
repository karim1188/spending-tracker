from datetime import date

from collector.salary_period import (
    pay_month_for_salary,
    salary_chart_day,
    salary_window,
)


def test_salary_window_spans_prev_month():
    start, end = salary_window(2026, 8)
    assert start == date(2026, 7, 27)
    assert end == date(2026, 8, 5)


def test_pay_month_early_and_late():
    assert pay_month_for_salary(date(2026, 7, 28)) == (2026, 8)
    assert pay_month_for_salary(date(2026, 7, 27)) == (2026, 8)
    assert pay_month_for_salary(date(2026, 7, 26)) == (2026, 7)
    assert pay_month_for_salary(date(2026, 8, 3)) == (2026, 8)
    assert pay_month_for_salary(date(2026, 8, 5)) == (2026, 8)
    assert pay_month_for_salary(date(2026, 8, 6)) == (2026, 8)
    assert pay_month_for_salary(date(2025, 12, 28)) == (2026, 1)


def test_salary_chart_day_maps_early_to_day_one():
    assert salary_chart_day(date(2026, 7, 28), 2026, 8) == 1
    assert salary_chart_day(date(2026, 8, 3), 2026, 8) == 3
    assert salary_chart_day(date(2026, 7, 20), 2026, 8) is None
    assert salary_chart_day(date(2026, 8, 6), 2026, 8) == 6
    assert salary_chart_day(date(2026, 7, 28), 2026, 7) is None
