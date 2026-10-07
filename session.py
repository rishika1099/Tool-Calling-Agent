"""Everything the harness remembers about one browser session.

Tools that need it declare a `session` parameter; the harness passes it in, so
the model never has to repeat things we already know (the wardrobe, the last
day plan, uploaded photos).
"""

import copy
from dataclasses import dataclass, field

from tools.catalog import load_demo_wardrobe

DEMO_WARDROBE = load_demo_wardrobe()


@dataclass
class Session:
    messages: list[dict]
    id: str = ""  # so tools can build links like /image/<session id>/<image id>
    wardrobe: dict[str, dict] = field(default_factory=dict)  # item id -> item
    cold_sensitivity: str = "average"  # runs_cold | average | runs_warm
    comfort_offset: float = 0.0  # learned from "I was too cold" feedback (bonus feature)
    images: dict[str, tuple[bytes, str]] = field(default_factory=dict)  # image id -> (bytes, mime type)
    last_plan: dict | None = None  # most recent plan_day_warmth result
    last_outfit: list[str] | None = None  # item ids of the most recent build_outfit pick
    person_photo_id: str | None = None  # the user's full-body photo, for try-on
    setup_done: bool = False  # finished "Build your digital closet" (or chose the demo closet)
    previews: list[str] = field(default_factory=list)  # ids of try-on images, oldest first
    recent_picks: dict[str, list[str]] = field(default_factory=dict)  # for_whom -> their most recent
    # build_outfit top pick's item ids (every slot, not just skin-touching ones - a single pair of
    # boots is still one physical object), so build_outfit can automatically steer a different
    # for_whom away from suggesting the exact same item before either has actually claimed anything

    @classmethod
    def new(cls, system_prompt: str, session_id: str = "") -> "Session":
        return cls(messages=[{"role": "system", "content": system_prompt}], id=session_id, wardrobe=demo_wardrobe())


def demo_wardrobe() -> dict[str, dict]:
    return {item["id"]: {"status": "clean", "wears": 0, "worn_by": None, "worn_for": None,
                          "qty": 1, "qty_in_laundry": 0, "lifetime_wears": 0, **item}
            for item in copy.deepcopy(DEMO_WARDROBE)}


# Pieces every outfit needs; missing ones can be borrowed from the demo closet.
ESSENTIALS = {"top": ("base_top", "one_piece"), "bottom": ("bottom", "one_piece"), "coat": ("outer",), "shoes": ("shoes",)}
BORROW = {"top": "tee-white", "bottom": "jeans-indigo", "coat": "parka-black", "shoes": "boots-leather"}
