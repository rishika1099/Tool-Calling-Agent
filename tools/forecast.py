"""Hourly forecasts from Open-Meteo (free, no API key)."""

import json
from datetime import date, datetime, timedelta, timezone

import requests
from cachetools import TTLCache, cached

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 7

HOURLY = "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,precipitation,snowfall,wind_speed_10m,wind_gusts_10m"


class ForecastError(Exception):
    """A problem the model can fix, e.g. an unknown city or an out-of-range date."""


@cached(TTLCache(maxsize=64, ttl=24 * 3600))
def _geocode(location: str) -> dict:
    results = requests.get(GEOCODE_URL, params={"name": location, "count": 1}, timeout=10).json().get("results")
    if not results:
        raise ForecastError(f"Place '{location}' was not found. Use a city name like 'New York' or 'Boston'.")
    return results[0]


@cached(TTLCache(maxsize=64, ttl=15 * 60))
def _hourly(latitude: float, longitude: float) -> dict:
    resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": HOURLY,
            "timezone": "auto",
            "forecast_days": FORECAST_DAYS,
            "wind_speed_unit": "ms",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def resolve_date(day: str, utc_offset_seconds: int) -> date:
    """Turn 'today', 'tomorrow' or 'YYYY-MM-DD' into a date in the location's timezone."""
    local_today = (datetime.now(timezone.utc) + timedelta(seconds=utc_offset_seconds)).date()
    day = (day or "today").strip().lower()
    if day == "today":
        return local_today
    if day == "tomorrow":
        return local_today + timedelta(days=1)
    if day in ("day after tomorrow", "the day after tomorrow"):
        return local_today + timedelta(days=2)
    try:
        wanted = date.fromisoformat(day)
    except ValueError:
        raise ForecastError(f"Date '{day}' is not valid. Use 'today', 'tomorrow' or YYYY-MM-DD.")
    last = local_today + timedelta(days=FORECAST_DAYS - 1)
    if not local_today <= wanted <= last:
        raise ForecastError(f"Forecasts only cover {local_today} to {last}. Ask the user for a date in that range.")
    return wanted


def hourly_for_day(location: str, day: str) -> tuple[dict, date, list[dict]]:
    """Return (place, date, 24 hourly rows) in metric units. Raises ForecastError or requests errors."""
    place = _geocode(location)
    data = _hourly(place["latitude"], place["longitude"])
    wanted = resolve_date(day, data["utc_offset_seconds"])
    h = data["hourly"]
    rows = [
        {
            "hour": int(t[11:13]),
            "temp_c": h["temperature_2m"][i],
            "feels_like_c": h["apparent_temperature"][i],
            "humidity": h["relative_humidity_2m"][i],
            "precip_chance": h["precipitation_probability"][i],
            "precip_mm": h["precipitation"][i],
            "snow_cm": h["snowfall"][i],
            "wind_ms": h["wind_speed_10m"][i],
            "gust_ms": h["wind_gusts_10m"][i],
        }
        for i, t in enumerate(h["time"])
        if t.startswith(wanted.isoformat())
    ]
    return place, wanted, rows


@cached(TTLCache(maxsize=64, ttl=10 * 60))
def current_conditions(location: str = "New York") -> dict:
    """Weather right now, for the page's live sky (not a model tool). Raises on failure."""
    place = _geocode(location)
    now = requests.get(
        FORECAST_URL,
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,precipitation,rain,snowfall,wind_speed_10m,is_day",
            "wind_speed_unit": "ms",
            "timezone": "auto",
        },
        timeout=10,
    ).json()["current"]
    return {
        "location": place["name"],
        "temp_f": to_f(now["temperature_2m"]),
        "feels_like_f": to_f(now["apparent_temperature"]),
        "wind_mph": to_mph(now["wind_speed_10m"]),
        "rain": now["rain"] > 0 or (now["precipitation"] > 0 and now["snowfall"] == 0),
        "snow": now["snowfall"] > 0,
        "is_day": bool(now.get("is_day", 1)),  # from the sun's position, not the user's dark-mode setting
    }


def to_f(c: float) -> int:
    return round(c * 9 / 5 + 32)


def to_mph(ms: float) -> int:
    return round(ms * 2.237)


def get_forecast_window(location: str = "New York", day: str = "today", start_hour: int = 7, end_hour: int = 22) -> str:
    """Hour-by-hour weather for the part of a day the user cares about."""
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23 and start_hour <= end_hour):
        return json.dumps({"error": "start_hour and end_hour must be 0-23 with start_hour <= end_hour."})
    try:
        place, wanted, rows = hourly_for_day(location, day)
    except ForecastError as e:
        return json.dumps({"error": str(e)})
    except requests.RequestException as e:
        return json.dumps({"error": f"Weather service failed ({type(e).__name__}). Try again in a moment."})

    return json.dumps({
        "location": f"{place['name']}, {place.get('admin1', place.get('country', ''))}",
        "date": wanted.isoformat(),
        "hours": [
            {
                "hour": r["hour"],
                "temp_f": to_f(r["temp_c"]),
                "feels_like_f": to_f(r["feels_like_c"]),
                "precip_chance_pct": r["precip_chance"],
                "precip_mm": r["precip_mm"],
                "snow_cm": r["snow_cm"],
                "wind_mph": to_mph(r["wind_ms"]),
                "gust_mph": to_mph(r["gust_ms"]),
            }
            for r in rows
            if start_hour <= r["hour"] <= end_hour
        ],
    })


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_forecast_window",
            "description": (
                "Get the hour-by-hour forecast (temperature, feels-like, rain/snow chance, wind) "
                "for part of one day, up to 7 days ahead. Use for general weather questions. "
                "For outfit questions call plan_day_warmth instead: it fetches the forecast itself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name, e.g. 'New York'. Defaults to New York."},
                    "day": {"type": "string", "description": "'today', 'tomorrow', or a date as YYYY-MM-DD within the next 7 days."},
                    "start_hour": {"type": "integer", "description": "First hour to include, 0-23 local time, e.g. 7 for 7am."},
                    "end_hour": {"type": "integer", "description": "Last hour to include, 0-23 local time, e.g. 22 for 10pm."},
                },
                "required": [],
            },
        },
    },
]

TOOL_MAP = {"get_forecast_window": get_forecast_window}
