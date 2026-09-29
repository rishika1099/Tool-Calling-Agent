"""Offline checks for the warmth model and outfit builder. Run: uv run pytest"""

import json
from datetime import date

import pytest

from app import get_session
from tools import run_tool, warmth
from tools.warmth import _indoor_clo, _outdoor_clo, _pmv

DAY = [
    {"start": "09:00", "minutes": 20, "activity": "walking", "setting": "outdoors"},
    {"start": "09:20", "minutes": 220, "activity": "sitting", "setting": "indoors"},
    {"start": "13:00", "minutes": 10, "activity": "standing", "setting": "outdoors"},
]


def fake_day(temp_c: float, wind_ms: float = 3.0, rain: bool = False):
    """Replace the forecast and alerts with a fixed day, so tests don't need the network."""
    rows = [
        {"hour": h, "temp_c": temp_c, "feels_like_c": temp_c - 3, "humidity": 70,
         "precip_chance": 90 if rain else 5, "precip_mm": 1.0 if rain else 0.0,
         "snow_cm": 0.0, "wind_ms": wind_ms, "gust_ms": wind_ms * 2}
        for h in range(24)
    ]
    return lambda location, day: ({"name": "New York", "country_code": "US"}, date(2026, 12, 14), rows)


@pytest.fixture
def cold_day(monkeypatch):
    monkeypatch.setattr(warmth, "hourly_for_day", fake_day(0.0, rain=True))
    monkeypatch.setattr(warmth, "active_alerts", lambda place: [])


@pytest.fixture
def mild_day(monkeypatch):
    monkeypatch.setattr(warmth, "hourly_for_day", fake_day(18.0))
    monkeypatch.setattr(warmth, "active_alerts", lambda place: [])


def plan(session, segments=DAY):
    return json.loads(run_tool("plan_day_warmth", {"segments": segments}, session))


def test_pmv_matches_iso_7730_reference_values():
    assert _pmv(22, 60, 0.1, 1.2, 0.5) == pytest.approx(-0.75, abs=0.01)
    assert _pmv(27, 60, 0.1, 1.2, 0.5) == pytest.approx(0.77, abs=0.01)


def test_colder_windier_and_longer_trips_need_more_clothing():
    assert _outdoor_clo(0, 70, 2.5, "walking", 20, 20) > _outdoor_clo(10, 70, 2.5, "walking", 20, 20)
    assert _outdoor_clo(0, 70, 5.0, "walking", 20, 20) > _outdoor_clo(0, 70, 2.5, "walking", 20, 20)
    assert _outdoor_clo(0, 70, 2.5, "walking", 90, 20) > _outdoor_clo(0, 70, 2.5, "walking", 20, 20)
    assert _outdoor_clo(0, 70, 1.3, "standing", 20, 20) > _outdoor_clo(0, 70, 2.5, "walking", 20, 20)


def test_indoor_winter_clothing_is_about_one_clo():
    assert 0.9 <= _indoor_clo(22, 30, 0.1, "sitting", 0.0) <= 1.3


def test_runs_cold_adds_warmth(cold_day):
    _, session = get_session(None)
    base = plan(session)["summary"]["outdoor_clo_ideal"]
    run_tool("set_cold_sensitivity", {"level": "runs_cold"}, session)
    assert plan(session)["summary"]["outdoor_clo_ideal"] == pytest.approx(base + 0.2, abs=0.011)


def test_heat_law_decides_indoor_temperature(cold_day):
    _, session = get_session(None)
    p = plan(session)
    assert p["buildings_heated"] is True
    assert p["segments"][1]["temp_f"] == 72


def test_outfit_skips_laundry_and_handles_rain(cold_day):
    _, session = get_session(None)
    plan(session)
    run_tool("update_wardrobe", {"item_ids": ["parka-black"], "status": "in_laundry"}, session)
    result = json.loads(run_tool("build_outfit", {"occasion": "class"}, session))
    names = [i["name"] for i in result["options"][0]["items"]]
    assert "Black down parka" not in names
    assert "Black down parka" in result["skipped_in_laundry"]


def test_interview_prefers_formal_pieces(cold_day):
    _, session = get_session(None)
    plan(session)
    ids = [i["id"] for i in json.loads(run_tool("build_outfit", {"occasion": "interview"}, session))["options"][0]["items"]]
    assert "sweatpants-grey" not in ids and "hoodie-grey" not in ids


def test_mild_day_needs_no_coat(mild_day):
    _, session = get_session(None)
    plan(session)
    slots = [i["slot"] for i in json.loads(run_tool("build_outfit", {}, session))["options"][0]["items"]]
    assert "outer" not in slots


@pytest.mark.parametrize("args, fragment", [
    ({"segments": [{"start": "9am", "minutes": 20, "activity": "walking", "setting": "outdoors"}]}, "24-hour HH:MM"),
    ({"segments": [{"start": "09:00", "minutes": 20, "activity": "jogging", "setting": "outdoors"}]}, "Activity 'jogging'"),
    ({"segments": []}, "at least one segment"),
])
def test_errors_tell_the_model_what_to_fix(cold_day, args, fragment):
    _, session = get_session(None)
    assert fragment in json.loads(run_tool("plan_day_warmth", args, session))["error"]


def test_build_outfit_needs_a_plan_first():
    _, session = get_session(None)
    assert "plan_day_warmth" in json.loads(run_tool("build_outfit", {}, session))["error"]
