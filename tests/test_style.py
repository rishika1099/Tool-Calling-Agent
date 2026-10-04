"""Offline checks for the style rules: color, shape, pattern, occasion, and the style_check tool."""

import json
import time

import pytest
from test_warmth import DAY, fake_day

from app import get_session
from tools import TOOLS, outfit, run_tool, style, warmth
from tools.style import style_score


def item(name, garment_type, color, fit="relaxed", pattern="solid", formality=1, **extra):
    return {"id": name.lower().replace(" ", "-"), "name": name, "garment_type": garment_type, "color": color,
            "fit": fit, "pattern": pattern, "formality": formality, "status": "clean", "wears": 0, **extra}


JEANS = item("Jeans", "jeans", "#2E3F63", fit="fitted")
WHITE_TEE = item("White tee", "t_shirt", "#F2F0EA", fit="fitted")
RED_TEE = item("Red tee", "t_shirt", "#C0392B", fit="fitted")
GREEN_PANTS = item("Green trousers", "trousers_thin", "#2E9B4F", fit="fitted")
PURPLE_PANTS = item("Purple trousers", "trousers_thin", "#7A3FA0", fit="fitted")
ORANGE_TEE = item("Orange tee", "t_shirt", "#F28C28", fit="fitted")
BLUE_PANTS = item("Blue trousers", "trousers_thin", "#2F6FD0", fit="fitted")


def check(session, ids=None, **args):
    if ids is not None:
        args["item_ids"] = ids
    return json.loads(run_tool("style_check", args, session))


# --- Shape of the result ---


def test_score_is_out_of_ten_with_one_reason_per_rule():
    result = style_score([WHITE_TEE, JEANS], "class")
    assert result["score"] == 10.0 and result["verdict"] == "goes together"
    assert list(result["breakdown"]) == ["color", "shape", "pattern", "occasion"]
    assert sum(result["breakdown"].values()) == pytest.approx(result["score"])
    assert [r.split()[0] for r in result["reasons"]] == ["Color", "Shape", "Pattern", "Occasion"]
    assert sum(style.POINTS.values()) == 10


def test_same_outfit_always_gets_the_same_score():
    assert style_score([RED_TEE, GREEN_PANTS], "class") == style_score([RED_TEE, GREEN_PANTS], "class")


# --- Color ---


def test_neutrals_go_with_anything():
    for hex_color, tone in [("#151515", "black"), ("#F4F4F0", "white"), ("#8A8D91", "grey"), ("#22314F", "navy"),
                            ("#E8DCC4", "cream"), ("#B08A5B", "camel"), ("#5C3A21", "brown"), ("#5E6B45", "olive")]:
        assert style._tone(hex_color, False)[:2] == (tone, None)
    assert style._tone("#5A7BA6", True)[:2] == ("denim blue", None)   # blue denim counts as a neutral
    assert style._tone("#5A7BA6", False)[0] == "blue"                 # the same blue in another fabric does not
    assert style_score([RED_TEE, JEANS], "class")["breakdown"]["color"] == style.POINTS["color"]


def test_neighbors_and_opposites_on_the_color_wheel_are_fine_but_in_between_clashes():
    full = style.POINTS["color"]
    pink_top = item("Pink top", "t_shirt", "#E0457B", fit="fitted")
    red_pants = item("Red trousers", "trousers_thin", "#C0392B", fit="fitted")
    assert style_score([pink_top, red_pants], "class")["breakdown"]["color"] == full       # analogous
    assert style_score([ORANGE_TEE, BLUE_PANTS], "class")["breakdown"]["color"] == full    # complementary

    clash = style_score([RED_TEE, PURPLE_PANTS], "class")                                  # about 90 degrees apart
    assert clash["breakdown"]["color"] < full * 0.6
    assert "Red tee" in clash["reasons"][0] and "Purple trousers" in clash["reasons"][0]
    assert clash["verdict"] == "works with a tweak"

    contrast = style_score([ORANGE_TEE, GREEN_PANTS], "class")                             # about 110: bold, not a clash
    assert clash["breakdown"]["color"] < contrast["breakdown"]["color"] < full


def test_muted_colors_clash_less_than_vivid_ones():
    dusty_rose = item("Dusty rose tee", "t_shirt", "#C9A0A0", fit="fitted")
    lavender = item("Lavender trousers", "trousers_thin", "#B7A0C9", fit="fitted")
    vivid = style_score([RED_TEE, PURPLE_PANTS], "class")["breakdown"]["color"]
    muted = style_score([dusty_rose, lavender], "class")["breakdown"]["color"]
    assert vivid < muted < style.POINTS["color"]


def test_a_missing_or_bad_color_is_treated_as_grey_not_a_crash():
    no_color = {"name": "Mystery top", "garment_type": "t_shirt"}
    bad_color = item("Odd top", "t_shirt", "not-a-color")
    assert style_score([no_color, JEANS], "class")["score"] == 10.0
    assert style_score([bad_color, JEANS], "class")["score"] == 10.0


# --- Shape ---


def test_full_skirt_wants_a_fitted_top_not_an_oversized_one():
    skirt = item("Maxi skirt", "long_skirt", "#6B4A36", fit="relaxed")
    oversized = item("Big sweater", "sweater_thick", "#E8DCC4", fit="oversized")
    relaxed = item("Easy sweater", "sweater_thick", "#E8DCC4", fit="relaxed")
    fitted = style_score([WHITE_TEE, skirt], "class")
    tucked = style_score([relaxed, skirt], "class")
    baggy = style_score([oversized, skirt], "class")
    assert fitted["breakdown"]["shape"] > tucked["breakdown"]["shape"] > baggy["breakdown"]["shape"]
    assert "tuck" in tucked["reasons"][1]
    assert baggy["verdict"] == "does not go together"


def test_wide_leg_pants_follow_the_same_rule():
    wide = item("Wide trousers", "trousers_thin", "#232323", fit="oversized")
    oversized = item("Big tee", "t_shirt", "#F2F0EA", fit="oversized")
    assert style_score([WHITE_TEE, wide], "class")["breakdown"]["shape"] == style.POINTS["shape"]
    assert style_score([oversized, wide], "class")["breakdown"]["shape"] < 1


def test_fitted_coat_over_an_oversized_layer_loses_points():
    hoodie = item("Big hoodie", "hoodie", "#8A8D91", fit="oversized")
    slim_coat = item("Slim coat", "wool_coat", "#151515", fit="fitted")
    roomy_coat = item("Roomy coat", "wool_coat", "#151515", fit="relaxed")
    slim = style_score([WHITE_TEE, hoodie, JEANS, slim_coat], "class")
    roomy = style_score([WHITE_TEE, hoodie, JEANS, roomy_coat], "class")
    assert slim["breakdown"]["shape"] < roomy["breakdown"]["shape"]
    assert "bunch" in slim["reasons"][1]


# --- Pattern ---


def test_at_most_one_bold_pattern():
    plaid_shirt = item("Plaid shirt", "flannel_shirt", "#9E3B32", pattern="bold")
    striped_pants = item("Striped trousers", "trousers_thin", "#232323", fit="fitted", pattern="bold")
    one = style_score([plaid_shirt, JEANS], "class")
    two = style_score([plaid_shirt, striped_pants], "class")
    assert one["breakdown"]["pattern"] == style.POINTS["pattern"]
    assert two["breakdown"]["pattern"] < style.POINTS["pattern"] / 2
    assert "Plaid shirt" in two["reasons"][2] and "Striped trousers" in two["reasons"][2]
    assert two["verdict"] == "works with a tweak"


# --- Occasion ---


def test_formality_has_to_reach_the_occasion():
    assert style_score([WHITE_TEE, JEANS], "class")["breakdown"]["occasion"] == style.POINTS["occasion"]
    interview = style_score([WHITE_TEE, JEANS], "interview")
    assert interview["breakdown"]["occasion"] == 0
    assert interview["verdict"] == "does not go together"
    assert "too casual for an interview" in interview["reasons"][3]


def test_occasions_match_the_outfit_builder():
    assert style.OCCASIONS == outfit.OCCASIONS
    schema = next(t for t in TOOLS if t["function"]["name"] == "style_check")["function"]["parameters"]
    assert schema["properties"]["occasion"]["enum"] == list(outfit.OCCASIONS)


def test_oxford_shirt_with_sweatpants_is_flagged():
    """GitHub issue #10: the weak pick style_check has to fix."""
    _, session = get_session(None)
    weak = check(session, ["shirt-oxford", "sweatpants-grey"])
    better = check(session, ["shirt-oxford", "jeans-indigo"])
    assert weak["verdict"] == "works with a tweak" and better["verdict"] == "goes together"
    assert weak["score"] < better["score"]
    assert "dress codes" in weak["reasons"][3]


# --- What counts as visible ---


def test_socks_and_hidden_leggings_do_not_affect_the_score():
    neon_socks = item("Neon socks", "socks", "#39FF14", pattern="bold")
    neon_leggings = item("Neon leggings", "thermal_leggings", "#FF00AA", pattern="bold")
    base = style_score([RED_TEE, JEANS], "class")
    assert style_score([RED_TEE, JEANS, neon_socks, neon_leggings], "class") == base
    # Under a skirt the leggings show, so now they count (here: a second bold pattern).
    skirt = item("Plaid skirt", "skirt_thick", "#2E9B4F", fit="fitted", pattern="bold")
    assert style_score([WHITE_TEE, skirt, neon_leggings], "class")["score"] < style_score([WHITE_TEE, skirt], "class")["score"]


# --- The tool ---


def test_style_check_scores_a_proposed_outfit():
    _, session = get_session(None)
    result = check(session, ["shirt-flannel", "skirt-maxi"])
    assert result["items"] == ["Red plaid flannel", "Brown pleated maxi skirt"]
    assert result["occasion"] == "class"
    assert 0 <= result["score"] <= 10 and len(result["reasons"]) == 4


def test_style_check_errors_tell_the_model_what_to_do():
    _, session = get_session(None)
    assert "list_wardrobe" in check(session, ["no-such-item"])["error"]
    assert "at least two" in check(session, ["tee-white"])["error"]
    assert "at least two" in check(session, ["tee-white", "socks-wool"])["error"]  # socks are not visible
    assert "occasion must be one of" in check(session, ["tee-white", "jeans-indigo"], occasion="gala")["error"]
    assert "build_outfit" in check(session)["error"]  # no ids and no outfit picked yet


def test_style_check_defaults_to_the_last_outfit_and_notes_laundry():
    _, session = get_session(None)
    session.last_outfit = ["tee-white", "jeans-indigo", "parka-black"]
    session.wardrobe["jeans-indigo"]["status"] = "in_laundry"
    result = check(session)
    assert result["items"] == ["White cotton tee", "Indigo jeans", "Black down parka"]
    assert "Indigo jeans" in result["note"]


# --- Working with build_outfit ---


@pytest.fixture
def cool_day(monkeypatch):
    monkeypatch.setattr(warmth, "hourly_for_day", fake_day(8.0))
    monkeypatch.setattr(warmth, "active_alerts", lambda place: [])


def test_build_outfit_uses_the_style_score(cool_day):
    _, session = get_session(None)
    session.cold_sensitivity = "runs_warm"  # the setup that used to pick the oxford shirt with sweatpants
    run_tool("plan_day_warmth", {"segments": DAY}, session)
    result = json.loads(run_tool("build_outfit", {}, session))
    assert result["style_check"] == "on"
    best = result["options"][0]
    assert best["style"]["score"] >= 8
    ids = {i["id"] for i in best["items"]}
    assert not {"shirt-oxford", "sweatpants-grey"} <= ids


def test_scoring_every_candidate_outfit_is_fast():
    _, session = get_session(None)
    combos = list(outfit._combos([i for i in session.wardrobe.values() if outfit.slot(i) not in ("head", "hands", "neck")]))
    assert len(combos) > 1000
    style._score.cache_clear()
    start = time.perf_counter()
    for combo in combos:
        style_score(combo, "class")
    assert time.perf_counter() - start < 2.0  # about 0.3 s on a laptop; generous for slow CI
