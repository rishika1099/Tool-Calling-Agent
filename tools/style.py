"""Does an outfit go together? Color, shape, pattern and occasion rules.

Owner: style (see PROPOSAL.md and the GitHub issue "style_check").

STATUS: stub. build_outfit already calls style_score() and ignores it while it
returns None, so the app works before this is built.

What to build:
- style_score(outfit, occasion) -> {"score": 0-10, "reasons": [str, ...]} or None
  Rules should be explainable, not the model's opinion:
  * Color: neutrals (black, white, grey, navy, beige, camel, brown) go with
    anything; otherwise check complementary / analogous hues on the color wheel.
    Each item has a hex "color" (the demo closet sets it by hand; scan_garment
    will measure it from photos with Pillow).
  * Shape: balance volume. A long or full skirt goes with a fitted or tucked
    top, not an oversized one; wide-leg pants likewise. Use item["fit"]
    (fitted / relaxed / oversized) and the garment type.
  * Pattern: at most one bold pattern (item["pattern"] == "bold").
  * Occasion: formality 1-3 (item["formality"]) should suit the occasion.
- style_check tool: the same rules for an outfit the user proposes, returning
  the score and reasons so the model can explain them.
Keep it fast: build_outfit calls style_score for every candidate outfit.
"""

import json


def style_score(outfit: list[dict], occasion: str) -> dict | None:
    """Score how well an outfit goes together. Returns None until implemented."""
    return None


def style_check(session, item_ids: list[str], occasion: str = "class") -> str:
    unknown = [i for i in item_ids if i not in session.wardrobe]
    if unknown:
        return json.dumps({"error": f"Unknown item ids {unknown}. Call list_wardrobe to see valid ids."})
    result = style_score([session.wardrobe[i] for i in item_ids], occasion)
    if result is None:
        return json.dumps({"error": "style_check is not built yet. Tell the user style scoring is coming soon "
                                    "and answer from warmth alone."})
    return json.dumps(result)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "style_check",
            "description": (
                "Score how well specific closet items go together (colors, shapes, patterns, occasion), "
                "0-10 with reasons. Use when the user asks 'does this go together?' or 'does this look good?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {"type": "array", "items": {"type": "string"}, "description": "Item ids from list_wardrobe."},
                    "occasion": {"type": "string", "enum": ["everyday", "class", "date", "dinner", "party", "work", "interview"]},
                },
                "required": ["item_ids"],
            },
        },
    },
]

TOOL_MAP = {"style_check": style_check}
