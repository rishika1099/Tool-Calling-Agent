"""Offline checks for date resolution. Run: uv run pytest"""

from datetime import date, timedelta

import pytest

from tools.forecast import ForecastError, resolve_date

OFFSET = -4 * 3600  # America/New_York, EDT


def test_today_and_tomorrow():
    today = resolve_date("today", OFFSET)
    assert resolve_date("tomorrow", OFFSET) == today + timedelta(days=1)
    assert resolve_date("", OFFSET) == today  # default is "today"


def test_day_after_tomorrow():
    today = resolve_date("today", OFFSET)
    assert resolve_date("day after tomorrow", OFFSET) == today + timedelta(days=2)
    assert resolve_date("the day after tomorrow", OFFSET) == today + timedelta(days=2)
    assert resolve_date("Day After Tomorrow", OFFSET) == today + timedelta(days=2)  # case-insensitive


def test_exact_iso_date_within_the_forecast_window():
    today = resolve_date("today", OFFSET)
    wanted = today + timedelta(days=3)
    assert resolve_date(wanted.isoformat(), OFFSET) == wanted


def test_iso_date_outside_the_forecast_window_is_rejected():
    today = resolve_date("today", OFFSET)
    with pytest.raises(ForecastError, match="only cover"):
        resolve_date((today + timedelta(days=30)).isoformat(), OFFSET)
    with pytest.raises(ForecastError, match="only cover"):
        resolve_date((today - timedelta(days=1)).isoformat(), OFFSET)


def test_unrecognized_phrase_tells_the_model_what_to_use():
    with pytest.raises(ForecastError, match="today.*tomorrow.*YYYY-MM-DD"):
        resolve_date("next Friday", OFFSET)
