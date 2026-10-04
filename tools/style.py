"""Does an outfit go together? Explainable rules for color, shape, pattern and occasion.

Owner: style (Kshamaa; see PROPOSAL.md and GitHub issue #10).

The score is out of 10: four rule groups, each worth a fixed number of points and each
giving one plain-English reason. Nothing here asks a model for an opinion, so the same
outfit always gets the same score and every point lost can be traced to a rule.

  Color     3.5  Neutrals (black, white, grey, navy, blue denim, cream/camel/brown, olive)
                 go with anything. Other colors are compared by hue angle on the color
                 wheel: up to 60 degrees apart is analogous, 150 or more is complementary,
                 anything in between competes (most between 60 and 105). Muted colors
                 compete less than vivid ones, and more than three colors is busy.
  Shape     2.0  Balance volume. A long or full skirt (or wide-leg pants) needs a fitted or
                 tucked top, not an oversized one. A fitted coat does not go over an
                 oversized layer.
  Pattern   1.5  At most one bold pattern.
  Occasion  3.0  Formality 1-3 must reach what the occasion asks for, and what you wear indoors
                 must share a dress code (no sweatpants with an oxford shirt).

The verdict is "goes together" only when the score is 8 or more and no single rule fails;
one weak rule makes it "works with a tweak", and a rule that fails outright (or a score
under 6) makes it "does not go together".

Only what shows is judged: socks are ignored, leggings count only under a skirt or dress,
and a top under a sweater, shoes and accessories count half.

build_outfit calls style_score() for every candidate outfit (thousands per request), so
scores are cached on what is visible; outfits that differ only in socks share one result.
"""

import colorsys
import itertools
import json
from functools import lru_cache
from typing import NamedTuple

from .catalog import GARMENTS

POINTS = {"color": 3.5, "shape": 2.0, "pattern": 1.5, "occasion": 3.0}  # adds up to 10

# Minimum formality (1 casual, 2 smart casual, 3 formal) per occasion. Same table as
# tools/outfit.py, which imports this module, so it cannot be imported from there
# (tests/test_style.py checks the two stay in step).
OCCASIONS = {"everyday": 1, "class": 1, "date": 2, "dinner": 2, "party": 2, "work": 2, "interview": 3}
FORMALITY_WORDS = {1: "casual", 2: "smart casual", 3: "formal"}
OCCASION_PHRASE = {"everyday": "everyday wear", "class": "class", "date": "a date", "dinner": "dinner",
                   "party": "a party", "work": "work", "interview": "an interview"}

# How much each visible piece counts. A top under a sweater only shows at the collar.
WEIGHT = {"top": 1.0, "mid": 1.0, "outer": 1.0, "bottom": 1.0, "dress": 1.0,
          "under": 0.5, "legs": 0.5, "shoes": 0.5, "accent": 0.5}
SLOT_ROLE = {"mid_top": "mid", "outer": "outer", "bottom": "bottom", "one_piece": "dress",
             "shoes": "shoes", "head": "accent", "hands": "accent", "neck": "accent"}

SKIRTS = {"skirt_thin", "skirt_thick", "long_skirt"}
DENIM = {"jeans", "denim_jacket"}
LOUNGE = {"sweatpants", "hoodie"}  # loungewear: a different dress code from anything smart

NEUTRAL_CHROMA = 0.12  # below this a color reads as black, white or grey
MUTED_CHROMA = 0.25    # below this a color is soft enough to clash less
ANALOGOUS_DEG = 60     # neighbors on the color wheel
COMPLEMENT_DEG = 150   # opposites on the color wheel
TRIAD_DEG = 105        # from here to COMPLEMENT_DEG the contrast is strong but less awkward
HUE_NAMES = [(15, "red"), (45, "orange"), (70, "yellow"), (165, "green"), (200, "teal"),
             (255, "blue"), (290, "purple"), (345, "pink"), (360, "red")]


class Piece(NamedTuple):
    """One visible garment, reduced to what the rules need (hashable, so scores can be cached)."""
    name: str
    role: str            # key of WEIGHT
    garment_type: str
    tone: str            # color name, e.g. "navy" or "red"
    hue: float | None    # degrees on the color wheel; None for neutrals
    chroma: float        # 0 grey .. 1 vivid
    volume: int          # 0 fitted, 1 relaxed, 2 oversized or full
    bold: bool
    formality: int


# --- Reading one garment ---


@lru_cache(maxsize=4096)
def _tone(hex_color: str, denim: bool) -> tuple[str, float | None, float]:
    """Name a hex color and say whether it is a neutral (hue None) or sits on the color wheel."""
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (TypeError, ValueError):
        return "grey", None, 0.0
    hue, light, _ = colorsys.rgb_to_hls(r, g, b)
    hue *= 360
    chroma = max(r, g, b) - min(r, g, b)
    if chroma < NEUTRAL_CHROMA:
        return ("black" if light < 0.2 else "white" if light > 0.8 else "grey"), None, chroma
    if 200 <= hue <= 250 and light < 0.33:
        return "navy", None, chroma
    if denim and 190 <= hue <= 250:
        return "denim blue", None, chroma
    if 18 <= hue <= 50 and chroma <= 0.45:
        return ("cream" if light > 0.7 else "camel" if light > 0.42 else "brown"), None, chroma
    if 50 < hue <= 95 and chroma < MUTED_CHROMA:
        return "olive", None, chroma
    return next(name for limit, name in HUE_NAMES if hue < limit), hue, chroma


def _volume(item: dict, role: str) -> int:
    fit = item.get("fit")
    if role == "bottom" and item.get("garment_type") == "long_skirt" and fit != "fitted":
        return 2  # a maxi skirt is full unless it is cut close
    return {"fitted": 0, "oversized": 2}.get(fit, 1)


def _pieces(outfit: list[dict]) -> tuple[Piece, ...]:
    """The parts of an outfit you can see, in the order given."""
    slots = [GARMENTS.get(item.get("garment_type"), {}).get("slot") for item in outfit]
    has_mid = "mid_top" in slots
    legs_show = "one_piece" in slots or any(item.get("garment_type") in SKIRTS for item in outfit)
    pieces = []
    for item, slot in zip(outfit, slots):
        if slot == "base_top":
            role = "under" if has_mid else "top"
        elif slot == "legwear":
            role = "legs" if legs_show else None  # hidden under trousers
        else:
            role = SLOT_ROLE.get(slot)  # socks and underwear have no role
        if role is None:
            continue
        garment_type = item.get("garment_type", "")
        denim = garment_type in DENIM or "denim" in (item.get("materials") or {})
        tone, hue, chroma = _tone(item.get("color"), denim)
        formality = item.get("formality")
        pieces.append(Piece(
            name=str(item.get("name") or garment_type.replace("_", " ")),
            role=role, garment_type=garment_type, tone=tone, hue=hue, chroma=chroma,
            volume=_volume(item, role), bold=item.get("pattern") == "bold",
            formality=formality if formality in (1, 2, 3) else 1,
        ))
    return tuple(pieces)


def _names(pieces) -> str:
    names = [p.name for p in pieces]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _tones(pieces) -> list[str]:
    return list(dict.fromkeys(p.tone for p in pieces))


# --- The four rules. Each returns (share of its points earned, reason) ---


def _color_rule(pieces: tuple[Piece, ...]) -> tuple[float, str]:
    colored = [p for p in pieces if p.hue is not None]
    neutrals = _tones(p for p in pieces if p.hue is None)
    if not colored:
        return 1.0, f"all neutrals ({', '.join(neutrals[:4])}), which go with anything."

    lost, worst, widest = 0.0, None, (0.0, None, None)
    for a, b in itertools.combinations(colored, 2):
        gap = abs(a.hue - b.hue)
        gap = min(gap, 360 - gap)
        if gap > widest[0]:
            widest = (gap, a, b)
        if gap <= ANALOGOUS_DEG or gap >= COMPLEMENT_DEG:
            continue
        cost = (1.0 if gap < TRIAD_DEG else 0.5) * WEIGHT[a.role] * WEIGHT[b.role] / 2
        if min(a.chroma, b.chroma) < MUTED_CHROMA:
            cost *= 0.6
        lost += cost
        if worst is None or cost > worst[0]:
            worst = (cost, gap, a, b)
    families = _tones(colored)
    if len(families) > 3:
        lost += 0.25 * (len(families) - 3)

    if worst:
        _, gap, a, b = worst
        pair = f"{a.name} ({a.tone}) and {b.name} ({b.tone}) are {gap:.0f} degrees apart on the color wheel"
        if gap < TRIAD_DEG:
            return max(0.0, 1 - lost), f"{pair}, neither neighbors nor opposites, so they compete. Swap one for a neutral."
        return max(0.0, 1 - lost), f"{pair}, a strong contrast just short of true opposites. Bold but workable; a neutral is the safe swap."
    if len(families) > 3:
        return max(0.0, 1 - lost), f"{len(families)} different colors ({', '.join(families)}) is busy. Keep to three."
    base = f" on a neutral base ({', '.join(neutrals[:3])})" if neutrals else ""
    if len(families) == 1:
        return 1.0, f"one color ({families[0]}: {_names(colored)}){base}."
    gap, a, b = widest
    link = "opposites on the color wheel, a classic contrast" if gap >= COMPLEMENT_DEG else "neighbors on the color wheel"
    return 1.0, f"{a.tone} ({a.name}) and {b.tone} ({b.name}) are {link}{base}."


def _shape_rule(pieces: tuple[Piece, ...]) -> tuple[float, str]:
    by_role = {p.role: p for p in pieces}
    top = by_role.get("mid") or by_role.get("top") or by_role.get("under")  # the top layer that shows indoors
    bottom, outer = by_role.get("bottom"), by_role.get("outer")
    share, reason = 1.0, "proportions are even, nothing fights for volume."

    if top and bottom:
        full_bottom = "full" if bottom.garment_type in SKIRTS else "wide"
        if bottom.volume == 2 and top.volume == 2:
            share, reason = 0.2, (f"{top.name} and {bottom.name} are both voluminous, so the outfit loses its shape. "
                                  f"A {full_bottom} bottom needs a fitted top.")
        elif bottom.volume == 2 and top.volume == 1:
            share, reason = 0.7, f"with the {full_bottom} {bottom.name}, tuck in {top.name} or pick a fitted top to show the waist."
        elif bottom.volume == 2:
            share, reason = 1.0, f"fitted {top.name} balances the {full_bottom} {bottom.name}."
        elif top.volume == 2 and bottom.volume == 0:
            share, reason = 1.0, f"oversized {top.name} over slim {bottom.name} is balanced."
        elif top.volume == 2:
            share, reason = 0.8, f"{top.name} is oversized; slimmer bottoms than {bottom.name} would sharpen it."

    under_coat = by_role.get("mid") or by_role.get("top") or by_role.get("dress")
    if outer and under_coat and outer.volume == 0 and under_coat.volume == 2:
        note = f"{outer.name} is fitted and will bunch over the oversized {under_coat.name}."
        reason = note if share == 1.0 else f"{reason} Also, {note}"
        share = max(0.0, share - 0.3)
    return share, reason


def _pattern_rule(pieces: tuple[Piece, ...]) -> tuple[float, str]:
    bold = [p for p in pieces if p.bold]
    if not bold:
        return 1.0, "all solids, nothing competes."
    if len(bold) == 1:
        return 1.0, f"one bold pattern ({bold[0].name}) against solids, so it reads as the statement piece."
    return (0.3 if len(bold) == 2 else 0.0), (f"{_names(bold)} are {'both' if len(bold) == 2 else 'all'} bold patterns "
                                              f"and compete. Keep one and make the rest solid.")


def _occasion_rule(pieces: tuple[Piece, ...], occasion: str) -> tuple[float, str]:
    need = OCCASIONS.get(occasion, 1)
    setting = OCCASION_PHRASE.get(occasion, occasion)
    indoor = [p for p in pieces if p.role in ("top", "under", "mid", "bottom", "dress")]  # what stays on inside
    judged = indoor + [p for p in pieces if p.role in ("outer", "shoes")]
    share, problems = 1.0, []

    # 1. Dressed up enough? Lose half the points per formality level the outfit is short, on average.
    short = [p for p in judged if p.formality < need]
    if short:
        share -= 0.5 * sum(WEIGHT[p.role] * (need - p.formality) for p in short) / sum(WEIGHT[p.role] for p in judged)
        problems.append(f"{_names(short)}: too casual for {setting} (needs {FORMALITY_WORDS[need]})")

    # 2. One dress code? Loungewear with smart pieces, or casual with formal, looks unplanned.
    #    A casual coat is left out (a parka over a smart outfit is just winter), a formal coat is not.
    lounge = [p for p in indoor if p.garment_type in LOUNGE]
    smart = [p for p in indoor if p.formality >= 2 and p.garment_type not in LOUNGE]
    smart += [p for p in pieces if p.role == "outer" and p.formality == 3]
    if lounge and smart:
        share -= 0.6
        problems.append(f"{_names(lounge)} (loungewear) with {_names(smart)} (smart) mixes two dress codes. "
                        f"Swap {_names(lounge)} for something less sporty, or go casual all over")
    elif indoor:
        low, high = min(indoor, key=lambda p: p.formality), max(indoor, key=lambda p: p.formality)
        if high.formality - low.formality >= 2:
            share -= 0.4
            problems.append(f"{high.name} (formal) with {low.name} (casual) is two formality levels apart")

    if problems:
        return max(0.0, share), ". ".join(problems) + "."
    if need == 1:
        return 1.0, f"relaxed enough for {setting}, and the pieces share a dress code."
    return 1.0, f"every piece is {FORMALITY_WORDS[need]} or dressier, right for {setting}."


# --- Scoring ---


@lru_cache(maxsize=50_000)
def _score(pieces: tuple[Piece, ...], occasion: str) -> tuple[float, str, tuple[tuple[str, float], ...], tuple[str, ...]]:
    rules = {
        "color": _color_rule(pieces),
        "shape": _shape_rule(pieces),
        "pattern": _pattern_rule(pieces),
        "occasion": _occasion_rule(pieces, occasion),
    }
    points = {name: round(POINTS[name] * share, 1) for name, (share, _) in rules.items()}
    score = round(sum(points.values()), 1)
    reasons = tuple(f"{name.capitalize()} {points[name]:g}/{POINTS[name]:g}: {reason}" for name, (_, reason) in rules.items())
    return score, _verdict(score, min(share for share, _ in rules.values())), tuple(points.items()), reasons


def _verdict(score: float, weakest: float) -> str:
    """A high total is not enough: the weakest rule (share of its points earned) can veto."""
    if score < 6 or weakest <= 0.25:
        return "does not go together"
    if score < 8 or weakest < 0.6:
        return "works with a tweak"
    return "goes together"


def style_score(outfit: list[dict], occasion: str = "class") -> dict | None:
    """Score how well an outfit goes together, 0-10, with one reason per rule.

    Returns {"score", "verdict", "breakdown", "reasons"}. build_outfit uses "score" to rank.
    """
    score, verdict, points, reasons = _score(_pieces(outfit), occasion)
    return {"score": score, "verdict": verdict, "breakdown": dict(points), "reasons": list(reasons)}


def style_check(session, item_ids: list[str] | None = None, occasion: str = "class") -> str:
    """Tool: score an outfit the user proposes, or the last one build_outfit picked."""
    if occasion not in OCCASIONS:
        return json.dumps({"error": f"occasion must be one of {list(OCCASIONS)}."})
    if isinstance(item_ids, str):
        item_ids = [item_ids]
    if not item_ids:
        item_ids = session.last_outfit
        if not item_ids:
            return json.dumps({"error": "No outfit to check yet. Pass the item ids to compare (call list_wardrobe "
                                        "to find them), or call plan_day_warmth and build_outfit first."})
    item_ids = list(dict.fromkeys(item_ids))
    unknown = [i for i in item_ids if i not in session.wardrobe]
    if unknown:
        return json.dumps({"error": f"Unknown item ids {unknown}. Call list_wardrobe to see valid ids."})

    items = [session.wardrobe[i] for i in item_ids]
    if len(_pieces(items)) < 2:
        return json.dumps({"error": "Style needs at least two visible items to compare, e.g. a top and a bottom. "
                                    "Ask the user what they want to pair it with, or call build_outfit."})
    result = {"items": [i["name"] for i in items], "occasion": occasion, **style_score(items, occasion)}
    in_laundry = [i["name"] for i in items if i.get("status") == "in_laundry"]
    if in_laundry:
        result["note"] = f"{', '.join(in_laundry)} {'is' if len(in_laundry) == 1 else 'are'} in the laundry right now."
    return json.dumps(result)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "style_check",
            "description": (
                "Score how well closet items go together, 0-10, using fixed rules for color harmony, shape balance, "
                "bold patterns and occasion. Returns a verdict, points per rule and one reason per rule (with a fix "
                "when something is off). Use when the user asks 'does this go together?' or 'does this look good?'. "
                "Leave item_ids out to check the outfit build_outfit just picked. Explain the reasons; do not judge "
                "style yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {"type": "array", "items": {"type": "string"},
                                 "description": "Item ids from list_wardrobe, at least two. Omit to check the last build_outfit pick."},
                    "occasion": {"type": "string", "enum": list(OCCASIONS),
                                 "description": "What the outfit is for. Defaults to 'class'."},
                },
                "required": [],
            },
        },
    },
]

TOOL_MAP = {"style_check": style_check}
