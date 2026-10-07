"""The /chat endpoint always answers with JSON text, even when the model returns nothing."""

import re
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module


def model_says(monkeypatch, *contents):
    """Make the model answer with each of these in turn (no tool calls); record what it was sent."""
    sent, replies = [], list(contents)

    def completion(**kwargs):
        sent.append(kwargs["messages"])
        message = SimpleNamespace(content=replies.pop(0), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(app_module.litellm, "completion", completion)
    return sent


def test_empty_answer_is_asked_again_and_not_remembered(monkeypatch):
    sent = model_says(monkeypatch, None, "Wear the parka.")
    data = TestClient(app_module.app).post("/chat", json={"message": "What should I wear?"}).json()
    assert data["response"] == "Wear the parka."
    assert len(sent) == 2
    history = app_module.sessions[data["session_id"]].messages
    assert [m["role"] for m in history] == ["system", "user", "assistant"]
    assert history[-1]["content"] == "Wear the parka."


def test_two_empty_answers_still_give_a_json_reply(monkeypatch):
    model_says(monkeypatch, None, "  ")
    res = TestClient(app_module.app).post("/chat", json={"message": "hello"})
    assert res.status_code == 200
    assert res.json()["response"] == app_module.EMPTY_ANSWER
    assert set(res.json()) == {"response", "session_id", "tool_calls"}


def test_system_prompt_tells_the_model_todays_real_date():
    # Without this, the model can only learn "today" by reading a prior plan_day_warmth result,
    # and has no way at all to resolve "day after tomorrow" before ever calling a tool.
    today = datetime.now(app_module.NY_TZ)
    prompt = app_module.system_prompt()
    assert today.strftime("%A, %Y-%m-%d") in prompt
    assert re.search(r"exact YYYY-MM-DD", prompt)

    _, session = app_module.get_session(None)
    assert session.messages[0]["role"] == "system"
    assert today.strftime("%Y-%m-%d") in session.messages[0]["content"]
