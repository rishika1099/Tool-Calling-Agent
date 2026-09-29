"""Show the user wearing an outfit (bonus feature).

Owner: style (see PROPOSAL.md and the GitHub issue "try_on_outfit").

STATUS: stub.

What to build:
- try_on_outfit(session, person_photo_id, item_ids=None)
  Uses the person photo from session.images and garment photos
  (item["photo_id"], set by scan_garment). Defaults to session.last_outfit.
  Options on Vertex AI, same GCP project as the chat model:
  * Virtual Try-On model: one person image + one garment image per call; apply
    top, then bottom, then outer layer in sequence.
  * Gemini image model: person + several garments in one prompt.
  Check current model ids in the Vertex docs before starting.
  Store the result in session.images under a new id and return
  {"image_url": "/image/<session_id>/<id>"}; never put image bytes in the
  tool result. Handle safety-filter refusals with an actionable error
  ("try a front-facing, full-body photo on a plain background").
  Warmth answers must never depend on this tool.
"""

import json


def try_on_outfit(session, person_photo_id: str | None = None, item_ids: list[str] | None = None) -> str:
    person_photo_id = person_photo_id or session.person_photo_id
    if not person_photo_id:
        return json.dumps({"error": "No photo of the user yet. Ask them to add one in the 'Your photo' slot."})
    if person_photo_id not in session.images:
        return json.dumps({"error": f"No uploaded photo with id '{person_photo_id}'. Ask the user for a full-body photo."})
    return json.dumps({"error": "try_on_outfit is not built yet. Tell the user the try-on preview is coming soon."})


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "try_on_outfit",
            "description": (
                "Generate an image of the user wearing an outfit, from their uploaded full-body photo. "
                "Only call when the user asks to see how it looks. Defaults to the last outfit from build_outfit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "person_photo_id": {"type": "string", "description": "Id of the user's full-body photo. Defaults to the one saved in 'Your photo'."},
                    "item_ids": {"type": "array", "items": {"type": "string"}, "description": "Items to show. Optional."},
                },
                "required": [],
            },
        },
    },
]

TOOL_MAP = {"try_on_outfit": try_on_outfit}
