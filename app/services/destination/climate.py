from datetime import date, timedelta

import httpx

from app.models.context import ClimateInfo


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_FIELDS = "temperature_2m_max,temperature_2m_min,precipitation_sum"

# Open-Meteo forecasts run about 16 days out; stay inside that with margin.
FORECAST_HORIZON_DAYS = 14
TIMEOUT_SECONDS = 10.0


def shift_back_one_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        # 29 February in a non-leap year.
        return day - timedelta(days=365)


def choose_window(
    start_date: date,
    end_date: date,
    today: date | None = None,
) -> tuple[str, date, date, bool]:
    """Pick the endpoint and date range to ask about.

    Trips inside the forecast horizon get a real forecast. Anything further
    out falls back to the same dates last year, which is the honest way to
    answer "what is it usually like then".
    """
    today = today or date.today()

    if (start_date - today).days <= FORECAST_HORIZON_DAYS:
        return FORECAST_URL, start_date, end_date, False

    return (
        ARCHIVE_URL,
        shift_back_one_year(start_date),
        shift_back_one_year(end_date),
        True,
    )


def _temperature_band(max_temp: float | None) -> str:
    if max_temp is None:
        return "unknown"
    if max_temp <= 0:
        return "freezing"
    if max_temp <= 10:
        return "cold"
    if max_temp <= 18:
        return "cool"
    if max_temp <= 27:
        return "mild"

    return "hot"


def _wetness(precipitation_mm: float | None, days: int) -> str:
    if precipitation_mm is None or days <= 0:
        return "unknown rainfall"

    per_day = precipitation_mm / days

    if per_day >= 5:
        return "wet"
    if per_day >= 1:
        return "some rain"

    return "mostly dry"


def summarize_daily(daily: dict, historical: bool) -> ClimateInfo:
    """Reduce Open-Meteo's daily arrays to the few numbers that matter.

    Pure function -- the aggregation maths is testable on its own.
    """
    highs = [v for v in (daily.get("temperature_2m_max") or []) if v is not None]
    lows = [v for v in (daily.get("temperature_2m_min") or []) if v is not None]
    rain = [v for v in (daily.get("precipitation_sum") or []) if v is not None]

    if not highs and not lows:
        return ClimateInfo(available=False, historical=historical)

    max_temp = max(highs) if highs else None
    min_temp = min(lows) if lows else None

    readings = highs + lows
    avg_temp = round(sum(readings) / len(readings), 1) if readings else None

    precipitation = round(sum(rain), 1) if rain else None
    days = len(daily.get("time") or []) or max(len(highs), len(lows))

    basis = "Typical conditions (same dates last year)" if historical else "Forecast"
    descriptor = _temperature_band(max_temp)
    wetness = _wetness(precipitation, days)

    parts = [f"{basis}: {descriptor} and {wetness}"]

    if min_temp is not None and max_temp is not None:
        parts.append(f"{min_temp}°C to {max_temp}°C")

    if precipitation is not None:
        parts.append(f"{precipitation}mm total precipitation over {days} days")

    return ClimateInfo(
        summary="; ".join(parts) + ".",
        avg_temp_c=avg_temp,
        min_temp_c=min_temp,
        max_temp_c=max_temp,
        precipitation_mm=precipitation,
        historical=historical,
        available=True,
    )


async def fetch_climate(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    today: date | None = None,
) -> ClimateInfo:
    """Fetch climate for a trip window.

    Fails soft: an unavailable weather service still leaves us able to
    advise on plugs and voltage, so this never raises.
    """
    url, window_start, window_end, historical = choose_window(
        start_date, end_date, today
    )

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
        "daily": DAILY_FIELDS,
        "timezone": "auto",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

    except (httpx.HTTPError, ValueError):
        return ClimateInfo(available=False, historical=historical)

    return summarize_daily(payload.get("daily") or {}, historical)
