# Layer Lab

**Dress for the hours you're actually outside.**

Layer Lab is a chat agent for students facing a cold NYC winter, especially those from warmer
climates who don't know whether their clothes are warm enough. Describe your day ("walk 20 minutes
to class at 9, sit in class until 1, wait for the bus"), and Layer Lab:

1. pulls the **hourly forecast** for the hours you're outside (Open-Meteo),
2. works out how much **clothing warmth (clo)** you need for each part of the day, indoors and out,
   adjusted for how quickly you feel cold,
3. picks an outfit **from your own closet** that works both outside and in a heated classroom,
   skipping anything in the laundry and warning about rain and wind.

IEOR 4570 Project 1. Team: Rishika, Shreya, Kshamaa.

## Sample queries

1. `I walk 20 minutes to class at 9am, sit in class until 1, then wait 10 minutes for the bus. What should I wear?`
2. `I always feel cold. Is my grey hoodie enough for a 15 minute walk tonight at 7?`
3. `My jeans are in the wash. I have an interview downtown tomorrow at 10: a 10 minute walk, 30 minutes on the subway, then an hour indoors.`

A demo closet is loaded in every new session, so these work without uploading anything.

## Tools

| Tool | Owner | What it does |
|---|---|---|
| `get_forecast_window` | shared | Hour-by-hour forecast for part of a day (Open-Meteo, external API) |
| `plan_day_warmth` | Rishika | Clothing warmth needed per segment of the day, indoor vs outdoor, with a layering plan |
| `set_cold_sensitivity` | Rishika | Remembers whether the user runs cold, average or warm |
| `build_outfit` | shared | Ranks outfits from the closet against the plan (warmth, rain, wind, occasion, laundry) |
| `list_wardrobe` / `update_wardrobe` | shared | Shows the closet; marks items worn, clean or in the laundry |
| `scan_garment` | Shreya | Adds clothes from a photo, reading the care label for the exact fiber mix *(in progress)* |
| `style_check` | Kshamaa | Scores whether an outfit goes together: color, shape, pattern, occasion *(in progress)* |
| `try_on_outfit` | bonus | Shows the user wearing the outfit (Vertex AI) *(in progress)* |

Every `/chat` response returns `response`, `session_id` and `tool_calls` (name, args, result),
and the page shows each tool call above the answer.

## How warmth is calculated

Warmth is measured in **clo** (a t-shirt is 0.08, a thick sweater 0.36, a down parka about 0.8).

- **Outdoors** we use ISO 11079's duration-limited required clothing insulation (IREQ): the body
  may run down a limited amount of stored heat during a short trip. `clo_min` allows the ISO limit
  of 40 Wh/m²; `clo_ideal` allows half of that. The ISO 9920 correction accounts for wind and
  walking pushing air through clothes.
- **Indoors** we use ASHRAE 55's PMV comfort model: `clo_ideal` is PMV 0 (neutral), `clo_min`
  is PMV -0.5 (edge of the comfort zone). Our PMV code reproduces the ISO 7730 reference values,
  and you can check results with the [CBE Thermal Comfort Tool](https://comfort.cbe.berkeley.edu/).
- **Heating:** NYC law requires heat between 6am and 10pm when it's below 55°F outside, so on those
  days we assume rooms are about 72°F, and about 75°F otherwise.
- **Garment values** come from ASHRAE 55's garment table where available (`data/garments.csv`
  marks which are estimates). **Fiber behavior** in rain and wind (`data/materials.csv`), the
  cold-sensitivity offset (±0.2 clo) and the windproof bonus (10%) are team estimates.

Simplifications: radiant temperature equals air temperature (no sun), wind at body height is two
thirds of the forecast 10 m wind, and trips shorter than 30 minutes count as 30 minutes.
Layer Lab gives clothing suggestions, not medical or safety advice.

## Run locally

1. A GCP project with billing and Vertex AI enabled (see the course's *Setting up GCP and Gemini* guide).
2. `gcloud auth application-default login`
3. `uv run app.py`, then open http://localhost:8000

## Deploy

Cloud Run with continuous deploy from this repo (course guide *Deploying to Cloud Run from GitHub*):
buildpack, entrypoint `uvicorn app:app --host 0.0.0.0 --port $PORT`, IAP restricted to `columbia.edu`.

## Project layout

```
app.py              harness (tool-calling loop), sessions, /chat /upload /wardrobe endpoints
session.py          per-session state: messages, closet, cold sensitivity, last plan, photos
tools/              one module per tool area; each exports TOOLS and TOOL_MAP
data/               garment clo values, fiber behavior, demo closet
static/             frontend (index.html, style.css, app.js)
PROPOSAL.md         plan, features and who owns what
DESIGN.md           visual direction and inspiration
```
