"""Pick outfits from the user's closet that meet the day plan, and keep the closet up to date.

Shared by all three owners: warmth needs come from plan_day_warmth, garment data
from scan_garment, and the style score from style.style_score.
"""

import itertools
import json
from collections import Counter

from . import style
from .catalog import INDOOR_SLOTS, clo, is_windproof, keeps_rain_out, slot, wear_limit, wet_retention

UNDERWEAR_CLO = 0.04  # assumed, not tracked in the closet
BARE_LEG_TYPES = {"skirt_thin", "skirt_thick", "dress_thin", "dress_thick", "shorts"}
COLD_DAY_CLO = 0.7  # outdoor warmth needed above which the warm socks go on
VARIETY_SLACK = 0.2  # penalty an option may give up to repeat fewer pieces from the others
VARIETY_WINDOW = 4000  # how far down the ranking to look for that
MAX_STYLED = 40000  # most outfits to style-score in one search
STYLE_WEIGHT = 0.25  # penalty per style point lost (out of 10)
SHORT_JACKETS = {"denim_jacket", "bomber_jacket", "leather_jacket"}
OCCASIONS = {"everyday": 1, "class": 1, "date": 2, "dinner": 2, "party": 2, "work": 2, "interview": 3}  # minimum formality
WINDY_MPH = 12
WINDPROOF_BONUS = 0.10  # team estimate: a windproof outer layer keeps ~10% more warmth in wind
SKIRTS = {"skirt_thin", "skirt_thick", "long_skirt"}
TIGHTS = {"tights", "fleece_tights"}
ACCESSORY_ORDER = ["gloves", "beanie", "scarf"]
LAYER_COST = 0.08  # small cost per optional layer, so we never add layers that don't help
STATUSES = ["clean", "worn", "in_laundry"]
# Worn against skin: not shared between people in a closet until laundered, unlike outer/shoes/accessories.
HYGIENE_SLOTS = {"base_top", "bottom", "one_piece", "legwear", "socks"}


def _by_slot(items: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(slot(item), []).append(item)
    return grouped


def _combos(items: list[dict]):
    """Every sensible outfit: a top and bottom (or a one-piece) plus optional layers."""
    g = _by_slot(items)
    cores = [(top, bottom) for top in g.get("base_top", []) for bottom in g.get("bottom", [])]
    cores += [(dress, None) for dress in g.get("one_piece", [])]
    for (core, bottom), mid, outer, leg, sock, shoe in itertools.product(
        cores,
        [None, *g.get("mid_top", [])],
        [None, *g.get("outer", [])],
        [None, *g.get("legwear", [])],
        g.get("socks") or [None],
        g.get("shoes") or [None],
    ):
        if leg and leg["garment_type"] in TIGHTS and bottom and bottom["garment_type"] not in SKIRTS:
            continue  # tights go under skirts and dresses, not jeans
        if mid and outer and mid["garment_type"] == "blazer" and outer["garment_type"] in SHORT_JACKETS:
            continue  # a blazer goes under a coat, not under another short jacket
        yield [x for x in (core, bottom, mid, outer, leg, sock, shoe) if x]


def _outermost(outfit: list[dict]) -> dict:
    for s in ("outer", "mid_top", "one_piece", "base_top"):
        for item in outfit:
            if slot(item) == s:
                return item
    return outfit[0]


def _evaluate(outfit: list[dict], summary: dict, occasion: str, with_style: bool = True) -> dict:
    """Indoor and outdoor warmth of an outfit against the plan, with a penalty (lower is better)."""
    notes = []
    slots = [slot(i) for i in outfit]
    indoor = UNDERWEAR_CLO + sum(clo(i) for i, s in zip(outfit, slots) if s in INDOOR_SLOTS)
    outer = outfit[slots.index("outer")] if "outer" in slots else None
    outdoor = indoor + (clo(outer) if outer else 0.0)
    penalty = 0.0

    if summary.get("rain_expected") or summary.get("snow_expected"):
        if not (outer and keeps_rain_out(outer)):
            top = _outermost(outfit)
            loss = clo(top) * (1 - wet_retention(top))
            outdoor -= loss
            if loss >= 0.05:
                notes.append(f"{top['name']} will get wet and lose about {loss:.2f} clo of warmth")
        shoes = next((i for i in outfit if slot(i) == "shoes"), None)
        if shoes and not keeps_rain_out(shoes):
            penalty += 0.3
            notes.append(f"{shoes['name']} will let water in")
    if summary.get("max_wind_mph", 0) >= WINDY_MPH and outer and is_windproof(outer):
        outdoor *= 1 + WINDPROOF_BONUS
        notes.append(f"{outer['name']} blocks the wind")

    if summary.get("outdoor_clo_min") is not None:
        penalty += 10 * max(0.0, summary["outdoor_clo_min"] - outdoor)
        penalty += 3 * max(0.0, summary["outdoor_clo_ideal"] - outdoor)
        penalty += 1 * max(0.0, outdoor - summary["outdoor_clo_ideal"] - 0.3)
    if summary.get("indoor_clo_min") is not None:
        penalty += 3 * max(0.0, summary["indoor_clo_min"] - indoor)
        penalty += 2 * max(0.0, indoor - summary["indoor_clo_ideal"] - 0.25)

    penalty += LAYER_COST * sum(1 for s in slots if s in ("mid_top", "outer", "legwear"))

    # Bare legs under a short skirt or a dress on a cold day: allowed, but tights should win.
    if (summary.get("outdoor_clo_min") or 0) >= COLD_DAY_CLO and "legwear" not in slots:
        if any(i["garment_type"] in BARE_LEG_TYPES for i in outfit):
            penalty += 0.5
            notes.append("bare legs on a cold day: add tights")

    # Formality of what stays on indoors; each level below the occasion costs a little.
    need = OCCASIONS[occasion]
    if need > 1:  # everything is at least formality 1, so casual occasions cost nothing here
        penalty += 0.6 * sum(max(0, need - i.get("formality", 1)) for i, s in zip(outfit, slots)
                             if s in ("base_top", "bottom", "one_piece", "mid_top"))
        # Shoes are seen all day and the coat on the way in, so they count too, at half weight.
        penalty += 0.3 * sum(max(0, need - i.get("formality", 1)) for i, s in zip(outfit, slots)
                             if s in ("shoes", "outer"))

    # Sweatpants and hoodies are for days with nothing on; anywhere else they are a last resort.
    if occasion != "everyday":
        penalty += 0.4 * sum(1 for i in outfit if i["garment_type"] in style.LOUNGE)

    result = {"indoor": indoor, "outdoor": outdoor, "notes": notes, "penalty": penalty, "style": None}
    return _add_style(result, outfit, occasion) if with_style else result


def _add_style(result: dict, outfit: list[dict], occasion: str) -> dict:
    """Add the style score to an evaluated outfit. It only ever raises the penalty."""
    result["style"] = style.style_score(outfit, occasion)
    if result["style"] is not None:
        result["penalty"] += (10 - result["style"]["score"]) * STYLE_WEIGHT
    return result


def _varied(ranked: list, n: int = 3, strict: bool = False) -> list:
    """The n best outfits that look different from each other, best first.

    ranked is (result, outfit) pairs, lowest penalty first. Each pick gets its own top and its
    own bottom (or dress), so the options are not one outfit with the trousers swapped. If the
    closet is too small for that, the rest are filled with any look not picked yet (unless strict).
    """
    picks, used, looks, worn = [], set(), set(), set()
    for at, pair in enumerate(ranked):
        if set(_look(pair[1])) & used:
            continue
        # Among outfits about as good as this one, take the one that repeats the fewest pieces
        # (knit, coat, shoes) from the options already picked.
        close = [p for p in ranked[at:at + VARIETY_WINDOW] if p[0]["penalty"] <= pair[0]["penalty"] + VARIETY_SLACK
                 and not set(_look(p[1])) & used]
        pair = min(close, key=lambda p: (sum(1 for i in p[1] if i["id"] in worn and slot(i) in ("mid_top", "outer", "shoes")),
                                         p[0]["penalty"]))
        picks.append(pair)
        used |= set(_look(pair[1]))
        looks.add(_look(pair[1]))
        worn |= {i["id"] for i in pair[1]}
        if len(picks) == n:
            return sorted(picks, key=lambda p: p[0]["penalty"])
    if not strict:
        for pair in ranked:
            if _look(pair[1]) not in looks:
                picks.append(pair)
                looks.add(_look(pair[1]))
                if len(picks) == n:
                    break
    return sorted(picks, key=lambda pair: pair[0]["penalty"])


def _look(outfit: list[dict]) -> tuple:
    """What makes two options look different: the top and bottom (or the dress)."""
    return tuple(sorted(i["id"] for i in outfit if slot(i) in ("base_top", "bottom", "one_piece")))


def _add_accessories(result: dict, accessories: list[dict], target: float | None) -> list[dict]:
    """Add gloves, hat, scarf (in that order) until the outdoor target is met."""
    added = []
    for kind in ACCESSORY_ORDER:
        if target is None or result["outdoor"] >= target:
            break
        for item in accessories:
            if item["garment_type"] == kind:
                added.append(item)
                result["outdoor"] += clo(item)
                break
    return added


def _fit(value: float, lo: float | None, hi: float | None) -> str:
    if lo is None:
        return "not needed today"
    if value < lo:
        return "too cold"
    if value > hi + 0.3:
        return "too warm"
    return "comfortable" if value >= hi - 0.15 else "a little cool"


def build_outfit(session, occasion: str = "class", must_include: list[str] | None = None,
                  exclude: list[str] | None = None, for_whom: str | None = None) -> str:
    """Rank outfits from the closet against the most recent plan_day_warmth result.

    for_whom names who this outfit is for (e.g. "me" or a friend's name), only needed when more
    than one person shares this closet in the same session. When given, an item someone else is
    currently wearing (update_wardrobe's worn_by, status "worn") is left out too, on top of the
    laundry and exclude filters, since a shared physical item can't be worn by two people at once
    (and, once laundered, each needs their own wash, not a pass straight to someone else).
    This only applies to garments worn directly against skin (tops, bottoms, dresses, legwear,
    socks) for hygiene; outerwear, mid-layers, shoes and accessories stay available to everyone
    across different people and days without needing a wash in between - but NOT simultaneously:
    a single pair of boots is still one physical object, so for_whom also steers this pick away
    from every item (every slot, not just the hygiene-sensitive ones) a *different* for_whom was
    picked for this exact same day, so two people asked about today and tomorrow in the same
    answer don't both get offered the identical physical item for the same day - coat or shoes
    included - before either has actually claimed anything with update_wardrobe. Scoped per day
    (from the most recent plan_day_warmth's date), not just per person, so building several of one
    person's days in a row doesn't overwrite and lose an earlier day's protection before the other
    for_whom's build for that same day runs. This only kicks in once every owned unit of that item
    is already claimed this way: owning 2 of something (set from the closet panel) means two
    people can legitimately both get offered it. This is a soft preference, not a hard rule, and
    backs off automatically if honoring it would leave no outfit at all.

    Separately, and regardless of for_whom (this applies to a single user too): a build for the
    same person on a *different* day steers away from that same person's own top, bottom or dress
    from their other days this session, so the same combo doesn't get suggested two days running
    just for variety's sake - this one is about repetition, not availability or hygiene, so it
    doesn't touch outerwear, mid-layers, shoes or accessories (re-wearing your own coat or shoes
    day to day is completely normal). Also a soft preference with the same automatic backoff.
    """
    plan = session.last_plan
    if not plan:
        return json.dumps({"error": "No day plan yet. Call plan_day_warmth with the user's schedule first."})
    if occasion not in OCCASIONS:
        return json.dumps({"error": f"occasion must be one of {list(OCCASIONS)}."})
    must_include, exclude = must_include or [], exclude or []
    unknown = [i for i in must_include + exclude if i not in session.wardrobe]
    if unknown:
        return json.dumps({"error": f"Unknown item ids {unknown}. Call list_wardrobe to see valid ids."})

    def _claimed_by_someone_else(item: dict) -> bool:
        if not for_whom or not item.get("worn_by") or slot(item) not in HYGIENE_SLOTS:
            return False
        return str(item["worn_by"]).strip().lower() != str(for_whom).strip().lower()

    laundry = [i["name"] for i in session.wardrobe.values() if i["status"] == "in_laundry"]
    claimed = [i["name"] for i in session.wardrobe.values()
               if i["status"] != "in_laundry" and _claimed_by_someone_else(i)]
    summary = plan["summary"]
    day = plan.get("date")

    # who_key tracks recent_picks even when for_whom is omitted (defaulting to "me", matching
    # build_outfit's own result below): a plain single-user conversation should still get the
    # same-day variety guard, not just the explicitly-shared-closet case.
    who_key = for_whom or "me"

    # plan_day_warmth stamps its own result with who it was for; if that doesn't match who this
    # build is for, the plan's clo targets (and thus the whole outfit) reflect the WRONG person's
    # warmth needs - most likely because cold_sensitivity was left out of the plan_day_warmth call
    # for this person, or their plan got skipped and this person's build is reusing someone else's.
    # Not a hard error (plan_for is only ever set by real plan_day_warmth calls, never by the literal
    # plan dicts some tests construct directly, so this never fires for those) - just a loud,
    # actionable note in the result so the mistake doesn't silently pass as a normal answer.
    plan_for = plan.get("for_whom")
    plan_mismatch = (f"This used the most recent plan_day_warmth, which was built for '{plan_for}', "
                      f"not '{who_key}'. If their cold_sensitivity differs, call plan_day_warmth again "
                      f"for '{who_key}' (with their own cold_sensitivity) before trusting this outfit."
                      ) if plan_for and plan_for.strip().lower() != who_key.strip().lower() else None

    # Only soft-avoid an item once every owned unit is already claimed by someone else's recent
    # pick *for this same day*: owning 2 pairs of the same boots means two people genuinely can
    # get offered "the same boots" without it being a physical conflict, so count claims against
    # qty rather than excluding on the first match. Scoped to the same day specifically - keyed by
    # (for_whom, day) rather than for_whom alone - so building this same person's OTHER days in
    # between doesn't overwrite and lose this day's protection before the other for_whom's build
    # for this exact day runs (which previously let two people both get offered the same top/
    # bottom for the same day, as long as the model built several of one person's days first).
    elsewhere_claims = Counter(
        iid for (who, picked_day), ids in session.recent_picks.items()
        if who.strip().lower() != who_key.strip().lower() and picked_day == day
        for iid in ids)
    recent_elsewhere = [iid for iid, claims in elsewhere_claims.items()
                         if claims >= session.wardrobe.get(iid, {}).get("qty", 1)]

    # Same person, a different day: avoid repeating your own exact top/bottom/dress two days
    # running. This is a variety preference, not a hygiene or physical-availability one - your own
    # shoes, socks, outer or mid-layer repeating day to day is completely normal and not touched.
    own_other_days = {
        iid for (who, picked_day), ids in session.recent_picks.items()
        if who.strip().lower() == who_key.strip().lower() and picked_day != day
        for iid in ids
        if iid in session.wardrobe and slot(session.wardrobe[iid]) in ("base_top", "bottom", "one_piece")
    }
    soft_avoid = list(set(recent_elsewhere) | own_other_days)

    def _score(avoid_these: list[str]):
        avoid = set(exclude) | set(avoid_these)
        available = [i for i in session.wardrobe.values()
                     if i["status"] != "in_laundry" and i["id"] not in avoid and not _claimed_by_someone_else(i)]
        wearable = [i for i in available if slot(i) not in ("head", "hands", "neck")]
        accessories = [i for i in available if slot(i) in ("head", "hands", "neck")]
        needed = {m for m in must_include if slot(session.wardrobe[m]) not in ("head", "hands", "neck")}
        # Socks barely change the numbers (0.03 against 0.06 clo), so pick the pair up front
        # rather than trying every outfit with each: the warmest on a cold day, else the lightest.
        socks = [i for i in wearable if slot(i) == "socks"]
        if len(socks) > 1:
            asked = [i for i in socks if i["id"] in needed]
            cold = (summary.get("outdoor_clo_min") or 0) >= COLD_DAY_CLO
            pair = asked[0] if asked else (max if cold else min)(socks, key=clo)
            wearable = [i for i in wearable if slot(i) != "socks"] + [pair]
        # Warmth, rain and formality are quick to work out; the style score is not. So rank on the
        # quick part first, then add style from the best down. Style only ever adds penalty, so once
        # three different looks beat the next outfit's quick penalty, nothing further can catch up.
        rough = [(_evaluate(outfit, summary, occasion, with_style=False), outfit) for outfit in _combos(wearable)
                 if needed <= {i["id"] for i in outfit}]
        rough.sort(key=lambda pair: pair[0]["penalty"])
        scored, best = [], {}  # best: look -> its best (result, outfit) so far
        for n, (result, outfit) in enumerate(rough):
            if len(best) >= 3 and n % 200 == 0:
                picks = _varied(sorted(best.values(), key=lambda pair: pair[0]["penalty"]), strict=True)
                if len(picks) == 3 and result["penalty"] > picks[-1][0]["penalty"]:
                    break
            if len(scored) >= MAX_STYLED:
                break
            _add_style(result, outfit, occasion)
            scored.append((result, outfit))
            look = _look(outfit)
            if look not in best or result["penalty"] < best[look][0]["penalty"]:
                best[look] = (result, outfit)
        return scored, accessories

    scored, accessories = _score(soft_avoid)
    if not scored and soft_avoid:
        # Honoring the soft same-session overlap/variety avoidance left nothing: a small closet
        # shouldn't hard-fail over a preference, so retry without it.
        scored, accessories = _score([])
    if not scored:
        return json.dumps({"error": "No complete outfit is available. The closet needs at least a top and a bottom "
                                    "(or a dress) that are not in the laundry and not excluded."})
    scored.sort(key=lambda pair: pair[0]["penalty"])

    options = []
    for result, outfit in _varied(scored):
        extras = _add_accessories(result, accessories, summary.get("outdoor_clo_ideal"))
        options.append({
            "items": [{"id": i["id"], "name": i["name"], "slot": slot(i), "clo": clo(i)} for i in outfit + extras],
            "indoor_clo": round(result["indoor"], 2),
            "outdoor_clo": round(result["outdoor"], 2),
            "indoors": _fit(result["indoor"], summary.get("indoor_clo_min"), summary.get("indoor_clo_ideal")),
            "outdoors": _fit(result["outdoor"], summary.get("outdoor_clo_min"), summary.get("outdoor_clo_ideal")),
            "take_off_indoors": [i["name"] for i in outfit + extras if slot(i) in ("outer", "head", "hands", "neck")],
            "notes": result["notes"],
            "style": result["style"],
        })

    session.last_outfit = [i["id"] for i in options[0]["items"]]
    session.recent_picks[(who_key, day)] = [i["id"] for i in options[0]["items"]]
    result = {
        "date": plan.get("date"),
        "for_whom": who_key,
        "targets": {k: summary.get(k) for k in ("indoor_clo_min", "indoor_clo_ideal", "outdoor_clo_min", "outdoor_clo_ideal")},
        "options": options,
        "skipped_in_laundry": laundry,
        "claimed_by_someone_else": claimed,
        "style_check": "on" if options[0]["style"] else "not built yet",
    }
    if plan_mismatch:
        result["warning"] = plan_mismatch
    return json.dumps(result)


def list_wardrobe(session, slot_filter: str | None = None) -> str:
    """Compact view of the closet so the model can refer to item ids."""
    items = [
        {"id": i["id"], "name": i["name"], "slot": slot(i), "clo": clo(i), "status": i["status"],
         "wears": i["wears"], "wear_limit": wear_limit(i), "worn_by": i.get("worn_by"), "worn_for": i.get("worn_for"),
         "qty": i.get("qty", 1), "qty_in_laundry": i.get("qty_in_laundry", 0)}
        for i in session.wardrobe.values()
        if slot_filter in (None, slot(i))
    ]
    return json.dumps({"count": len(items), "items": items})


def sync_laundry_status(item: dict) -> None:
    """Recompute status from qty/qty_in_laundry/wears after either changes.

    status == "in_laundry" only once nothing is available (qty_in_laundry >= qty); that is
    exactly what build_outfit's availability filter and the closet's "in laundry" styling
    already key off, so keeping status in sync here means neither needs to know qty exists.
    """
    qty = item.get("qty", 1)
    dirty = item.get("qty_in_laundry", 0)
    item["status"] = "in_laundry" if dirty >= qty else "worn" if item["wears"] > 0 else "clean"
    if item["status"] != "worn":
        item["worn_by"] = None
        item["worn_for"] = None


def update_wardrobe(session, item_ids: list[str], status: str, worn_by: str | None = None,
                     worn_for: str | None = None) -> str:
    """Mark items clean, worn, or in the laundry. A 'worn' item that reaches its wear limit
    (garments.csv, e.g. a t-shirt is 1, a coat is 10) sends one unit to the laundry automatically;
    for an item owned more than once (qty > 1, set from the closet panel), only that one unit
    goes, not the whole item. Repeated 'worn' calls past the limit each dirty one more unit.
    status="in_laundry" also sends one more unit each call; status="clean" is a full restock
    (qty_in_laundry back to 0), matching "the laundry is done" rather than "undo one item" (the
    closet panel's own laundry-count controls handle undoing a single accidental tap). A separate
    lifetime_wears counter increments once per call that actually dirties a previously-clean unit,
    whether that happens via "worn" or a direct "in_laundry" (e.g. the closet tile's manual toggle,
    which deliberately never touches wears/wear_limit) - both mean the item got used. Unlike wears
    (which tracks the current wash cycle), it's never reset by "clean"; wardrobe_stats reads it.

    worn_by optionally labels who is wearing the item today (e.g. "me" or a friend's name), for a
    closet shared by more than one person. worn_for optionally labels which day it's set aside for
    (e.g. "today", "tomorrow", or the date used in plan_day_warmth) once more than one day has been
    planned in this conversation, even for a single person. Both only take effect alongside
    status="worn" - including on an item whose wear limit this exact call reaches (you're still
    wearing it right now, even though it's also headed to the laundry after); any OTHER status, or
    a "worn" call on an item that was already at its limit before this call, clears both labels,
    since nobody currently "has" a plain dirty item that nobody just put on. build_outfit's
    for_whom filter reads worn_by to avoid handing one person's current pick to someone else
    before it is laundered.
    """
    if status not in STATUSES:
        return json.dumps({"error": f"status must be one of {STATUSES}."})
    unknown = [i for i in item_ids if i not in session.wardrobe]
    if unknown:
        return json.dumps({"error": f"Unknown item ids {unknown}. Call list_wardrobe to see valid ids."})
    updated, needs_laundry = [], []
    for item_id in item_ids:
        item = session.wardrobe[item_id]
        qty = item.get("qty", 1)
        just_worn_out = False  # this exact call dirtied a previously-clean unit, not an already-laundered one
        if status == "worn":
            item["wears"] += 1
            item["lifetime_wears"] = item.get("lifetime_wears", 0) + 1
            if item["wears"] >= wear_limit(item):
                prev_dirty = item.get("qty_in_laundry", 0)
                item["qty_in_laundry"] = min(qty, prev_dirty + 1)
                just_worn_out = item["qty_in_laundry"] > prev_dirty
                needs_laundry.append(item["name"])
        elif status == "clean":
            item["qty_in_laundry"] = 0
            item["wears"] = 0
        else:  # "in_laundry": one more unit goes to the wash, same action as a laundry-panel tap.
            # Marking something dirty directly (without going through "worn" first, e.g. tapping
            # the closet tile straight to laundry) still means it got used - it still counts for
            # wardrobe_stats, even though it deliberately doesn't touch wears/wear_limit (see
            # test_manual_laundry_toggle_is_unaffected_by_wear_limit).
            prev_dirty = item.get("qty_in_laundry", 0)
            item["qty_in_laundry"] = min(qty, prev_dirty + 1)
            if item["qty_in_laundry"] > prev_dirty:
                item["lifetime_wears"] = item.get("lifetime_wears", 0) + 1
        sync_laundry_status(item)
        # Still tag it even if this exact "worn" call is what just sent the last clean unit to the
        # laundry: the user is wearing it *right now*, today, even though it'll need a wash after -
        # that's not the same as "nobody has this, it's just sitting dirty" (a bare "in_laundry" call
        # with no wear behind it, which still clears the tag as before).
        still_has_it = item["status"] == "worn" or just_worn_out
        item["worn_by"] = worn_by.strip()[:40] if (
            isinstance(worn_by, str) and worn_by.strip() and still_has_it) else None
        item["worn_for"] = worn_for.strip()[:40] if (
            isinstance(worn_for, str) and worn_for.strip() and still_has_it) else None
        updated.append({"id": item_id, "name": item["name"], "status": item["status"], "wears": item["wears"],
                         "worn_by": item["worn_by"], "worn_for": item["worn_for"],
                         "qty": qty, "qty_in_laundry": item["qty_in_laundry"]})
    result = {"updated": updated}
    if needs_laundry:
        result["note"] = f"{', '.join(needs_laundry)} hit the wear limit and went straight to the laundry."
    return json.dumps(result)


_SLOTS = ["base_top", "mid_top", "outer", "bottom", "one_piece", "legwear", "socks", "shoes", "head", "hands", "neck"]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "build_outfit",
            "description": (
                "Pick the best outfits from the user's closet for the most recent plan_day_warmth result. "
                "Skips items in the laundry, checks warmth indoors and outdoors, accounts for rain and wind, "
                "and adds gloves/hat/scarf if needed. Returns up to 3 ranked options. "
                "Always call plan_day_warmth first. For a shared closet, pass for_whom: a top, bottom, dress, "
                "legwear or sock someone else already has on is left out, and this call also automatically "
                "steers away from every item (any slot, including coats and shoes - a single pair of boots "
                "can't be on two people on the same day) a different for_whom was picked for this exact "
                "same day, even before anything is confirmed with update_wardrobe. Also automatically avoids "
                "repeating the same person's own top/bottom/dress on a different day, for variety."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion": {"type": "string", "enum": list(OCCASIONS), "description": "What the day is for. Defaults to 'class'."},
                    "must_include": {"type": "array", "items": {"type": "string"},
                                     "description": "Item ids the user wants to wear, e.g. ['skirt-maxi']."},
                    "exclude": {"type": "array", "items": {"type": "string"},
                                "description": "Item ids the user does not want today."},
                    "for_whom": {"type": "string",
                                 "description": "Who this outfit is for, e.g. 'me' or a name. Only needed when "
                                                "more than one person shares this closet; a top, bottom, dress, "
                                                "legwear or socks someone else currently has on (see "
                                                "update_wardrobe) is left out for hygiene, until laundered. "
                                                "Outerwear, mid-layers, shoes and accessories stay available to "
                                                "everyone regardless of who has them on."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_wardrobe",
            "description": "List the clothes in the user's closet with ids, warmth (clo) and laundry status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_filter": {"type": "string", "enum": _SLOTS, "description": "Only show one kind of item, e.g. 'outer' for coats."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_wardrobe",
            "description": (
                "Change the status of closet items. Use 'in_laundry' when the user says something is in the wash, "
                "'worn' after they choose an outfit, 'clean' when laundry is done. A 'worn' item that reaches its "
                "wear limit (e.g. a t-shirt after 1 wear, a coat after 10) is sent to the laundry automatically; "
                "the result's 'note' field says which items that happened to."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {"type": "array", "items": {"type": "string"}, "description": "Item ids from list_wardrobe."},
                    "status": {"type": "string", "enum": STATUSES},
                    "worn_by": {"type": "string",
                                "description": "Who is wearing it today, e.g. 'me' or a name. Only needed when "
                                               "more than one person shares this closet; omit for a single user."},
                    "worn_for": {"type": "string",
                                 "description": "Which day it's set aside for, e.g. 'today', 'tomorrow', or the "
                                                "date used in plan_day_warmth. Only needed once more than one day "
                                                "has been planned in this conversation, even for a single user."},
                },
                "required": ["item_ids", "status"],
            },
        },
    },
]

TOOL_MAP = {"build_outfit": build_outfit, "list_wardrobe": list_wardrobe, "update_wardrobe": update_wardrobe}
