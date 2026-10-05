"""Offline checks for try_on_outfit. The image model is replaced by a stub."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app as app_module
from app import get_session
from tools import run_tool, tryon


def jpeg(color=(200, 200, 200), size=(300, 500)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def fake_model(monkeypatch):
    sent = {}

    def generate(parts):
        sent["parts"] = parts
        return jpeg((90, 20, 20))

    monkeypatch.setattr(tryon, "_generate", generate)
    return sent


def session_with_person():
    sid, session = get_session(None)
    session.images["img_me"] = (jpeg(), "image/jpeg")
    session.person_photo_id = "img_me"
    return sid, session


def test_needs_a_photo_and_an_outfit(fake_model):
    _, session = get_session(None)
    assert "Your photo" in json.loads(run_tool("try_on_outfit", {}, session))["error"]
    _, session = session_with_person()
    assert "build_outfit" in json.loads(run_tool("try_on_outfit", {}, session))["error"]
    assert "Unknown item ids" in json.loads(run_tool("try_on_outfit", {"item_ids": ["nope"]}, session))["error"]


def test_preview_is_stored_and_served_not_inlined(fake_model):
    sid, session = session_with_person()
    session.images["img_sweater"] = (jpeg((120, 30, 30)), "image/jpeg")
    session.wardrobe["my-sweater"] = {"id": "my-sweater", "name": "Maroon sweater", "garment_type": "sweater_thick",
                                      "photo_id": "img_sweater", "status": "clean", "wears": 0}
    raw = run_tool("try_on_outfit", {"item_ids": ["jeans-indigo", "my-sweater", "parka-black"]}, session)
    result = json.loads(raw)
    assert result["image_url"].startswith(f"/image/{sid}/tryon_")
    assert result["from_photos"] == ["Black down parka", "Maroon sweater", "Indigo jeans"]  # uploads and demo closet photos
    assert len(raw) < 800  # a link, never image bytes

    parts = fake_model["parts"]
    assert sum(isinstance(p, bytes) for p in parts) == 4  # the person and three garment photos
    prompt = parts[-1]
    assert prompt.index("Black down parka") < prompt.index("Maroon sweater") < prompt.index("Indigo jeans")  # outermost first

    served = TestClient(app_module.app).get(result["image_url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"


def test_defaults_to_the_last_outfit_and_keeps_few_previews(fake_model):
    _, session = session_with_person()
    session.last_outfit = ["tee-white", "jeans-indigo"]
    for _ in range(tryon.KEEP_PREVIEWS + 3):
        assert "image_url" in json.loads(run_tool("try_on_outfit", {}, session))
    assert len(session.previews) == tryon.KEEP_PREVIEWS
    assert sum(k.startswith("tryon_") for k in session.images) == tryon.KEEP_PREVIEWS


def test_model_refusal_and_outage_are_explained(monkeypatch):
    _, session = session_with_person()
    session.last_outfit = ["tee-white", "jeans-indigo"]

    def declined(parts):
        raise tryon.TryOnError("The image model did not return a picture for that photo. Ask the user for a front-facing photo.")
    monkeypatch.setattr(tryon, "_generate", declined)
    assert "front-facing" in json.loads(run_tool("try_on_outfit", {}, session))["error"]

    def down(parts):
        raise RuntimeError("503")
    monkeypatch.setattr(tryon, "_generate", down)
    assert "outfit advice still stands" in json.loads(run_tool("try_on_outfit", {}, session))["error"]
