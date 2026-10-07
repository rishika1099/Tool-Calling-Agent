"""Proactive reasoning about the closet itself, not just picking from it.

Owner: wardrobe (see PROPOSAL.md). Three tools, each answering a question build_outfit never
asks on its own: what's missing for today's weather (suggest_wardrobe_gaps), what's running low
on clean units (plan_laundry), and what actually gets worn (wardrobe_stats).
"""

import json

from .catalog import clo, is_windproof, keeps_rain_out, slot, wear_limit
from .outfit import UNDERWEAR_CLO, WINDY_MPH

OUTDOOR_SLOTS = ("base_top", "mid_top", "outer")
LAUNDRY_SLOTS = ("base_top", "mid_top", "outer", "bottom", "one_piece", "legwear", "socks", "shoes")
LOW_CLEAN_UNITS = 1  # at or below this many clean units in a category, flag it as running low


def suggest_wardrobe_gaps(session) -> str:
    """Tool: flag closet coverage gaps against the most recent plan_day_warmth result - a missing
    waterproof or windproof coat when the forecast calls for one, or not enough warmth available
    in the closet at all even stacking every layer. Reasons about what's absent, not just what to
    pick from what's there.
    """
    plan = session.last_plan
    if not plan:
        return json.dumps({"error": "No day plan yet. Call plan_day_warmth with the user's schedule first."})
    summary = plan["summary"]
    available = [i for i in session.wardrobe.values() if i["status"] != "in_laundry"]
    by_slot: dict[str, list[dict]] = {}
    for item in available:
        by_slot.setdefault(slot(item), []).append(item)
    outers = by_slot.get("outer", [])
    gaps = []

    if not outers:
        gaps.append("No coat or jacket in the closet at all (or every one is in the laundry).")
    else:
        if summary.get("rain_expected") and not any(keeps_rain_out(o) for o in outers):
            gaps.append("No waterproof or water-resistant coat for today's rain.")
        elif summary.get("snow_expected") and not any(keeps_rain_out(o) for o in outers):
            gaps.append("No waterproof coat for today's snow.")
        if summary.get("max_wind_mph", 0) >= WINDY_MPH and not any(is_windproof(o) for o in outers):
            gaps.append(f"No windproof coat despite {summary['max_wind_mph']} mph wind expected.")

    shoes = by_slot.get("shoes", [])
    if not shoes:
        gaps.append("No shoes in the closet at all (or every pair is in the laundry).")
    elif summary.get("rain_expected") and not any(keeps_rain_out(s) for s in shoes):
        gaps.append("No waterproof shoes or boots for today's rain.")

    # A rough ceiling, not build_outfit's real optimizer: the single warmest item in each
    # outdoor-relevant slot, stacked. Good enough to catch "nothing here gets you warm enough."
    ceiling = round(UNDERWEAR_CLO + sum(max((clo(i) for i in by_slot.get(s, [])), default=0.0)
                                         for s in OUTDOOR_SLOTS), 2)
    target = summary.get("outdoor_clo_min")
    if target is not None and ceiling < target:
        gaps.append(f"Even the warmest combo in the closet (about {ceiling} clo) falls short of "
                    f"today's target ({target} clo outdoors) - it's missing a warm enough layer.")

    return json.dumps({"gaps": gaps, "closet_size": len(session.wardrobe)})


def plan_laundry(session) -> str:
    """Tool: how many clean units remain in each clothing category right now, and which
    categories are running low, so the user can do laundry before they actually run out of a
    clean top, bottom, or pair of shoes rather than finding out the morning of.
    """
    by_category: dict[str, dict] = {}
    for item in session.wardrobe.values():
        s = slot(item)
        if s not in LAUNDRY_SLOTS:
            continue
        qty = item.get("qty", 1)
        clean_units = max(0, qty - item.get("qty_in_laundry", 0))
        entry = by_category.setdefault(s, {"clean_items": 0, "clean_units": 0, "owned_units": 0})
        entry["owned_units"] += qty
        entry["clean_units"] += clean_units
        if clean_units > 0:
            entry["clean_items"] += 1

    running_low = [f"{cat.replace('_', ' ')}: only {data['clean_units']} clean unit(s) left "
                    f"(of {data['owned_units']} owned)"
                    for cat, data in sorted(by_category.items()) if data["clean_units"] <= LOW_CLEAN_UNITS]
    return json.dumps({"by_category": by_category, "running_low": running_low})


def wardrobe_stats(session) -> str:
    """Tool: lifetime wear counts - which items actually earn their place in the closet, and
    which have never been worn once, for when the user asks something like "what do I even wear"
    or "what's just sitting there."
    """
    items = list(session.wardrobe.values())
    ranked = sorted(items, key=lambda i: i.get("lifetime_wears", 0), reverse=True)
    most_worn = [{"id": i["id"], "name": i["name"], "lifetime_wears": i.get("lifetime_wears", 0)}
                 for i in ranked if i.get("lifetime_wears", 0) > 0][:5]
    never_worn = [{"id": i["id"], "name": i["name"]} for i in items if i.get("lifetime_wears", 0) == 0]
    return json.dumps({
        "total_items": len(items),
        "most_worn": most_worn,
        "never_worn_count": len(never_worn),
        "never_worn_sample": never_worn[:5],
    })


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "suggest_wardrobe_gaps",
            "description": (
                "Check the closet for coverage gaps against the most recent plan_day_warmth result: "
                "a missing waterproof coat when rain or snow is expected, a missing windproof coat on "
                "a windy day, no shoes or coat at all, or not enough warmth available even stacking "
                "every layer. Use when the user asks if their closet is ready for the weather, or "
                "after a build_outfit result looks thin or forced. Always call plan_day_warmth first."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_laundry",
            "description": (
                "Check how many clean units are left in each clothing category (tops, bottoms, "
                "shoes, etc.) and which are running low, so the user can do laundry before they "
                "actually run out of something clean. Use when they ask about laundry timing, "
                "whether they need to do a wash soon, or how many clean items they have left."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wardrobe_stats",
            "description": (
                "Lifetime wear counts across the closet: the most-worn items and ones never worn "
                "at all. Use when the user asks what they actually wear, what's basically unused, "
                "or wants a sense of their closet habits."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

TOOL_MAP = {
    "suggest_wardrobe_gaps": suggest_wardrobe_gaps,
    "plan_laundry": plan_laundry,
    "wardrobe_stats": wardrobe_stats,
}
