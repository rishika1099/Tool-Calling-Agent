"""Offline checks for the closet tools: listing, and automatic laundry by wear limit."""

import json

from app import get_session
from tools import run_tool
from tools.catalog import wear_limit


def test_list_wardrobe_reports_wear_limit():
    _, session = get_session(None)
    items = {i["id"]: i for i in json.loads(run_tool("list_wardrobe", {}, session))["items"]}
    assert items["tee-white"]["wear_limit"] == 1
    assert items["parka-black"]["wear_limit"] == 10


def test_worn_item_goes_to_laundry_at_its_wear_limit():
    # A t-shirt's wear limit is 1, so one "worn" update should send it straight to the laundry.
    _, session = get_session(None)
    assert wear_limit(session.wardrobe["tee-white"]) == 1

    result = json.loads(run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "worn"}, session))
    assert session.wardrobe["tee-white"]["status"] == "in_laundry"
    assert session.wardrobe["tee-white"]["wears"] == 1
    assert "White cotton tee" in result["note"]
    assert result["updated"][0]["status"] == "in_laundry"


def test_worn_item_stays_worn_below_its_wear_limit():
    # Jeans have a wear limit of 5, so they stay "worn" (not laundry) after one wear.
    _, session = get_session(None)
    assert wear_limit(session.wardrobe["jeans-indigo"]) == 5

    result = json.loads(run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn"}, session))
    assert session.wardrobe["jeans-indigo"]["status"] == "worn"
    assert "note" not in result


def test_marking_clean_resets_wears():
    _, session = get_session(None)
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn"}, session)
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "clean"}, session)
    assert session.wardrobe["jeans-indigo"]["status"] == "clean"
    assert session.wardrobe["jeans-indigo"]["wears"] == 0


def test_repeated_wears_eventually_trigger_laundry():
    _, session = get_session(None)
    for _ in range(4):
        result = json.loads(run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn"}, session))
        assert "note" not in result
    result = json.loads(run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn"}, session))
    assert session.wardrobe["jeans-indigo"]["status"] == "in_laundry"
    assert "note" in result


def test_manual_laundry_toggle_is_unaffected_by_wear_limit():
    _, session = get_session(None)
    result = json.loads(run_tool("update_wardrobe", {"item_ids": ["parka-black"], "status": "in_laundry"}, session))
    assert session.wardrobe["parka-black"]["status"] == "in_laundry"
    assert session.wardrobe["parka-black"]["wears"] == 0  # a direct laundry toggle doesn't count as a wear
    assert "note" not in result


def test_interview_outfit_is_dressed_up():
    """A cool day, jeans in the wash: the interview pick is tailored, not a puffer, sweatpants or sneakers."""
    _, session = get_session(None)
    session.wardrobe["jeans-indigo"]["status"] = "in_laundry"
    session.last_plan = {"summary": {"outdoor_clo_min": 1.05, "outdoor_clo_ideal": 1.42, "indoor_clo_min": 0.83,
                                     "indoor_clo_ideal": 1.17, "max_wind_mph": 7}}
    options = json.loads(run_tool("build_outfit", {"occasion": "interview"}, session))["options"]
    best = {item["id"] for item in options[0]["items"]}
    assert "trousers-black" in best and best & {"shirt-white", "shirt-oxford"}
    assert best & {"coat-charcoal", "coat-camel", "trench-beige"}  # a tailored layer on top
    assert not best & {"parka-black", "puffer-sage", "sneakers-white", "sweatpants-grey", "hoodie-grey"}
    for option in options:
        ids = {item["id"] for item in option["items"]}
        assert not {"coat-camel", "jacket-denim"} <= ids  # never a blazer under a denim jacket
