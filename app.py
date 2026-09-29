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

from session import Session
from tools import TOOLS, run_tool
from tools.catalog import clo, slot

# --- Config ---

MODEL = "vertex_ai/gemini-3.5-flash-lite"
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
- If they say an item is in the wash, call update_wardrobe with 'in_laundry'.
- Photo ids like img_ab12cd in a message are uploaded photos. Clothing photos go to scan_garment,
  a full-body photo of the user is for try_on_outfit (only when they ask to see it).
- Use style_check when they ask if things go together.
- If the plan has active_alerts (e.g. a Wind Chill Advisory), mention them first and lean warmer.

How to answer:
- Lead with the outfit in one line, then 2-4 short bullets: why it's warm enough, what to take off
  indoors, and any rain/wind warnings. Mention clo only briefly (e.g. "about 1.8 clo").
- Refer to clothes by name, not id.
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
            vertex_location="global",
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


@app.post("/clear")
def clear(session_id: str | None = None):
    sessions.pop(session_id, None)
    return {"status": "ok"}


@app.get("/wardrobe")
def wardrobe(session_id: str | None = None):
    """The closet, profile and last plan, for the side panels of the page."""
    session_id, session = get_session(session_id)
    items = [{**item, "slot": slot(item), "clo": clo(item)} for item in session.wardrobe.values()]
    return {
        "session_id": session_id,
        "items": items,
        "cold_sensitivity": session.cold_sensitivity,
        "last_plan": session.last_plan,
        "last_outfit": session.last_outfit,
    }


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
