"""Offline checks for the closet tools: listing, and automatic laundry by wear limit."""

import json

from fastapi.testclient import TestClient

import app as app_module
from app import get_session
from tools import run_tool
from tools.catalog import slot, wear_limit


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


def test_manual_laundry_toggle_still_counts_as_a_lifetime_wear():
    # Reported: tapping a closet tile straight to "in the wash" (no "worn" call first, e.g. the
    # closet panel's own tap-to-toggle) left wardrobe_stats calling the item "never worn" even
    # though sending something to the wash means it was used.
    _, session = get_session(None)
    run_tool("update_wardrobe", {"item_ids": ["shirt-flannel"], "status": "in_laundry"}, session)
    assert session.wardrobe["shirt-flannel"]["lifetime_wears"] == 1
    assert session.wardrobe["shirt-flannel"]["wears"] == 0  # still unaffected, per the test above

    # A second toggle on an item already fully in the laundry doesn't count again.
    run_tool("update_wardrobe", {"item_ids": ["shirt-flannel"], "status": "in_laundry"}, session)
    assert session.wardrobe["shirt-flannel"]["lifetime_wears"] == 1


def test_update_wardrobe_sets_and_clears_worn_by():
    _, session = get_session(None)
    result = json.loads(run_tool("update_wardrobe",
                                  {"item_ids": ["jeans-indigo"], "status": "worn", "worn_by": "Alex"}, session))
    assert session.wardrobe["jeans-indigo"]["worn_by"] == "Alex"
    assert result["updated"][0]["worn_by"] == "Alex"
    run_tool("update_wardrobe", {"item_ids": ["jeans-indigo"], "status": "clean"}, session)
    assert session.wardrobe["jeans-indigo"]["worn_by"] is None


def test_worn_by_still_tags_an_item_on_the_call_that_reaches_its_wear_limit():
    # tee-white's wear limit is 1, so this call sends it straight to the laundry - but Alex is
    # wearing it *right now*, today, even though it also needs a wash after, so the tag should
    # still show who has it instead of silently vanishing the moment it's marked worn.
    _, session = get_session(None)
    run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "worn", "worn_by": "Alex"}, session)
    assert session.wardrobe["tee-white"]["status"] == "in_laundry"
    assert session.wardrobe["tee-white"]["worn_by"] == "Alex"


def test_worn_by_does_not_stick_to_an_item_already_fully_in_the_laundry():
    # A second "worn" call on an item that was already at its wear limit (no clean units left)
    # isn't "being worn right now" in any meaningful sense - nobody picked up a dirty item.
    _, session = get_session(None)
    run_tool("update_wardrobe", {"item_ids": ["tee-white"], "status": "worn", "worn_by": "Alex"}, session)
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


def test_worn_for_also_still_tags_an_item_on_the_call_that_reaches_its_wear_limit():
    _, session = get_session(None)
    result = json.loads(run_tool("update_wardrobe",
                                  {"item_ids": ["tee-white"], "status": "worn", "worn_by": "me", "worn_for": "today"},
                                  session))
    assert session.wardrobe["tee-white"]["status"] == "in_laundry"
    assert session.wardrobe["tee-white"]["worn_for"] == "today"
    assert result["updated"][0]["worn_for"] == "today"


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


def test_build_outfit_result_carries_its_own_date_and_for_whom():
    # The frontend pairs each build_outfit result with its own day and person directly from the
    # result itself (not by tracking the most recent plan_day_warmth/for_whom seen in call order),
    # so a multi-day or multi-person answer tags the right day and name even if the model doesn't
    # call plan_day_warmth immediately before every build_outfit.
    _, session = get_session(None)
    session.last_plan = {**SHARED_PLAN, "date": "2026-10-09"}
    result = json.loads(run_tool("build_outfit", {"for_whom": "Alex"}, session))
    assert result["date"] == "2026-10-09"
    assert result["for_whom"] == "Alex"

    no_for_whom = json.loads(run_tool("build_outfit", {}, session))
    assert no_for_whom["for_whom"] == "me"  # defaults to "me" when omitted (single-user case)


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


def test_build_outfit_steers_a_different_for_whom_away_from_the_same_items():
    # Asked about two people in the same reply, before either has actually claimed anything with
    # update_wardrobe: the second person's build_outfit call should automatically avoid repeating
    # the first person's exact picks - every slot, not just hygiene ones. Reported: both people
    # got offered the same single pair of boots for the same day, which is physically impossible
    # regardless of whether shoes need a hygiene wash between wearers.
    _, session = get_session(None)
    session.last_plan = SHARED_PLAN
    me = json.loads(run_tool("build_outfit", {"for_whom": "me"}, session))
    me_ids = {i["id"] for i in me["options"][0]["items"]}

    alex = json.loads(run_tool("build_outfit", {"for_whom": "Alex"}, session))
    alex_ids = {i["id"] for i in alex["options"][0]["items"]}
    # No single-copy item is shared between the two picks. Pieces owned in multiples (the demo
    # closet has several pairs of socks) can go to both people.
    assert not {i for i in me_ids & alex_ids if session.wardrobe[i]["qty"] == 1}


def test_recent_picks_keeps_a_separate_entry_per_day_not_just_per_person():
    # Reported: asked for two people across two days in one message, the same top and bottom got
    # offered to both people on BOTH days. Root cause: recent_picks was keyed by for_whom alone,
    # so building the same person's day 2 overwrote and lost the record of their day 1 pick before
    # the other person's day 1 build ever ran - exactly what happens if the model finishes one
    # person's whole multi-day plan before starting the other's, rather than strictly alternating
    # day-by-day between people (which the prompt asks for, but can't be relied on alone).
    _, session = get_session(None)
    session.last_plan = {**SHARED_PLAN, "date": "2026-10-07"}
    run_tool("build_outfit", {"for_whom": "me"}, session)
    day1_picks = session.recent_picks.get(("me", "2026-10-07"))
    assert day1_picks  # stored under a day-specific key

    session.last_plan = {**SHARED_PLAN, "date": "2026-10-08"}
    run_tool("build_outfit", {"for_whom": "me"}, session)
    # Day 1's entry must still be there, unchanged - not overwritten by day 2's build for the same
    # person, which is exactly what the old for_whom-only key did.
    assert session.recent_picks.get(("me", "2026-10-07")) == day1_picks
    assert session.recent_picks.get(("me", "2026-10-08"))


def test_build_outfit_avoids_overlap_on_an_earlier_day_even_after_a_later_day_is_built():
    # Behavioral version of the test above: the earlier day's protection must still be live by
    # the time the other person's build for that same earlier day actually runs.
    _, session = get_session(None)
    for item in session.wardrobe.values():
        if slot(item) == "bottom" and item["id"] != "jeans-indigo":
            item["status"] = "in_laundry"  # jeans-indigo is the only bottom left

    session.last_plan = {**SHARED_PLAN, "date": "2026-10-07"}
    me_day1 = json.loads(run_tool("build_outfit", {"for_whom": "me"}, session))
    assert "jeans-indigo" in {i["id"] for i in me_day1["options"][0]["items"]}  # only bottom available

    session.last_plan = {**SHARED_PLAN, "date": "2026-10-08"}
    run_tool("build_outfit", {"for_whom": "me"}, session)  # me's day 2 - must not clobber day 1's record

    session.last_plan = {**SHARED_PLAN, "date": "2026-10-07"}
    sister_day1 = json.loads(run_tool("build_outfit", {"for_whom": "sister"}, session))
    # jeans-indigo is still the only bottom in the whole closet, so sister either gets a dress
    # instead (correctly avoiding it) or the request fails outright - never jeans-indigo itself.
    assert "jeans-indigo" not in {i["id"] for i in sister_day1["options"][0]["items"]}


def test_build_outfit_avoids_repeating_the_same_persons_top_and_bottom_two_days_running():
    # Reported: the same person got offered the exact same top+bottom two days in a row even
    # though nothing requires reusing them (no scarcity, no hygiene issue with your own clothes) -
    # purely a variety preference, distinct from the cross-person/same-day physical-conflict check.
    _, session = get_session(None)
    session.last_plan = {**SHARED_PLAN, "date": "2026-10-07"}
    day1 = json.loads(run_tool("build_outfit", {"for_whom": "me"}, session))
    day1_core = {i["id"] for i in day1["options"][0]["items"] if i["slot"] in ("base_top", "bottom", "one_piece")}

    session.last_plan = {**SHARED_PLAN, "date": "2026-10-08"}
    day2 = json.loads(run_tool("build_outfit", {"for_whom": "me"}, session))
    day2_core = {i["id"] for i in day2["options"][0]["items"] if i["slot"] in ("base_top", "bottom", "one_piece")}
    assert not (day1_core & day2_core)


def test_build_outfit_variety_check_applies_even_without_for_whom():
    # "me or anyone": the variety guard should work for a plain single-user conversation too, not
    # just when for_whom is explicitly passed for a shared closet.
    _, session = get_session(None)
    session.last_plan = {**SHARED_PLAN, "date": "2026-10-07"}
    day1 = json.loads(run_tool("build_outfit", {}, session))
    day1_core = {i["id"] for i in day1["options"][0]["items"] if i["slot"] in ("base_top", "bottom", "one_piece")}

    session.last_plan = {**SHARED_PLAN, "date": "2026-10-08"}
    day2 = json.loads(run_tool("build_outfit", {}, session))
    day2_core = {i["id"] for i in day2["options"][0]["items"] if i["slot"] in ("base_top", "bottom", "one_piece")}
    assert not (day1_core & day2_core)


def test_build_outfit_variety_check_backs_off_when_nothing_else_is_available():
    # Repeating is sometimes unavoidable without an actual laundry cycle - the soft variety
    # preference shouldn't block a valid answer outright when the closet is this scarce.
    _, session = get_session(None)
    for item in session.wardrobe.values():
        if slot(item) in ("base_top", "bottom", "one_piece") and item["id"] not in ("tee-white", "jeans-indigo"):
            item["status"] = "in_laundry"

    session.last_plan = {**SHARED_PLAN, "date": "2026-10-07"}
    day1 = json.loads(run_tool("build_outfit", {"for_whom": "me"}, session))
    assert {"tee-white", "jeans-indigo"} <= {i["id"] for i in day1["options"][0]["items"]}

    session.last_plan = {**SHARED_PLAN, "date": "2026-10-08"}
    day2 = json.loads(run_tool("build_outfit", {"for_whom": "me"}, session))
    assert "error" not in day2
    assert {"tee-white", "jeans-indigo"} <= {i["id"] for i in day2["options"][0]["items"]}


def test_build_outfit_allows_sharing_an_item_owned_in_multiples():
    # Owning 2 of something (set from the closet panel) means two people can legitimately both
    # get offered it - the soft avoid-duplicate check should only kick in once every owned unit
    # is already claimed, not on the first match. boots-leather is made the only available shoe
    # so a wrongly-excluded version of this would show up as a missing shoe, not an error (shoes
    # aren't a required slot), making the difference directly observable without must_include
    # (which would mask it: an empty scored list falls back to ignoring the avoid-set entirely).
    _, session = get_session(None)
    session.last_plan = SHARED_PLAN
    session.wardrobe["boots-leather"]["qty"] = 2
    for item in session.wardrobe.values():
        if slot(item) == "shoes" and item["id"] != "boots-leather":
            item["status"] = "in_laundry"

    me = json.loads(run_tool("build_outfit", {"for_whom": "me"}, session))
    assert "boots-leather" in {i["id"] for i in me["options"][0]["items"]}

    alex = json.loads(run_tool("build_outfit", {"for_whom": "Alex"}, session))
    assert "boots-leather" in {i["id"] for i in alex["options"][0]["items"]}


def test_build_outfit_overlap_avoidance_backs_off_when_nothing_else_is_available():
    # If honoring the soft avoidance would leave no outfit at all, it's dropped rather than
    # failing the call outright - a small closet shouldn't hard-break over a soft preference.
    _, session = get_session(None)
    session.last_plan = SHARED_PLAN
    for item in session.wardrobe.values():
        if slot(item) in ("base_top", "bottom", "one_piece") and item["id"] not in ("tee-white", "jeans-indigo"):
            item["status"] = "in_laundry"

    me = json.loads(run_tool("build_outfit", {"for_whom": "me", "must_include": ["tee-white", "jeans-indigo"]}, session))
    assert {"tee-white", "jeans-indigo"} <= {i["id"] for i in me["options"][0]["items"]}

    # The only clean top and bottom in the whole closet are the ones "me" just got - Alex's call
    # must still succeed, reusing them, instead of erroring with "no complete outfit available".
    alex = json.loads(run_tool("build_outfit", {"for_whom": "Alex"}, session))
    assert "error" not in alex
    assert {"tee-white", "jeans-indigo"} <= {i["id"] for i in alex["options"][0]["items"]}


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
