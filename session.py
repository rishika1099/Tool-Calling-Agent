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
    wardrobe: dict[str, dict] = field(default_factory=dict)  # item id -> item
    cold_sensitivity: str = "average"  # runs_cold | average | runs_warm
    comfort_offset: float = 0.0  # learned from "I was too cold" feedback (bonus feature)
    images: dict[str, tuple[bytes, str]] = field(default_factory=dict)  # image id -> (bytes, mime type)
    last_plan: dict | None = None  # most recent plan_day_warmth result
    last_outfit: list[str] | None = None  # item ids of the most recent build_outfit pick

    @classmethod
    def new(cls, system_prompt: str) -> "Session":
        wardrobe = {item["id"]: {"status": "clean", "wears": 0, **item} for item in copy.deepcopy(DEMO_WARDROBE)}
        return cls(messages=[{"role": "system", "content": system_prompt}], wardrobe=wardrobe)
