"""Pick outfits from the user's closet that meet the day plan, and keep the closet up to date.

Shared by all three owners: warmth needs come from plan_day_warmth, garment data
from scan_garment, and the style score from style.style_score.
"""

import itertools
import json

from . import style
from .catalog import INDOOR_SLOTS, clo, is_windproof, keeps_rain_out, slot, wear_limit, wet_retention

UNDERWEAR_CLO = 0.04  # assumed, not tracked in the closet
SHORT_JACKETS = {"denim_jacket", "bomber_jacket", "leather_jacket"}
OCCASIONS = {"everyday": 1, "class": 1, "date": 2, "dinner": 2, "party": 2, "work": 2, "interview": 3}  # minimum formality
WINDY_MPH = 12
WINDPROOF_BONUS = 0.10  # team estimate: a windproof outer layer keeps ~10% more warmth in wind
SKIRTS = {"skirt_thin", "skirt_thick", "long_skirt"}
TIGHTS = {"tights", "fleece_tights"}
ACCESSORY_ORDER = ["gloves", "beanie", "scarf"]
LAYER_COST = 0.08  # small cost per optional layer, so we never add layers that don't help
STATUSES = ["clean", "worn", "in_laundry"]


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


def _evaluate(outfit: list[dict], summary: dict, occasion: str) -> dict:
    """Indoor and outdoor warmth of an outfit against the plan, with a penalty (lower is better)."""
    notes = []
    indoor = UNDERWEAR_CLO + sum(clo(i) for i in outfit if slot(i) in INDOOR_SLOTS)
    outer = next((i for i in outfit if slot(i) == "outer"), None)
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

    penalty += LAYER_COST * sum(1 for i in outfit if slot(i) in ("mid_top", "outer", "legwear"))

    # Formality of what stays on indoors; each level below the occasion costs a little.
    visible = [i for i in outfit if slot(i) in ("base_top", "bottom", "one_piece", "mid_top")]
    penalty += 0.6 * sum(max(0, OCCASIONS[occasion] - i.get("formality", 1)) for i in visible)
    # Shoes are seen all day and the coat on the way in, so they count too, at half weight.
    seen = [i for i in outfit if slot(i) in ("shoes", "outer")]
    penalty += 0.3 * sum(max(0, OCCASIONS[occasion] - i.get("formality", 1)) for i in seen)

    # Sweatpants and hoodies are for days with nothing on; anywhere else they are a last resort.
    if occasion != "everyday":
        penalty += 0.4 * sum(1 for i in outfit if i["garment_type"] in style.LOUNGE)

    style_result = style.style_score(outfit, occasion)
    if style_result is not None:
        penalty += (10 - style_result["score"]) * 0.15

    return {"indoor": indoor, "outdoor": outdoor, "notes": notes, "penalty": penalty, "style": style_result}


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
    than one person shares this closet in the same session. When given, any item someone else is
    currently wearing (update_wardrobe's worn_by, status "worn") is left out too, on top of the
    laundry and exclude filters, since a shared physical item can't be worn by two people at once.
    Omit for a single user; nothing changes for that case.
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
        if not for_whom or not item.get("worn_by"):
            return False
        return str(item["worn_by"]).strip().lower() != str(for_whom).strip().lower()

    available = [i for i in session.wardrobe.values()
                 if i["status"] != "in_laundry" and i["id"] not in exclude and not _claimed_by_someone_else(i)]
    laundry = [i["name"] for i in session.wardrobe.values() if i["status"] == "in_laundry"]
    claimed = [i["name"] for i in session.wardrobe.values()
               if i["status"] != "in_laundry" and _claimed_by_someone_else(i)]
    wearable = [i for i in available if slot(i) not in ("head", "hands", "neck")]
    accessories = [i for i in available if slot(i) in ("head", "hands", "neck")]

    summary = plan["summary"]
    scored = []
    for outfit in _combos(wearable):
        ids = {i["id"] for i in outfit}
        if all(m in ids for m in must_include if slot(session.wardrobe[m]) not in ("head", "hands", "neck")):
            scored.append((_evaluate(outfit, summary, occasion), outfit))
    if not scored:
        return json.dumps({"error": "No complete outfit is available. The closet needs at least a top and a bottom "
                                    "(or a dress) that are not in the laundry and not excluded."})
    scored.sort(key=lambda pair: pair[0]["penalty"])

    options, seen = [], set()
    for result, outfit in scored:
        key = tuple(sorted(i["id"] for i in outfit if slot(i) in ("base_top", "bottom", "one_piece", "outer")))
        if key in seen:
            continue
        seen.add(key)
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
        if len(options) == 3:
            break

    session.last_outfit = [i["id"] for i in options[0]["items"]]
    return json.dumps({
        "targets": {k: summary.get(k) for k in ("indoor_clo_min", "indoor_clo_ideal", "outdoor_clo_min", "outdoor_clo_ideal")},
        "options": options,
        "skipped_in_laundry": laundry,
        "claimed_by_someone_else": claimed,
        "style_check": "on" if options[0]["style"] else "not built yet",
    })


def list_wardrobe(session, slot_filter: str | None = None) -> str:
    """Compact view of the closet so the model can refer to item ids."""
    items = [
        {"id": i["id"], "name": i["name"], "slot": slot(i), "clo": clo(i), "status": i["status"],
         "wears": i["wears"], "wear_limit": wear_limit(i), "worn_by": i.get("worn_by"), "worn_for": i.get("worn_for")}
        for i in session.wardrobe.values()
        if slot_filter in (None, slot(i))
    ]
    return json.dumps({"count": len(items), "items": items})


def update_wardrobe(session, item_ids: list[str], status: str, worn_by: str | None = None,
                     worn_for: str | None = None) -> str:
    """Mark items clean, worn, or in the laundry. A 'worn' item that reaches its wear limit
    (garments.csv, e.g. a t-shirt is 1, a coat is 10) goes to the laundry automatically.

    worn_by optionally labels who is wearing the item today (e.g. "me" or a friend's name), for a
    closet shared by more than one person. worn_for optionally labels which day it's set aside for
    (e.g. "today", "tomorrow", or the date used in plan_day_warmth) once more than one day has been
    planned in this conversation, even for a single person. Both only take effect alongside
    status="worn", and only on items that end up actually staying "worn" (not ones that hit their
    wear limit and go straight to the laundry). Any other status clears both labels: nobody
    currently "has" an item, for anyone or any day, once it isn't being worn right now.
    build_outfit's for_whom filter reads worn_by to avoid handing one person's current pick to
    someone else before it is laundered.
    """
    if status not in STATUSES:
        return json.dumps({"error": f"status must be one of {STATUSES}."})
    unknown = [i for i in item_ids if i not in session.wardrobe]
    if unknown:
        return json.dumps({"error": f"Unknown item ids {unknown}. Call list_wardrobe to see valid ids."})
    updated, needs_laundry = [], []
    for item_id in item_ids:
        item = session.wardrobe[item_id]
        if status == "worn":
            item["wears"] += 1
            if item["wears"] >= wear_limit(item):
                item["status"] = "in_laundry"
                needs_laundry.append(item["name"])
            else:
                item["status"] = "worn"
        elif status == "clean":
            item["wears"] = 0
            item["status"] = "clean"
        else:
            item["status"] = status
        still_worn = item["status"] == "worn"
        item["worn_by"] = worn_by.strip()[:40] if (
            isinstance(worn_by, str) and worn_by.strip() and still_worn) else None
        item["worn_for"] = worn_for.strip()[:40] if (
            isinstance(worn_for, str) and worn_for.strip() and still_worn) else None
        updated.append({"id": item_id, "name": item["name"], "status": item["status"], "wears": item["wears"],
                         "worn_by": item["worn_by"], "worn_for": item["worn_for"]})
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
                "Always call plan_day_warmth first. For a shared closet, pass for_whom so one person's "
                "current pick isn't offered to someone else."
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
                                                "more than one person shares this closet; items someone else is "
                                                "currently wearing (see update_wardrobe) are left out."},
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
