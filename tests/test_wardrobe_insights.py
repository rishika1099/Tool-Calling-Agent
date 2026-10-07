"""Offline checks for the proactive wardrobe-reasoning tools: gaps, laundry, and wear stats."""

import json

from app import get_session
from tools import run_tool
from tools.catalog import slot

RAIN_WIND_PLAN = {"summary": {"outdoor_clo_min": 0.6, "outdoor_clo_ideal": 0.9, "indoor_clo_min": 0.4,
                               "indoor_clo_ideal": 0.6, "max_wind_mph": 20, "rain_expected": True,
                               "snow_expected": False}}
MILD_PLAN = {"summary": {"outdoor_clo_min": 0.6, "outdoor_clo_ideal": 0.9, "indoor_clo_min": 0.4,
                          "indoor_clo_ideal": 0.6, "max_wind_mph": 3, "rain_expected": False,
                          "snow_expected": False}}


def test_suggest_wardrobe_gaps_requires_a_plan():
    _, session = get_session(None)
    result = json.loads(run_tool("suggest_wardrobe_gaps", {}, session))
    assert "error" in result


def test_suggest_wardrobe_gaps_flags_missing_waterproof_windproof_coat():
    _, session = get_session(None)
    session.last_plan = RAIN_WIND_PLAN
    # Only the two outers with neither property stay available.
    for item in session.wardrobe.values():
        if slot(item) == "outer" and item["id"] not in ("coat-charcoal", "jacket-denim"):
            item["status"] = "in_laundry"
    result = json.loads(run_tool("suggest_wardrobe_gaps", {}, session))
    assert any("waterproof" in g for g in result["gaps"])
    assert any("windproof" in g for g in result["gaps"])


def test_suggest_wardrobe_gaps_finds_nothing_wrong_with_a_well_covered_closet():
    _, session = get_session(None)
    session.last_plan = MILD_PLAN
    result = json.loads(run_tool("suggest_wardrobe_gaps", {}, session))
    assert result["gaps"] == []


def test_suggest_wardrobe_gaps_flags_no_coat_at_all():
    _, session = get_session(None)
    session.last_plan = MILD_PLAN
    for item in session.wardrobe.values():
        if slot(item) == "outer":
            item["status"] = "in_laundry"
    result = json.loads(run_tool("suggest_wardrobe_gaps", {}, session))
    assert any("No coat or jacket" in g for g in result["gaps"])


def test_plan_laundry_reports_nothing_running_low_on_a_fresh_closet():
    _, session = get_session(None)
    result = json.loads(run_tool("plan_laundry", {}, session))
    assert result["running_low"] == []
    assert result["by_category"]["base_top"]["clean_units"] == result["by_category"]["base_top"]["owned_units"]


def test_plan_laundry_flags_a_category_running_low():
    _, session = get_session(None)
    for item in session.wardrobe.values():
        if slot(item) == "base_top":
            item["status"] = "in_laundry"
            item["qty_in_laundry"] = item.get("qty", 1)
    result = json.loads(run_tool("plan_laundry", {}, session))
    assert any("base top" in note for note in result["running_low"])
    assert result["by_category"]["base_top"]["clean_units"] == 0


def test_wardrobe_stats_starts_with_everything_never_worn():
    _, session = get_session(None)
    result = json.loads(run_tool("wardrobe_stats", {}, session))
    assert result["most_worn"] == []
    assert result["never_worn_count"] == result["total_items"]


def test_wardrobe_stats_tracks_lifetime_wears_across_a_laundry_cycle():
    # lifetime_wears should keep counting even after "clean" resets the current wash cycle's
    # wears counter - that's the whole point of it being a separate field.
    _, session = get_session(None)
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn"}, session)
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "clean"}, session)
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn"}, session)
    assert session.wardrobe["jeans-indigo"]["wears"] == 1  # reset by "clean" in between
    assert session.wardrobe["jeans-indigo"]["lifetime_wears"] == 2  # never reset

    result = json.loads(run_tool("wardrobe_stats", {}, session))
    assert result["most_worn"][0] == {"id": "jeans-indigo", "name": "Indigo jeans", "lifetime_wears": 2}
