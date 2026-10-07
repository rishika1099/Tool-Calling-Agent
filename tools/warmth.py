"""How much clothing warmth a person needs, segment by segment through their day.

Owner: warmth (see PROPOSAL.md).

Warmth is measured in clo (a t-shirt is 0.08, a wool coat about 0.6). For each
part of the day we compute two numbers:

- clo_min:   the least clothing before the user is too cold
- clo_ideal: clothing for feeling comfortable

Outdoors (short exposures) we use ISO 11079's duration-limited IREQ: the body
may lose a limited amount of stored heat during the trip. clo_min allows the
ISO limit of 40 Wh/m2, clo_ideal allows half of it. The ISO 9920 correction
then accounts for wind and walking pumping air through clothes.

Indoors we use ASHRAE 55's PMV comfort model, assuming buildings are heated
to about 72F on days when NYC's heat law applies (below 55F outside) and about
75F otherwise. clo_ideal puts PMV at 0 (neutral), clo_min at -0.5 (edge of the
comfort zone).
You can check these values with the CBE Thermal Comfort Tool.

Simplifications, documented in the README: radiant temperature equals air
temperature (no sun), wind at body height is two thirds of the 10 m forecast,
trips shorter than 30 minutes are treated as 30 minutes.
"""

import json
import math

import requests

from .alerts import active_alerts
from .forecast import ForecastError, hourly_for_day, to_f, to_mph

MET = 58.2  # W/m2 per met
CLO = 0.155  # m2K/W per clo

# ASHRAE 55 metabolic rates. Sitting is seated writing/typing, walking is a brisk
# city pace (1.2 m/s), biking is an estimate for easy city cycling.
ACTIVITIES = {
    "sitting": {"met": 1.1, "speed_ms": 0.0},
    "standing": {"met": 1.2, "speed_ms": 0.0},
    "walking": {"met": 2.6, "speed_ms": 1.2},
    "biking": {"met": 4.0, "speed_ms": 4.5},
}

# Indoor conditions we don't have a forecast for. NYC's heat law requires heat between
# 6am and 10pm whenever it is below 55F outside, so we assume buildings are heated
# on those days and around 75F otherwise.
HEAT_LAW_C = 12.8  # 55F
INDOOR_SETTINGS = {
    "indoors": {"heated": {"temp_c": 22.0, "humidity": 30, "air_ms": 0.1}, "unheated": {"temp_c": 24.0, "humidity": 45, "air_ms": 0.1}},
    "transit": {"heated": {"temp_c": 20.0, "humidity": 40, "air_ms": 0.2}, "unheated": {"temp_c": 24.0, "humidity": 50, "air_ms": 0.2}},
}

SENSITIVITY_OFFSET = {"runs_cold": 0.2, "average": 0.0, "runs_warm": -0.2}  # clo, team estimate
WIND_AT_BODY = 0.67  # 10 m wind -> roughly 1.5 m
RAIN_MM = 0.2
MIN_EXPOSURE_MIN = 30  # treat short trips as at least this long, so they still count
RAIN_CHANCE = 50


def _psat(t: float) -> float:
    """Saturated water vapour pressure in kPa at t degrees C."""
    return 0.6105 * math.exp(17.27 * t / (t + 237.3))


def _outdoor_clo(temp_c: float, humidity: float, air_ms: float, activity: str, minutes: int, heat_debt: float) -> float:
    """ISO 11079 duration-limited IREQ: clothing (clo) that keeps body heat loss under
    heat_debt Wh/m2 over the exposure. The ISO limit is 40; we use 20 for "ideal"."""
    met = ACTIVITIES[activity]["met"] * MET
    walk = min(ACTIVITIES[activity]["speed_ms"], 1.2)
    var = max(air_ms, 0.4)
    pa = _psat(temp_c) * humidity / 100
    storage = heat_debt / (max(minutes, MIN_EXPOSURE_MIN) / 60)  # W/m2 the body may run down

    t_skin, wetness = 33.34 - 0.0354 * met, 0.06  # ISO 11079 IREQ_min skin criteria
    hc = 3.5 + 5.2 * var if var <= 1 else 8.7 * var**0.6
    ia = 1 / (hc + 4.0)  # boundary air layer, with ~4 W/m2K radiative exchange
    breathing = 0.0014 * met * (34 - temp_c) + 0.0173 * met * (5.87 - pa)

    icl = 0.2
    for _ in range(100):
        fcl = 1 + 1.97 * icl
        total = icl + ia / fcl
        sweat = wetness * (_psat(t_skin) - pa) / (0.06 / 0.38 * total)
        dry_loss = met + storage - breathing - sweat
        if dry_loss <= 0:
            return 0.0
        icl = max(0.0, 0.5 * icl + 0.5 * ((t_skin - temp_c) / dry_loss - ia / fcl))

    # ISO 9920: wind and walking pump air through clothing, so the label value must be higher.
    v = min(var, 3.5) - 0.15
    correction = math.exp(-0.281 * v + 0.044 * v**2 - 0.492 * walk + 0.176 * walk**2)
    fcl = 1 + 1.97 * icl
    return max(0.0, ((icl + ia / fcl) / correction - 0.111 / fcl) / CLO)


def _pmv(temp_c: float, humidity: float, air_ms: float, met: float, clo: float) -> float:
    """ASHRAE 55 / ISO 7730 Predicted Mean Vote (-3 cold ... +3 hot), air temp = radiant temp."""
    pa = humidity * 10 * math.exp(16.6536 - 4030.183 / (temp_c + 235))
    icl, m = CLO * clo, met * MET
    fcl = 1 + 1.29 * icl if icl <= 0.078 else 1.05 + 0.645 * icl
    hcf = 12.1 * math.sqrt(air_ms)
    taa = tra = temp_c + 273
    p1 = icl * fcl
    p2, p3, p4 = p1 * 3.96, p1 * 100, p1 * taa
    p5 = 308.7 - 0.028 * m + p2 * (tra / 100) ** 4
    xn, xf = (taa + (35.5 - temp_c) / (3.5 * icl + 0.1)) / 100, 0.0
    hc = hcf
    for _ in range(150):
        if abs(xn - xf) < 0.00015:
            break
        xf = (xf + xn) / 2
        hc = max(hcf, 2.38 * abs(100 * xf - taa) ** 0.25)
        xn = (p5 + p4 * hc - p2 * xf**4) / (100 + p3 * hc)
    tcl = 100 * xn - 273
    losses = (
        3.05e-3 * (5733 - 6.99 * m - pa)
        + (0.42 * (m - MET) if m > MET else 0)
        + 1.7e-5 * m * (5867 - pa)
        + 0.0014 * m * (34 - temp_c)
        + 3.96 * fcl * (xn**4 - (tra / 100) ** 4)
        + fcl * hc * (tcl - temp_c)
    )
    return (0.303 * math.exp(-0.036 * m) + 0.028) * (m - losses)


def _indoor_clo(temp_c: float, humidity: float, air_ms: float, activity: str, target_pmv: float) -> float:
    """Clothing (clo) that puts PMV at target: 0 is neutral, -0.5 is the edge of ASHRAE 55's comfort zone."""
    met = ACTIVITIES[activity]["met"]
    lo, hi = 0.0, 3.0
    if _pmv(temp_c, humidity, air_ms, met, lo) >= target_pmv:
        return 0.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _pmv(temp_c, humidity, air_ms, met, mid) < target_pmv else (lo, mid)
    return (lo + hi) / 2


def _parse_start(start: str) -> tuple[int, int]:
    try:
        hour, minute = (int(x) for x in start.split(":"))
        assert 0 <= hour <= 23 and 0 <= minute <= 59
        return hour, minute
    except (ValueError, AssertionError):
        raise ForecastError(f"Segment start '{start}' is not valid. Use 24-hour HH:MM, e.g. '08:00' or '18:30'.")


def plan_day_warmth(session, segments: list[dict], location: str = "New York", day: str = "today",
                     cold_sensitivity: str | None = None, for_whom: str | None = None) -> str:
    """Warmth needed (clo) for each part of a day, plus a layering plan.

    By default this plans for the primary user: it reads session.cold_sensitivity and adds
    session.comfort_offset, their own personally learned feedback adjustment. Pass cold_sensitivity
    to plan for someone else who shares this chat (e.g. a roommate or friend) without touching the
    user's saved setting: the override replaces session.cold_sensitivity for this call only, and
    comfort_offset is deliberately not added, since that adjustment was learned from the primary
    user's own feedback and should not be assumed for another person.

    for_whom labels who this specific plan is for (defaults to "me"), stored in the result so
    build_outfit can tell if it's about to use a plan that was actually built for someone else - a
    plain-text warning in that case, not a hard block, since build_outfit always trusts whichever
    plan_day_warmth result ran most recently and has no way to re-derive the right one on its own.
    """
    if not segments:
        return json.dumps({"error": "Give at least one segment, e.g. {'start': '08:00', 'minutes': 20, 'activity': 'walking', 'setting': 'outdoors'}."})
    if cold_sensitivity is not None and cold_sensitivity not in SENSITIVITY_OFFSET:
        return json.dumps({"error": f"cold_sensitivity must be one of {list(SENSITIVITY_OFFSET)}."})
    try:
        place, wanted, hours = hourly_for_day(location, day)
        by_hour = {h["hour"]: h for h in hours}
        daytime = [h["temp_c"] for h in hours if 6 <= h["hour"] < 22]
        heating_on = sum(daytime) / len(daytime) < HEAT_LAW_C
        sensitivity = cold_sensitivity or session.cold_sensitivity
        offset = SENSITIVITY_OFFSET[sensitivity] + (0.0 if cold_sensitivity else session.comfort_offset)

        planned = []
        for seg in segments:
            activity, setting = seg.get("activity"), seg.get("setting")
            if activity not in ACTIVITIES:
                raise ForecastError(f"Activity '{activity}' is not one of {list(ACTIVITIES)}.")
            if setting not in ("outdoors", *INDOOR_SETTINGS):
                raise ForecastError(f"Setting '{setting}' is not one of ['outdoors', {', '.join(map(repr, INDOOR_SETTINGS))}].")
            hour, minute = _parse_start(seg.get("start", ""))
            minutes = max(1, int(seg.get("minutes", 30)))

            if setting == "outdoors":
                span = [by_hour[h] for h in range(hour, min(24, hour + math.ceil((minute + minutes) / 60)))]
                worst = min(span, key=lambda h: h["feels_like_c"])
                air = worst["wind_ms"] * WIND_AT_BODY + ACTIVITIES[activity]["speed_ms"]
                conditions = {
                    "temp_f": to_f(worst["temp_c"]),
                    "feels_like_f": to_f(worst["feels_like_c"]),
                    "wind_mph": to_mph(max(h["wind_ms"] for h in span)),
                    "precip_chance_pct": max(h["precip_chance"] for h in span),
                    "rain": any(h["precip_mm"] >= RAIN_MM or h["precip_chance"] >= RAIN_CHANCE for h in span),
                    "snow": any(h["snow_cm"] > 0 for h in span),
                }
                need_min = _outdoor_clo(worst["temp_c"], worst["humidity"], air, activity, minutes, heat_debt=40)
                need_ideal = _outdoor_clo(worst["temp_c"], worst["humidity"], air, activity, minutes, heat_debt=20)
            else:
                indoor = INDOOR_SETTINGS[setting]["heated" if heating_on else "unheated"]
                need_min = _indoor_clo(indoor["temp_c"], indoor["humidity"], indoor["air_ms"], activity, target_pmv=-0.5)
                need_ideal = _indoor_clo(indoor["temp_c"], indoor["humidity"], indoor["air_ms"], activity, target_pmv=0.0)
                conditions = {"temp_f": to_f(indoor["temp_c"]),
                              "note": "heating on (below 55F outside)" if heating_on else "heating off, typical room temperature"}

            planned.append({
                "start": f"{hour:02d}:{minute:02d}",
                "minutes": minutes,
                "activity": activity,
                "setting": setting,
                **conditions,
                "clo_min": round(max(0.0, need_min + offset), 2),
                "clo_ideal": round(max(0.0, need_ideal + offset), 2),
            })
    except ForecastError as e:
        return json.dumps({"error": str(e)})
    except requests.RequestException as e:
        return json.dumps({"error": f"Weather service failed ({type(e).__name__}). Try again in a moment."})

    # Coats come off indoors but stay on for a subway or bus ride.
    outdoor = [s for s in planned if s["setting"] == "outdoors"]
    coat_on = [s for s in planned if s["setting"] != "indoors"]
    inside = [s for s in planned if s["setting"] == "indoors"]
    summary = {
        "indoor_clo_ideal": max((s["clo_ideal"] for s in inside), default=None),
        "indoor_clo_min": max((s["clo_min"] for s in inside), default=None),
        "outdoor_clo_ideal": max((s["clo_ideal"] for s in coat_on), default=None),
        "outdoor_clo_min": max((s["clo_min"] for s in coat_on), default=None),
        "rain_expected": any(s["rain"] for s in outdoor),
        "snow_expected": any(s["snow"] for s in outdoor),
        "max_wind_mph": max((s["wind_mph"] for s in outdoor), default=0),
    }
    if summary["indoor_clo_ideal"] is not None and summary["outdoor_clo_ideal"] is not None:
        summary["removable_layers_clo"] = round(max(0.0, summary["outdoor_clo_ideal"] - summary["indoor_clo_ideal"]), 2)

    plan = {
        "location": place["name"],
        "date": wanted.isoformat(),
        "for_whom": for_whom or "me",
        "cold_sensitivity": sensitivity,
        "personal_adjustment_clo": round(offset, 2),
        "buildings_heated": heating_on,
        "segments": planned,
        "summary": summary,
        "active_alerts": active_alerts(place),  # NWS, US only; None if unavailable
        "clo_guide": "t-shirt 0.08, thick sweater 0.36, jeans 0.24, wool coat 0.60, down parka 0.80",
    }
    session.last_plan = plan
    return json.dumps(plan)


def set_cold_sensitivity(session, level: str) -> str:
    """Remember whether the user runs cold, average or warm."""
    if level not in SENSITIVITY_OFFSET:
        return json.dumps({"error": f"level must be one of {list(SENSITIVITY_OFFSET)}."})
    session.cold_sensitivity = level
    return json.dumps({"cold_sensitivity": level, "adjustment_clo": SENSITIVITY_OFFSET[level],
                       "note": "Call plan_day_warmth again so the plan uses the new setting."})


FEEDBACK_STEP = {"too_cold": 0.1, "just_right": 0.0, "too_warm": -0.1}  # clo per report, team estimate
FEEDBACK_CAP = 0.3


def record_comfort_feedback(session, feeling: str) -> str:
    """Learn from how an outfit actually felt: nudge future plans warmer or cooler."""
    if feeling not in FEEDBACK_STEP:
        return json.dumps({"error": f"feeling must be one of {list(FEEDBACK_STEP)}."})
    session.comfort_offset = round(max(-FEEDBACK_CAP, min(FEEDBACK_CAP, session.comfort_offset + FEEDBACK_STEP[feeling])), 2)
    total = round(SENSITIVITY_OFFSET[session.cold_sensitivity] + session.comfort_offset, 2)
    at_cap = abs(session.comfort_offset) >= FEEDBACK_CAP and feeling != "just_right"
    return json.dumps({
        "feeling": feeling,
        "learned_adjustment_clo": session.comfort_offset,
        "total_personal_adjustment_clo": total,
        "note": ("That is the largest adjustment feedback can make; suggest the 'I run cold / warm' setting too. "
                 if at_cap else "") + "Future plans will ask for this much more (or less) clothing. "
                "Call plan_day_warmth again if the user wants a new outfit now.",
    })


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "plan_day_warmth",
            "description": (
                "Work out how much clothing warmth (in clo) the user needs for each part of their day, "
                "using the hourly forecast for outdoor parts and typical temperatures for indoor ones. "
                "Returns clo_min (lowest before feeling cold) and clo_ideal (comfortable) per segment, "
                "and a summary with indoor vs outdoor needs and how many clo of removable layers to carry. "
                "Call this first for any 'what should I wear' question, then call build_outfit. "
                "Break the user's description into segments; include indoor parts (class, office, subway) "
                "because they decide what can be worn underneath. For a second person sharing the closet, "
                "call this separately for them too, passing their own cold_sensitivity - even if their "
                "schedule is word-for-word identical to the primary user's. build_outfit has no sensitivity "
                "parameter of its own; it only ever uses whichever plan_day_warmth result ran most recently, "
                "so reusing one call for both people would silently apply one person's warmth preference to "
                "both of them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "segments": {
                        "type": "array",
                        "description": "The user's day in order, e.g. walk to class, sit in class, wait for the bus.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "string", "description": "Start time, 24-hour HH:MM, e.g. '08:00'."},
                                "minutes": {"type": "integer", "description": "How long this part lasts, in minutes."},
                                "activity": {"type": "string", "enum": list(ACTIVITIES),
                                             "description": "What the body is doing. Waiting at a stop is 'standing'."},
                                "setting": {"type": "string", "enum": ["outdoors", *INDOOR_SETTINGS],
                                            "description": "'indoors' is class, office, library; coats come off. 'transit' is inside a subway car or bus; coats stay on."},
                            },
                            "required": ["start", "minutes", "activity", "setting"],
                        },
                    },
                    "location": {"type": "string", "description": "City name. Defaults to New York."},
                    "day": {"type": "string", "description": "'today', 'tomorrow', or YYYY-MM-DD within the next 7 days."},
                    "cold_sensitivity": {
                        "type": "string", "enum": list(SENSITIVITY_OFFSET),
                        "description": "Required every time this call is for someone other than the primary user, "
                                       "e.g. a friend or roommate - never leave it out for them, even if you already "
                                       "called this for the primary user moments ago with an identical schedule. "
                                       "Omitting it does NOT mean 'neutral': it silently falls back to the primary "
                                       "user's own saved sensitivity, which would plan the wrong person's warmth "
                                       "needs for them. Overrides the saved setting for this call only and skips "
                                       "the user's own learned comfort adjustment. Omit only when this call really "
                                       "is for the primary user themselves.",
                    },
                    "for_whom": {
                        "type": "string",
                        "description": "Who this plan is for, e.g. 'me' or a name - pass the same label you'll use "
                                       "on the matching build_outfit call. Only needed when more than one person "
                                       "shares this closet; omit for a single user. build_outfit warns if it ends "
                                       "up using a plan built for someone else, so this is what makes that catch "
                                       "possible.",
                    },
                },
                "required": ["segments"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_cold_sensitivity",
            "description": "Save how quickly the user feels cold. Use when they say things like 'I always feel cold' or 'I run hot'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "enum": list(SENSITIVITY_OFFSET)},
                },
                "required": ["level"],
            },
        },
    },
]

TOOLS.append({
    "type": "function",
    "function": {
        "name": "record_comfort_feedback",
        "description": (
            "Record how an outfit actually felt after the user wore it, so future plans adapt: each 'too_cold' "
            "asks for 0.1 clo more next time, each 'too_warm' 0.1 less (up to 0.3 either way). Use when the user "
            "reports on a past outfit, e.g. 'I was freezing in that yesterday' or 'that was perfect'. "
            "For a general trait ('I always run cold') use set_cold_sensitivity instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feeling": {"type": "string", "enum": list(FEEDBACK_STEP), "description": "How the outfit felt overall."},
            },
            "required": ["feeling"],
        },
    },
})

TOOL_MAP = {"plan_day_warmth": plan_day_warmth, "set_cold_sensitivity": set_cold_sensitivity,
            "record_comfort_feedback": record_comfort_feedback}
