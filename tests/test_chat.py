"""The /chat endpoint always answers with JSON text, even when the model returns nothing."""

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
