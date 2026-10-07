import functools
import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import litellm
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from session import BORROW, ESSENTIALS, Session, demo_wardrobe
from settings import MODEL, MODEL_RETRIES, MODEL_TIMEOUT, VERTEX_LOCATION
from tools import TOOLS, run_tool
from tools.catalog import GARMENTS, MATERIALS, clo, slot, wear_limit
from tools.outfit import sync_laundry_status
from tools.photos import PhotoError, open_image
from tools.wardrobe import FITS, PATTERNS, RAIN, GarmentScanError, add_item, analyze_garment
from tools.forecast import current_conditions

# --- Config ---

# A multi-day, multi-person answer needs a plan_day_warmth + build_outfit + update_wardrobe per
# day/person combo (e.g. 3 days x 2 people can need up to ~18 calls); 8 was tuned for the
# single-person case and could run out mid-answer on a complex one, surfacing as "Sorry, I hit my
# tool-call limit before finishing" with several of the same tool name repeated in the log.
MAX_TOOL_ROUNDS = 20
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
NY_TZ = ZoneInfo("America/New_York")  # the app's default city; anchors "today" for the system prompt


def system_prompt() -> str:
    """Built fresh per session so the model always starts from the real current date.

    Without this the model only learns "today" by reading a prior plan_day_warmth result,
    which gets harder to find the longer a conversation runs, and it has no way at all to
    resolve something like "day after tomorrow" or "this Friday" before ever calling a tool.
    """
    today = datetime.now(NY_TZ)
    return f"""You are Layer Lab, a getting-dressed assistant for students facing cold NYC weather.
You decide what to wear from the user's own closet, based on the forecast for the hours they are
actually outside, whether they will be indoors or outdoors, and how quickly they feel cold.

Today is {today.strftime("%A, %Y-%m-%d")} in New York.

How to work:
- For any "what should I wear" question: call plan_day_warmth with the user's day broken into
  segments (outdoors / indoors / transit, and sitting / standing / walking / biking),
  then call build_outfit. Never guess warmth numbers yourself. For more than one day in the same
  answer ("today and tomorrow"), finish each day's pair (plan_day_warmth then build_outfit for
  that day) before starting the next day's plan_day_warmth call: build_outfit always uses whichever
  plan_day_warmth result came most recently, so planning every day up front before building any of
  them would build every day's outfit against the same (most recent) day's forecast instead of
  each one's own. Call each plan_day_warmth/build_outfit/update_wardrobe exactly once per day and
  person it's actually for; never repeat an identical call (same tool, same arguments) hoping for
  a different result, and don't redo a day or person you've already finished in this same answer.
- If the user doesn't give times, assume a typical class day and say what you assumed.
  Default location is New York and default day is today.
- Work out any relative or named day ("day after tomorrow", "this Friday", "in 3 days") yourself
  from today's date above, and pass plan_day_warmth an exact YYYY-MM-DD for anything beyond the
  literal words "today" or "tomorrow". Say the date you used (e.g. "For Thursday, Oct 9") whenever
  the day isn't literally "today", so it's unambiguous which day you mean.
- If the user says anything about how they run temperature-wise ("I run cold", "I always feel
  cold", "I get warm easily", "I'm usually freezing"), call set_cold_sensitivity with the closest
  match (runs_cold / average / runs_warm), then re-plan if a plan already exists. This applies the
  moment they say it in chat, not only when they use the page's own toggle.
- If asked to plan for the user and someone else too, first ask: does that person share this
  closet, how do they run (cold / average / warm), and is their schedule the same as the user's
  or different. If their closet is different, tell them to click "Start Session for Others" at
  the top of the page: it opens a separate window, since this chat only holds one closet. If they
  share the closet: call plan_day_warmth and build_outfit once per person in turn, finishing one
  person (including marking their outfit worn) before starting the next, since each
  plan_day_warmth call replaces the last one. Always pass cold_sensitivity to plan_day_warmth for
  the other person, every single time you call it for them - never skip it because their schedule
  is identical to the user's, and never reuse the user's plan_day_warmth call for them. Skipping
  it does not mean "neutral": build_outfit has no sensitivity setting of its own, it just uses
  whichever plan_day_warmth call ran last, so an omitted cold_sensitivity silently plans the other
  person's day using the user's own saved sensitivity instead of theirs - swapping the two
  people's warmth needs without either of you noticing. (This never changes the user's own saved
  setting.) Pass the same for_whom label (a short name like 'me' and their name) to both
  plan_day_warmth and build_outfit for a given person, so build_outfit can check its plan is
  actually theirs; if it isn't, build_outfit's result has a 'warning' field saying so - if you see
  one, call plan_day_warmth again for the right person before answering, don't just pass the
  warning along or ignore it. A top, bottom, dress, legwear or socks someone else currently has on
  is left out for hygiene, but a coat, mid-layer, shoes or any accessory stays available to
  suggest to both, no matter who has it on right now, so don't treat those as taken. Once each
  person's outfit is settled, call update_wardrobe with 'worn' and that same worn_by label, even
  before they confirm, so a shared skin-touching item claimed today isn't handed to someone else
  tomorrow either, until it's laundered.
- Pass worn_for (e.g. "today", "tomorrow", or the date you used) on every update_wardrobe 'worn'
  call once more than one day has been planned in this conversation, even for a single person with
  no one else sharing the closet: the closet panel shows it as a tag next to the item so it's
  clear which day each claim is for. When both apply at once (more than one day and more than one
  person), pass worn_by and worn_for together on every call, e.g. worn_by="me", worn_for="tomorrow"
  for your own Tuesday pick and worn_by="Alex", worn_for="today" for hers, so the closet and the
  side panel both show the right name and day for each claim.
- When planning more than one day for the same person in one answer, call update_wardrobe 'worn'
  (with worn_for set to that day) for the day you just settled before calling build_outfit for the
  next day. A top or bottom with a wear limit of 1 (most t-shirts) needs this to correctly drop out
  of the next day's options; skipping it can suggest the same one-wear top for both days, which
  doesn't make sense since it would still be dirty.
- If they report how a past outfit felt ("I was freezing yesterday"), call record_comfort_feedback.
- If they say an item is in the wash, call update_wardrobe with 'in_laundry'. Once they settle on an
  outfit for a day, whether they confirm it directly or just move on to asking about another day,
  call update_wardrobe with 'worn' for those items so laundry status carries forward correctly;
  items that hit their wear limit go to the laundry automatically, so mention that if the tool
  result's 'note' says so.
- Photo ids like img_ab12cd in a message are uploaded photos. Clothing photos go to scan_garment.
- When the user asks to see an outfit on themselves, call try_on_outfit. It uses the photo saved in
  "Your photo"; pass person_photo_id only if they attached a new photo of themselves in that message.
  For "option 2" pass that option's item ids. The page shows the picture, so don't describe it; just
  say it's an AI preview and that colors and fit are approximate. If the outfit belongs to someone
  else (for_whom wasn't "me") and no new photo was attached for them in this message, it's still the
  primary user's own saved photo in the preview, not that other person's — say so warmly in one
  short line (e.g. "That's you in the preview, not Alex, since this uses your own saved photo 😊
  Attach a photo of Alex if you'd like to see it on her instead.") rather than describing it as if
  it shows the other person.
- Use style_check when they ask if things go together.
- If the plan has active_alerts (e.g. a Wind Chill Advisory), mention them first and lean warmer.
- Call suggest_wardrobe_gaps when the user asks if their closet is ready for the weather, or when
  build_outfit's pick looks forced or thin (e.g. no real coat option, or notes about getting wet).
  It needs plan_day_warmth called first. Mention a gap plainly and suggest what kind of item would
  close it; don't invent a specific product, just the category (e.g. "a waterproof coat").
- Call plan_laundry when they ask about laundry timing or how many clean items they have left, not
  just when a single item hits its wear limit (that's already handled by update_wardrobe's note).
- Call wardrobe_stats when they ask what they actually wear, what's unused, or similar questions
  about their closet habits rather than what to wear today.

How to answer:
- Recommend the first option from build_outfit: it is ranked best and the page shows it as option 1.
  Name every item in it. Mention option 2 or 3 only if the user asks for alternatives, by number.
  The side panel stacks every day (and, when relevant, every person) you've built an outfit for in
  this conversation, each showing its own 3 options, so "option 2" is fine even across several days
  in one answer as long as build_outfit was called for each day.
- When the answer covers more than one day and/or more than one person, open with one short line
  naming what you checked before the outfits themselves, e.g. "I checked today and tomorrow's
  forecast for you and Alex." so it's clear up front everything was actually planned for, not
  guessed. Skip this line for the plain single-day, single-person case; it would just be noise there.
- Lead with the outfit in one line, then 2-4 short bullets: why it's warm enough, what to take off
  indoors, and any rain/wind warnings. Mention clo only briefly (e.g. "about 1.8 clo").
- For more than one person in the same answer, use one top-level bullet per person, their name in
  bold (e.g. "- **Alex:**") with their own 2-4 detail bullets indented two spaces underneath, so
  each person's details are visually grouped under their name instead of one long flat list mixing
  everyone together. For more than one day, a "### <day>" heading above each day's section is fine.
- One fixed rule for naming a day, in text and in worn_for alike: the literal word "today" for the
  current day, "tomorrow" for the next one, and the exact date (e.g. "Oct 9") for anything further
  out - never a phrase like "day after tomorrow". Use the same word/date for a given day everywhere
  in the answer and pass update_wardrobe's worn_for that identical string, so the closet's day tag
  always matches what you said in the text.
- Refer to clothes by name, not id. Use plain punctuation: commas and periods, no em dashes.
- If a tool returns an error, follow its instructions or tell the user plainly what to do."""

# --- The Harness ---

EMPTY_ANSWER = "Sorry, I didn't get an answer that time. Please send that again."


def run_agent(session: Session) -> tuple[str, list[dict]]:
    """Complete until the model answers without asking for a tool.

    Returns the final text and a record of every tool call made along the way.
    """
    messages = session.messages
    tool_calls = []
    nudge = []  # set after an empty answer; sent once, never stored in the session

    for _ in range(MAX_TOOL_ROUNDS):
        reply = litellm.completion(
            model=MODEL,
            vertex_location=VERTEX_LOCATION,
            timeout=MODEL_TIMEOUT,
            num_retries=MODEL_RETRIES,
            messages=messages + nudge,
            tools=TOOLS,
        ).choices[0].message

        if not reply.tool_calls:
            text = (reply.content or "").strip()
            if not text and not nudge:
                # The model sometimes answers with nothing. Don't store that turn (an empty
                # turn in the history makes every later answer empty too); ask once more.
                nudge = [{"role": "user", "content": "Answer my last message now, in plain text."}]
                continue
            text = text or EMPTY_ANSWER
            messages += [{"role": "assistant", "content": text}]
            return text, tool_calls

        # model_dump() keeps it a plain dict: the raw object carries provider-specific
        # fields that trip Pydantic when LiteLLM re-serializes it next round.
        messages += [reply.model_dump()]
        nudge = []

        # The harness, not the model, runs each tool and appends the result.
        for call in reply.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = run_tool(call.function.name, args, session)
            tool_calls += [{"name": call.function.name, "args": args, "result": result}]
            messages += [{"role": "tool", "tool_call_id": call.id, "content": result}]

    return "Sorry, I hit my tool-call limit before finishing.", tool_calls


# --- Session Store ---

# session_id -> Session. In-memory, single process.
sessions: dict[str, Session] = {}


def get_session(session_id: str | None) -> tuple[str, Session]:
    session_id = session_id or str(uuid.uuid4())
    if session_id not in sessions:
        sessions[session_id] = Session.new(system_prompt(), session_id)
    return session_id, sessions[session_id]


# --- FastAPI App ---

app = FastAPI()
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _index_html() -> str:
    """index.html with a content hash on each /static/ file, e.g. /static/app.js?v=3fa9c1d2.

    Browsers cache static files for a long time, so without this a returning visitor keeps
    running the old script after a deploy. A changed file gets a new URL; unchanged ones stay cached.
    """
    def versioned(match: re.Match) -> str:
        path = STATIC / match.group(1)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8] if path.is_file() else "0"
        return f"/static/{match.group(1)}?v={digest}"
    return re.sub(r"/static/([\w.-]+\.(?:js|css|svg|png|webmanifest))", versioned, (STATIC / "index.html").read_text())


INDEX_HTML = _index_html()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


class StatusRequest(BaseModel):
    session_id: str
    item_ids: list[str]
    status: str


class QtyRequest(BaseModel):
    session_id: str
    item_id: str
    qty: int


class UnlaundryRequest(BaseModel):
    session_id: str
    item_id: str


class ScanRequest(BaseModel):
    session_id: str
    photo_id: str
    label_photo_id: str | None = None


class ItemRequest(BaseModel):
    session_id: str
    item: dict


class PhotoRequest(BaseModel):
    session_id: str
    image_id: str | None = None


class StartRequest(BaseModel):
    session_id: str
    mode: str  # "own" (start empty) or "demo"


class SessionRequest(BaseModel):
    session_id: str


class ProfileRequest(BaseModel):
    session_id: str
    cold_sensitivity: str


@app.get("/")
def index():
    # no-cache: the browser may keep the page but must check with us before reusing it.
    return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    session_id, session = get_session(request.session_id)
    session.messages += [{"role": "user", "content": request.message}]

    try:
        response, tool_calls = run_agent(session)
    except Exception as e:
        # Auth, billing, a model that is not running: show it in the chat, not as a 500.
        first_line = (str(e).splitlines() or [""])[0][:300]
        response, tool_calls = f"Model call failed: {type(e).__name__}: {first_line}", []

    return ChatResponse(response=response, session_id=session_id, tool_calls=tool_calls)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "favicon.ico", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/conditions")
def conditions(location: str = "New York"):
    """Current weather for the page background. Failures just mean a calm sky."""
    try:
        return current_conditions(location)
    except Exception:
        raise HTTPException(503, "Weather unavailable.")


@app.post("/clear")
def clear(session_id: str | None = None):
    sessions.pop(session_id, None)
    return {"status": "ok"}


@functools.cache
def _photo_version(photo: str) -> str:
    """Content hash of a demo closet photo, so a replaced photo gets a new URL past browser caches."""
    path = STATIC / photo
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8] if path.is_file() else "0"


def item_view(session_id: str, item: dict) -> dict:
    """An item as the page needs it: slot, warmth, wear limit, and where its photo lives (if any)."""
    photo = (f"/image/{session_id}/{item['photo_id']}" if item.get("photo_id")
             else f"/static/{item['photo']}?v={_photo_version(item['photo'])}" if item.get("photo") else None)
    return {**item, "slot": slot(item), "clo": clo(item), "wear_limit": wear_limit(item), "photo_url": photo}


@app.get("/wardrobe")
def wardrobe(session_id: str | None = None):
    """The closet, profile and last plan, for the side panels of the page."""
    session_id, session = get_session(session_id)
    items = [item_view(session_id, item) for item in session.wardrobe.values()]
    return {
        "session_id": session_id,
        "items": items,
        "cold_sensitivity": session.cold_sensitivity,
        "last_plan": session.last_plan,
        "last_outfit": session.last_outfit,
        "person_photo_id": session.person_photo_id,
        "setup_done": session.setup_done,
    }


@app.post("/wardrobe/start")
def wardrobe_start(request: StartRequest):
    """Begin with an empty closet to build your own, or with the demo closet."""
    if request.mode not in ("own", "demo"):
        raise HTTPException(400, "mode must be 'own' or 'demo'.")
    _, session = get_session(request.session_id)
    session.wardrobe = {} if request.mode == "own" else demo_wardrobe()
    session.last_outfit = None
    session.setup_done = request.mode == "demo"
    return {"mode": request.mode, "items": len(session.wardrobe)}


@app.post("/wardrobe/finish")
def wardrobe_finish(request: SessionRequest):
    """Finish closet setup. Borrow demo basics for any essential the user hasn't added."""
    _, session = get_session(request.session_id)
    demo = demo_wardrobe()
    borrowed = []
    for need, slots in ESSENTIALS.items():
        if not any(slot(item) in slots for item in session.wardrobe.values()):
            item = {**demo[BORROW[need]], "borrowed": True}
            session.wardrobe[item["id"]] = item
            borrowed.append(item["name"])
    session.setup_done = True
    return {"borrowed": borrowed}


@app.get("/catalog")
def catalog():
    """Choices for the Add clothes form."""
    def label(garment_type):
        base, _, weight = garment_type.rpartition("_") if garment_type.endswith(("_thin", "_thick")) else (garment_type, "", "")
        text = base.replace("_", " ").capitalize()
        return f"{text} ({weight})" if weight else text
    return {
        "garments": [{"type": t, "label": label(t), "slot": row["slot"], "clo": float(row["clo"])} for t, row in GARMENTS.items()],
        "materials": list(MATERIALS),
        "fits": FITS, "patterns": PATTERNS, "rain": RAIN,
    }


@app.post("/wardrobe/scan")
def wardrobe_scan(request: ScanRequest):
    """Suggest item fields from a photo (Gemini vision). Saves nothing; the form confirms."""
    _, session = get_session(request.session_id)
    try:
        return analyze_garment(session, request.photo_id, request.label_photo_id)
    except (GarmentScanError, PhotoError) as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"Scanning is unavailable right now ({type(e).__name__}). Fill in the details by hand.")


@app.post("/wardrobe/item")
def wardrobe_add(request: ItemRequest):
    _, session = get_session(request.session_id)
    try:
        item = add_item(session, request.item)
    except (GarmentScanError, PhotoError) as e:
        raise HTTPException(422, str(e))
    return item_view(request.session_id, item)


@app.delete("/wardrobe/item")
def wardrobe_remove(session_id: str, item_id: str):
    _, session = get_session(session_id)
    item = session.wardrobe.get(item_id)
    if not item or not item.get("user_added"):
        raise HTTPException(404, "Only clothes you added can be removed.")
    del session.wardrobe[item_id]
    return {"removed": item_id}


@app.post("/me/photo")
def me_photo(request: PhotoRequest):
    """Save (or clear) the user's full-body photo for try-on."""
    _, session = get_session(request.session_id)
    if request.image_id and request.image_id not in session.images:
        raise HTTPException(404, "Upload the photo first.")
    session.person_photo_id = request.image_id
    return {"person_photo_id": session.person_photo_id}


@app.post("/wardrobe/status")
def wardrobe_status(request: StatusRequest):
    """Laundry toggle from the closet panel; same code path as the update_wardrobe tool."""
    _, session = get_session(request.session_id)
    result = json.loads(run_tool("update_wardrobe", {"item_ids": request.item_ids, "status": request.status}, session))
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/wardrobe/qty")
def wardrobe_qty(request: QtyRequest):
    """UI-only: how many of this item the user owns. Lowering it below the current dirty
    count clamps the dirty count down to match (you can't own fewer than are in the wash)."""
    _, session = get_session(request.session_id)
    item = session.wardrobe.get(request.item_id)
    if not item:
        raise HTTPException(404, "Unknown item id.")
    item["qty"] = max(1, int(request.qty))
    item["qty_in_laundry"] = min(item.get("qty_in_laundry", 0), item["qty"])
    sync_laundry_status(item)
    return {"id": item["id"], "qty": item["qty"], "qty_in_laundry": item["qty_in_laundry"], "status": item["status"]}


@app.post("/wardrobe/unlaundry")
def wardrobe_unlaundry(request: UnlaundryRequest):
    """UI-only: undo one accidental "send to laundry" tap. Decrements qty_in_laundry by 1
    (floor 0); unlike update_wardrobe's "clean", this never touches wears, since undoing a
    laundry-send isn't the same as declaring the item freshly washed."""
    _, session = get_session(request.session_id)
    item = session.wardrobe.get(request.item_id)
    if not item:
        raise HTTPException(404, "Unknown item id.")
    item["qty_in_laundry"] = max(0, item.get("qty_in_laundry", 0) - 1)
    sync_laundry_status(item)
    return {"id": item["id"], "qty": item["qty"], "qty_in_laundry": item["qty_in_laundry"], "status": item["status"]}


@app.post("/profile")
def profile(request: ProfileRequest):
    _, session = get_session(request.session_id)
    result = json.loads(run_tool("set_cold_sensitivity", {"level": request.cold_sensitivity}, session))
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/upload")
async def upload(session_id: str = Form(...), file: UploadFile = File(...)):
    """Store a photo in the session and return an id the model can pass to tools."""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "Only image files can be uploaded.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Image is larger than 8 MB.")
    try:
        open_image(data)
    except PhotoError as e:
        raise HTTPException(400, str(e))
    session_id, session = get_session(session_id)
    image_id = f"img_{secrets.token_hex(3)}"
    session.images[image_id] = (data, file.content_type)
    return {"session_id": session_id, "image_id": image_id, "url": f"/image/{session_id}/{image_id}"}


@app.get("/image/{session_id}/{image_id}")
def image(session_id: str, image_id: str):
    session = sessions.get(session_id)
    if not session or image_id not in session.images:
        raise HTTPException(404, "Image not found.")
    data, mime = session.images[image_id]
    return Response(content=data, media_type=mime)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
