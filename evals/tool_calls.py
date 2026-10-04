"""Does the model call the right tools? Runs real prompts through the harness.

Needs Gemini credentials (gcloud auth application-default login). Each case gets a
fresh session. Run: uv run python evals/tool_calls.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import get_session, run_agent  # noqa: E402


def names(calls):
    return [c["name"] for c in calls]


def before(calls, first, second):
    n = names(calls)
    return first in n and second in n and n.index(first) < n.index(second)


def segment_has(calls, key, value):
    return any(
        seg.get(key) == value
        for c in calls if c["name"] == "plan_day_warmth"
        for seg in c["args"].get("segments", [])
    )


CASES = [
    ("I walk 20 minutes to class at 9am, sit in class until 1, then wait 10 minutes for the bus. What should I wear?",
     lambda c: before(c, "plan_day_warmth", "build_outfit") and segment_has(c, "setting", "indoors")),
    ("I always feel cold. Is my grey hoodie enough for a 15 minute walk tonight at 7?",
     lambda c: before(c, "set_cold_sensitivity", "plan_day_warmth")),
    ("My jeans are in the wash. What should I wear for a 10 minute walk to class at 10am?",
     lambda c: before(c, "update_wardrobe", "build_outfit")),
    ("Are there any weather warnings in New York right now?",
     lambda c: "get_weather_alerts" in names(c) and "build_outfit" not in names(c)),
    ("Will it rain tomorrow afternoon in New York?",
     lambda c: "get_forecast_window" in names(c) and "build_outfit" not in names(c)),
    ("What coats do I have?",
     lambda c: "list_wardrobe" in names(c)),
    ("Does my red plaid flannel go with the brown maxi skirt?",
     lambda c: "style_check" in names(c)),
    ("Hi! What can you do?",
     lambda c: names(c) == []),
    ("What should I wear for a 15 minute walk to dinner in Boston tonight at 7?",
     lambda c: any("boston" in str(x["args"].get("location", "")).lower() for x in c if x["name"] == "plan_day_warmth")),
    ("I wore what you suggested yesterday and I was freezing the whole walk.",
     lambda c: any(x["name"] == "record_comfort_feedback" and x["args"].get("feeling") == "too_cold" for x in c)),
    ("I'm biking to work tomorrow at 8am, about 25 minutes. What should I wear?",
     lambda c: segment_has(c, "activity", "biking")),
]


def main():
    passed = 0
    for prompt, check in CASES:
        _, session = get_session(None)
        session.messages.append({"role": "user", "content": prompt})
        try:
            _, calls = run_agent(session)
            ok = check(calls)
        except Exception as e:
            calls, ok = [], False
            print(f"  error: {type(e).__name__}: {str(e)[:120]}")
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {prompt[:70]:<70}  {' > '.join(names(calls)) or '(no tools)'}")
    print(f"\n{passed}/{len(CASES)} passed")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
