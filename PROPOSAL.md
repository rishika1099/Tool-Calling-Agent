# Layer Lab: Proposal and Team Plan

Due **Wed Oct 7, 11:59pm**. Team: Rishika (rishika1099), Shreya (shreyashetty2), Kshamaa (KshamaaS).

## Problem
- Students facing their first NYC winter, especially from warmer climates, don't know if their clothes are warm enough.
- Weather apps give a temperature, not an answer to "what should I wear for *my* day?"
- The real NYC problem: freezing outside, overheating in a heated classroom.

## How it works
- The user describes their day; the agent splits it into segments (outdoors / indoors / transit, and sitting / standing / walking / biking).
- It pulls the hourly forecast for exactly those hours.
- It calculates warmth needed in clo (ISO 11079 outdoors, ASHRAE 55 PMV indoors), adjusted for how quickly the user feels cold.
- It picks an outfit from the user's closet: a base that's comfortable indoors plus layers to take off, skipping laundry, warning about rain and wind.
- Users add clothes by photographing them and their care labels.
- Bonus: a try-on image of the user in the outfit.

## Features
| Feature | Status |
|---|---|
| Hourly forecast for the user's outdoor hours | done |
| Official NWS weather alerts (wind chill, winter storms) in the day plan | done |
| Warmth needed per segment, indoor vs outdoor, layering plan | done |
| Cold sensitivity ("I run cold / average / I run warm") | done (feedback learning is a bonus) |
| Indoors vs outdoors, NYC heat-law indoor temperatures, transit = coat on | done |
| Outfit builder: warmth, rain, wind, occasion formality, laundry | done |
| Laundry: manual toggle in chat and closet panel | done |
| Laundry: automatic wear limits per garment type | to do (Shreya) |
| Add clothes from photos + care labels | to do (Shreya) |
| Style: color, shape, pattern, occasion rules | to do (Kshamaa) |
| Motion with anime.js: timeline, outfit, closet, chat | first pass done |
| Frontend polish, mobile, dark mode, effects inspired by reactbits / originkit | to do (Kshamaa) |
| Offline tests (`uv run pytest`) and tool-selection evals | done (run evals once credentials are set up) |
| Architecture diagram in the README | done |
| Deploy to Cloud Run | to do (Rishika) |
| Comfort feedback ("I was freezing") adjusts future plans | bonus (Rishika) |
| Try-on image (Vertex AI) | bonus (Rishika) |
| Launch video with /brag | last day (Kshamaa) |

## Who owns what
Each person owns one **original tool** (the course requires one per team member).

### Rishika: warmth + deployment
- **Original tool:** `plan_day_warmth` (`tools/warmth.py`). Built; verify values against the CBE Thermal Comfort Tool and tune the system prompt with real chats.
- Deploy to Cloud Run with continuous deploy and Columbia-only IAP, early, so every push is tested live.
- Bonus: `record_comfort_feedback` (adjusts `session.comfort_offset`), `try_on_outfit` (`tools/tryon.py`).
- Final: `submission.json` with everyone's UNI, README sample queries tested on the deployed URL.

### Shreya: wardrobe
- **Original tool:** `scan_garment` (`tools/wardrobe.py`): garment photo + care label photo, then Gemini vision gives type, fiber mix, fit, formality; Pillow measures the color; the item is saved to the session closet. The spec is in the file.
- Automatic laundry tracking: wear limits per garment type.
- Sample garment and care-label photos in `data/demo_photos/` so graders can test scanning.

### Kshamaa: style + design
- **Original tool:** `style_check` and `style_score` (`tools/style.py`): explainable rules for color harmony, shape balance (e.g. maxi skirt + fitted top), one bold pattern, occasion. `build_outfit` already calls `style_score`, so outfits improve automatically once it returns scores.
- Frontend polish following `DESIGN.md`: weather-reactive header, a style score in the outfit card, mobile check, dark mode check.
- Last day: launch video with [/brag](https://github.com/latent-spaces/brag) for the README.

## Timeline
| Dates | Goal |
|---|---|
| Sep 29 to 30 | Everyone: `uv` + `gcloud auth application-default login`, run locally. Rishika deploys the skeleton. |
| Oct 1 to 3 | Original tools built, each on its own branch, merged by PR |
| Oct 4 to 5 | Integration, UI polish, bonus features |
| Oct 6 | Feature freeze. Test the 3 README queries on the deployed URL. Launch video. |
| Oct 7 | Submit the repo URL on Courseworks (one person) |

## How we work
- `main` auto-deploys to Cloud Run, so keep it working: branch per feature, open a PR, get one teammate to look.
- Tools follow the pattern in `tools/`: a function, a JSON schema in `TOOLS`, an entry in `TOOL_MAP`. Return JSON; errors are JSON that tell the model what to do next.
- A tool that needs the closet or plan takes a `session` parameter; the harness passes it in.
- Must-haves first: warmth answers must never depend on scanning, style or try-on.
