"""Offline checks for the closet tools: listing, and automatic laundry by wear limit."""

import json

from fastapi.testclient import TestClient

import app as app_module
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


def test_update_wardrobe_sets_and_clears_worn_by():
    _, session = get_session(None)
    result = json.loads(run_tool("update_wardrobe",
                                  {"item_ids": ["jeans-indigo"], "status": "worn", "worn_by": "Alex"}, session))
    assert session.wardrobe["jeans-indigo"]["worn_by"] == "Alex"
    assert result["updated"][0]["worn_by"] == "Alex"
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "clean"}, session)
    assert session.wardrobe["jeans-indigo"]["worn_by"] is None


def test_worn_by_does_not_stick_to_an_item_that_hits_its_wear_limit():
    # tee-white's wear limit is 1, so this call sends it straight to the laundry; nobody
    # "has" a laundered item, so worn_by should not be left set.
    _, session = get_session(None)
    run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "worn", "worn_by": "Alex"}, session)
    assert session.wardrobe["tee-white"]["status"] == "in_laundry"
    assert session.wardrobe["tee-white"]["worn_by"] is None


def test_list_wardrobe_reports_worn_by():
    _, session = get_session(None)
    items = {i["id"]: i for i in json.loads(run_tool("list_wardrobe", {}, session))["items"]}
    assert items["jeans-indigo"]["worn_by"] is None
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn", "worn_by": "Alex"}, session)
    items = {i["id"]: i for i in json.loads(run_tool("list_wardrobe", {}, session))["items"]}
    assert items["jeans-indigo"]["worn_by"] == "Alex"


def test_update_wardrobe_sets_and_clears_worn_for():
    _, session = get_session(None)
    result = json.loads(run_tool("update_wardrobe",
                                  {"item_ids": ["jeans-indigo"], "status": "worn", "worn_for": "tomorrow"}, session))
    assert session.wardrobe["jeans-indigo"]["worn_for"] == "tomorrow"
    assert result["updated"][0]["worn_for"] == "tomorrow"
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "clean"}, session)
    assert session.wardrobe["jeans-indigo"]["worn_for"] is None


def test_worn_for_does_not_gate_build_outfit_availability():
    # worn_for is a display label only; it doesn't exclude the item for anyone, unlike worn_by.
    _, session = get_session(None)
    session.last_plan = SHARED_PLAN
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn", "worn_for": "tomorrow"}, session)
    result = json.loads(run_tool("build_outfit", {"must_include": ["jeans-indigo"]}, session))
    assert "jeans-indigo" in {i["id"] for i in result["options"][0]["items"]}


def test_qty_defaults_to_one_and_is_exposed():
    _, session = get_session(None)
    items = {i["id"]: i for i in json.loads(run_tool("list_wardrobe", {}, session))["items"]}
    assert items["tee-white"]["qty"] == 1 and items["tee-white"]["qty_in_laundry"] == 0


def test_multi_unit_item_sends_one_unit_to_laundry_per_worn_call():
    # tee-white's wear limit is 1, so each "worn" call should dirty exactly one more unit.
    _, session = get_session(None)
    session.wardrobe["tee-white"]["qty"] = 3
    run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "worn"}, session)
    item = session.wardrobe["tee-white"]
    assert item["qty_in_laundry"] == 1 and item["status"] == "worn"  # 2 of 3 still available
    run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "worn"}, session)
    run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "worn"}, session)
    assert item["qty_in_laundry"] == 3 and item["status"] == "in_laundry"  # none left


def test_clean_status_fully_restocks_a_multi_unit_item():
    _, session = get_session(None)
    session.wardrobe["tee-white"]["qty"] = 3
    for _ in range(3):
        run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "worn"}, session)
    run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "clean"}, session)
    item = session.wardrobe["tee-white"]
    assert item["qty_in_laundry"] == 0 and item["wears"] == 0 and item["status"] == "clean"


def test_wardrobe_qty_endpoint_clamps_laundry_count_and_minimum():
    client = TestClient(app_module.app)
    sid = client.get("/wardrobe").json()["session_id"]
    client.post("/wardrobe/qty", json={"session_id": sid, "item_id": "tee-white", "qty": 3})
    client.post("/wardrobe/status", json={"session_id": sid, "item_ids": ["tee-white"], "status": "in_laundry"})
    client.post("/wardrobe/status", json={"session_id": sid, "item_ids": ["tee-white"], "status": "in_laundry"})
    res = client.post("/wardrobe/qty", json={"session_id": sid, "item_id": "tee-white", "qty": 1}).json()
    assert res["qty"] == 1 and res["qty_in_laundry"] == 1  # clamped down to match the lowered qty
    assert client.post("/wardrobe/qty", json={"session_id": sid, "item_id": "tee-white", "qty": 0}).json()["qty"] == 1


def test_wardrobe_unlaundry_endpoint_decrements_without_touching_wears():
    client = TestClient(app_module.app)
    sid = client.get("/wardrobe").json()["session_id"]
    client.post("/wardrobe/qty", json={"session_id": sid, "item_id": "tee-white", "qty": 2})
    client.post("/wardrobe/status", json={"session_id": sid, "item_ids": ["tee-white"], "status": "in_laundry"})
    client.post("/wardrobe/status", json={"session_id": sid, "item_ids": ["tee-white"], "status": "in_laundry"})
    res = client.post("/wardrobe/unlaundry", json={"session_id": sid, "item_id": "tee-white"}).json()
    assert res["qty_in_laundry"] == 1 and res["status"] == "clean"  # wears was never touched by "in_laundry" calls


SHARED_PLAN = {"summary": {"outdoor_clo_min": 0.6, "outdoor_clo_ideal": 0.9,
                            "indoor_clo_min": 0.4, "indoor_clo_ideal": 0.6, "max_wind_mph": 5}}


def test_partially_dirty_item_still_counts_as_available_to_build_outfit():
    # jeans' wear limit is 5, so one pair of 2 owned goes to the laundry well before
    # the item becomes fully unavailable.
    _, session = get_session(None)
    session.last_plan = SHARED_PLAN
    session.wardrobe["jeans-indigo"]["qty"] = 2
    for _ in range(5):
        run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn"}, session)
    item = session.wardrobe["jeans-indigo"]
    assert item["qty_in_laundry"] == 1 and item["status"] != "in_laundry"  # 1 of 2 still available
    result = json.loads(run_tool("build_outfit", {"must_include": ["jeans-indigo"]}, session))
    assert "jeans-indigo" in {i["id"] for i in result["options"][0]["items"]}


def test_build_outfit_for_whom_excludes_items_claimed_by_someone_else():
    _, session = get_session(None)
    session.last_plan = SHARED_PLAN
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn", "worn_by": "me"}, session)

    for_other = json.loads(run_tool("build_outfit", {"for_whom": "Alex"}, session))
    picked = {i["id"] for opt in for_other["options"] for i in opt["items"]}
    assert "jeans-indigo" not in picked
    assert "Indigo jeans" in for_other["claimed_by_someone_else"]

    for_me = json.loads(run_tool("build_outfit", {"for_whom": "me", "must_include": ["jeans-indigo"]}, session))
    assert "jeans-indigo" in {i["id"] for i in for_me["options"][0]["items"]}  # still available to its own wearer


def test_build_outfit_for_whom_still_offers_outerwear_and_shoes_someone_else_has_on():
    # Hygiene exclusion only applies to tops/bottoms/dresses/legwear/socks; a coat or shoes are
    # fine to suggest to someone else even while another person currently has them on.
    _, session = get_session(None)
    session.last_plan = SHARED_PLAN
    run_tool("update_wardrobe", {"item_ids": ["parka-black", "boots-leather"], "status": "worn", "worn_by": "me"},
             session)

    for_other = json.loads(run_tool("build_outfit", {"for_whom": "Alex", "must_include": ["parka-black", "boots-leather"]},
                                     session))
    picked = {i["id"] for i in for_other["options"][0]["items"]}
    assert {"parka-black", "boots-leather"} <= picked
    assert for_other["claimed_by_someone_else"] == []


def test_build_outfit_without_for_whom_ignores_worn_by():
    _, session = get_session(None)
    session.last_plan = SHARED_PLAN
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "worn", "worn_by": "Alex"}, session)
    result = json.loads(run_tool("build_outfit", {}, session))  # no for_whom: old single-person behavior
    assert result["claimed_by_someone_else"] == []
    # Still selectable (not silently filtered out) now that for_whom isn't in play, same as before this feature existed.
    forced = json.loads(run_tool("build_outfit", {"must_include": ["jeans-indigo"]}, session))
    assert "jeans-indigo" in {i["id"] for i in forced["options"][0]["items"]}


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
