"""Garment and material reference data, loaded once from data/*.csv.

garments.csv gives each garment type its warmth in clo (ASHRAE 55 where
available, marked "estimate" otherwise). materials.csv says how each fiber
behaves when wet or windy. These are team estimates; see the README.
"""

import csv
import json
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"


def _read_csv(name: str) -> dict[str, dict]:
    with open(DATA / name, newline="") as f:
        rows = list(csv.DictReader(f))
    key = next(iter(rows[0]))
    return {row[key]: row for row in rows}


GARMENTS = _read_csv("garments.csv")
MATERIALS = _read_csv("materials.csv")

# Where each slot sits when you get dressed. Outer and accessory slots come off indoors.
INDOOR_SLOTS = {"underwear", "base_top", "mid_top", "bottom", "one_piece", "legwear", "socks", "shoes"}
OUTDOOR_ONLY_SLOTS = {"outer", "head", "hands", "neck"}


def load_demo_wardrobe() -> list[dict]:
    with open(DATA / "demo_wardrobe.json") as f:
        return json.load(f)


def slot(item: dict) -> str:
    return GARMENTS[item["garment_type"]]["slot"]


def clo(item: dict) -> float:
    return float(GARMENTS[item["garment_type"]]["clo"])


def wet_retention(item: dict) -> float:
    """Share of an item's warmth left when soaked, weighted by its fiber mix."""
    mix = item.get("materials") or {"cotton": 100}
    total = sum(mix.values()) or 1
    return sum(float(MATERIALS.get(m, MATERIALS["cotton"])["wet_retention"]) * pct for m, pct in mix.items()) / total


def is_windproof(item: dict) -> bool:
    return bool(item.get("windproof"))


def keeps_rain_out(item: dict) -> bool:
    return item.get("shell") in ("water_resistant", "waterproof")
