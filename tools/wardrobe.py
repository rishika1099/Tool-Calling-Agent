"""Add clothes to the closet from photos of the garment and its care label.

Owner: wardrobe (see PROPOSAL.md and the GitHub issue "scan_garment").

STATUS: stub.

What to build:
- scan_garment(session, photo_id, label_photo_id=None, name=None)
  1. Read the image bytes from session.images[photo_id] (uploaded via POST /upload).
  2. Ask Gemini vision (litellm.completion with an image_url data URI, same model
     as app.py) to return JSON: garment_type (must be a key of data/garments.csv,
     so pass the allowed list), fit, pattern, formality, a short name.
  3. If there is a care-label photo, read the fiber mix, e.g. {"wool": 70, "nylon": 30}.
     Materials must be keys of data/materials.csv; map others to the closest one.
     Without a label, guess the material and say so in the result.
  4. Measure the main color with Pillow (resize small, take the most common
     non-background color) and store it as hex in item["color"].
  5. Save the item into session.wardrobe with status "clean" and wears 0,
     and return it with its clo value so the model can explain it.
  Return JSON errors the model can act on, e.g. unknown photo id, unreadable
  label ("ask the user for a sharper, closer photo of the label").
- Laundry tracking (issue "laundry"): wear limits per garment type (jeans ~4,
  tees 1, coats many) so items move to in_laundry automatically.
"""

import json


def scan_garment(session, photo_id: str, label_photo_id: str | None = None, name: str | None = None) -> str:
    if photo_id not in session.images:
        return json.dumps({"error": f"No uploaded photo with id '{photo_id}'. Ask the user to attach the photo again."})
    return json.dumps({"error": "scan_garment is not built yet. Tell the user photo scanning is coming soon; "
                                "they can use the demo closet meanwhile."})


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scan_garment",
            "description": (
                "Add a clothing item to the user's closet from an uploaded photo, and optionally a photo of its "
                "care label to read the exact fiber mix. Use when the user attaches clothing photos. "
                "Photo ids look like 'img_ab12cd' and appear in the user's message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "photo_id": {"type": "string", "description": "Id of the photo of the garment."},
                    "label_photo_id": {"type": "string", "description": "Id of the photo of its care label, if the user sent one."},
                    "name": {"type": "string", "description": "What the user calls it, e.g. 'my green sweater'. Optional."},
                },
                "required": ["photo_id"],
            },
        },
    },
]

TOOL_MAP = {"scan_garment": scan_garment}
