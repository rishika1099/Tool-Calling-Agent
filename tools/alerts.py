"""Active weather alerts from the US National Weather Service (free, no API key, US only).

Wind chill advisories, winter storm warnings and the like. plan_day_warmth includes
these automatically; get_weather_alerts is for "any warnings today?" questions.
"""

import json

import requests
from cachetools import TTLCache, cached

from .forecast import ForecastError, _geocode

ALERTS_URL = "https://api.weather.gov/alerts/active"
# NWS asks every client to identify itself with a contact.
HEADERS = {"User-Agent": "LayerLab/0.1 (https://github.com/rishika1099/Tool-Calling-Agent)", "Accept": "application/geo+json"}


@cached(TTLCache(maxsize=64, ttl=10 * 60))
def _fetch(latitude: float, longitude: float) -> list[dict]:
    resp = requests.get(ALERTS_URL, params={"point": f"{latitude:.4f},{longitude:.4f}"}, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return [
        {
            "event": p["event"],
            "severity": p.get("severity"),
            "headline": p.get("headline"),
            "ends": p.get("ends") or p.get("expires"),
            "instruction": (p.get("instruction") or "")[:300],
        }
        for p in (f["properties"] for f in resp.json().get("features", []))
    ]


def active_alerts(place: dict) -> list[dict] | None:
    """Alerts for a geocoded place, [] if none, None if outside the US or the service is down."""
    if place.get("country_code") != "US":
        return None
    try:
        return _fetch(round(place["latitude"], 4), round(place["longitude"], 4))
    except requests.RequestException:
        return None


def get_weather_alerts(location: str = "New York") -> str:
    """Active NWS alerts for a US city."""
    try:
        place = _geocode(location)
    except ForecastError as e:
        return json.dumps({"error": str(e)})
    except requests.RequestException as e:
        return json.dumps({"error": f"Location lookup failed ({type(e).__name__}). Try again in a moment."})
    if place.get("country_code") != "US":
        return json.dumps({"error": f"{place['name']} is outside the US; National Weather Service alerts only cover the US."})
    alerts = active_alerts(place)
    if alerts is None:
        return json.dumps({"error": "The National Weather Service is not responding. Try again in a moment, or rely on the forecast."})
    return json.dumps({"location": place["name"], "count": len(alerts), "alerts": alerts})


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather_alerts",
            "description": (
                "Get active official weather alerts (e.g. Wind Chill Advisory, Winter Storm Warning) from the "
                "US National Weather Service for a US city. Use when the user asks about warnings or severe weather. "
                "plan_day_warmth already includes alerts, so don't call both for outfit questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "US city name, e.g. 'New York'. Defaults to New York."},
                },
                "required": [],
            },
        },
    },
]

TOOL_MAP = {"get_weather_alerts": get_weather_alerts}
