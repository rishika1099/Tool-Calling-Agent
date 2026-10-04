import json
import secrets
import uuid
from pathlib import Path

import litellm
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from session import BORROW, ESSENTIALS, Session, demo_wardrobe
from settings import MODEL, MODEL_RETRIES, MODEL_TIMEOUT, VERTEX_LOCATION
from tools import TOOLS, run_tool
from tools.catalog import GARMENTS, MATERIALS, clo, slot, wear_limit
from tools.photos import PhotoError, open_image
from tools.wardrobe import FITS, PATTERNS, RAIN, GarmentScanError, add_item, analyze_garment
from tools.forecast import current_conditions

# --- Config ---

MAX_TOOL_ROUNDS = 8
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

SYSTEM_PROMPT = """You are Layer Lab, a getting-dressed assistant for students facing cold NYC weather.
You decide what to wear from the user's own closet, based on the forecast for the hours they are
actually outside, whether they will be indoors or outdoors, and how quickly they feel cold.

How to work:
- For any "what should I wear" question: call plan_day_warmth with the user's day broken into
  segments (outdoors / indoors / transit, and sitting / standing / walking / biking),
  then call build_outfit. Never guess warmth numbers yourself.
- If the user doesn't give times, assume a typical class day and say what you assumed.
  Default location is New York and default day is today.
- If the user says they run cold or warm, call set_cold_sensitivity, then re-plan.
- If they report how a past outfit felt ("I was freezing yesterday"), call record_comfort_feedback.
- If they say an item is in the wash, call update_wardrobe with 'in_laundry'. Once they confirm they're
  wearing an outfit, call update_wardrobe with 'worn' for those items; items that hit their wear limit
  go to the laundry automatically, so mention that if the tool result's 'note' says so.
- Photo ids like img_ab12cd in a message are uploaded photos. Clothing photos go to scan_garment,
  a full-body photo of the user is for try_on_outfit (only when they ask to see it).
- Use style_check when they ask if things go together.
- If the plan has active_alerts (e.g. a Wind Chill Advisory), mention them first and lean warmer.

How to answer:
- Recommend the first option from build_outfit: it is ranked best and the page shows it as option 1.
  Name every item in it. Mention option 2 or 3 only if the user asks for alternatives, by number.
- Lead with the outfit in one line, then 2-4 short bullets: why it's warm enough, what to take off
  indoors, and any rain/wind warnings. Mention clo only briefly (e.g. "about 1.8 clo").
- Refer to clothes by name, not id. Use plain punctuation: commas and periods, no em dashes.
- If a tool returns an error, follow its instructions or tell the user plainly what to do."""

# --- The Harness ---


def run_agent(session: Session) -> tuple[str, list[dict]]:
    """Complete until the model answers without asking for a tool.

    Returns the final text and a record of every tool call made along the way.
    """
    messages = session.messages
    tool_calls = []

    for _ in range(MAX_TOOL_ROUNDS):
        reply = litellm.completion(
            model=MODEL,
            vertex_location=VERTEX_LOCATION,
            timeout=MODEL_TIMEOUT,
            num_retries=MODEL_RETRIES,
            messages=messages,
            tools=TOOLS,
        ).choices[0].message

        # model_dump() keeps it a plain dict: the raw object carries provider-specific
        # fields that trip Pydantic when LiteLLM re-serializes it next round.
        messages += [reply.model_dump()]

        if not reply.tool_calls:
            return reply.content, tool_calls

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
        sessions[session_id] = Session.new(SYSTEM_PROMPT)
    return session_id, sessions[session_id]


# --- FastAPI App ---

app = FastAPI()
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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
    return FileResponse(STATIC / "index.html")


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


@app.get("/wardrobe")
def wardrobe(session_id: str | None = None):
    """The closet, profile and last plan, for the side panels of the page."""
    session_id, session = get_session(session_id)
    items = [{**item, "slot": slot(item), "clo": clo(item), "wear_limit": wear_limit(item)} for item in session.wardrobe.values()]
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
    return {**item, "slot": slot(item), "clo": clo(item), "wear_limit": wear_limit(item)}


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
