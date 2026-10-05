from datetime import date

from app.services.destination.climate import (
    ARCHIVE_URL,
    FORECAST_URL,
    choose_window,
    shift_back_one_year,
    summarize_daily,
)

TODAY = date(2026, 10, 5)


def test_near_trip_uses_forecast_for_real_dates():
    url, start, end, historical = choose_window(
        date(2026, 10, 10), date(2026, 10, 12), today=TODAY
    )
    assert (url, start, end, historical) == (
        FORECAST_URL,
        date(2026, 10, 10),
        date(2026, 10, 12),
        False,
    )


def test_horizon_boundary_still_uses_forecast():
    url, *_ = choose_window(date(2026, 10, 19), date(2026, 10, 20), today=TODAY)
    assert url == FORECAST_URL


def test_far_trip_uses_last_years_dates():
    url, start, end, historical = choose_window(
        date(2026, 11, 10), date(2026, 11, 14), today=TODAY
    )
    assert (url, start, end, historical) == (
        ARCHIVE_URL,
        date(2025, 11, 10),
        date(2025, 11, 14),
        True,
    )


def test_leap_day_shifts_to_a_real_date():
    assert shift_back_one_year(date(2028, 2, 29)) == date(2027, 3, 1)


def test_summary_describes_hot_dry_conditions():
    info = summarize_daily(
        {
            "time": ["d1", "d2", "d3"],
            "temperature_2m_max": [29.4, 28.0, 27.5],
            "temperature_2m_min": [17.6, 18.0, 19.1],
            "precipitation_sum": [0.0, 0.0, 0.0],
        },
        historical=True,
    )
    assert info.available
    assert (info.min_temp_c, info.max_temp_c, info.precipitation_mm) == (17.6, 29.4, 0.0)
    assert info.summary.startswith("Typical conditions (same dates last year): hot and mostly dry")


def test_summary_flags_wet_forecast():
    info = summarize_daily(
        {
            "time": ["d1", "d2"],
            "temperature_2m_max": [12.0, 11.0],
            "temperature_2m_min": [6.0, 5.0],
            "precipitation_sum": [8.0, 6.0],
        },
        historical=False,
    )
    assert info.summary.startswith("Forecast: cool and wet")


def test_missing_readings_are_ignored():
    info = summarize_daily(
        {
            "time": ["d1", "d2"],
            "temperature_2m_max": [None, 20.0],
            "temperature_2m_min": [10.0, None],
            "precipitation_sum": [None, None],
        },
        historical=False,
    )
    assert (info.min_temp_c, info.max_temp_c, info.precipitation_mm) == (10.0, 20.0, None)


def test_no_temperatures_means_unavailable():
    info = summarize_daily({"time": []}, historical=True)
    assert not info.available
    assert info.historical
