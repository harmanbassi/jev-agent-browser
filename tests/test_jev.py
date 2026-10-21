import json

import pytest
import requests

from jev_browser import jev

from helpers import make_state


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def answer(choice, ids, confidence=0.8):
    probabilities = {i: 0.0 for i in ids}
    probabilities[choice] = 1.0
    return {"choice": choice, "probabilities": probabilities, "confidence": confidence}


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def test_api_key_prefers_the_jev_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "general")
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "jev")
    assert jev.api_key() == "jev"
    monkeypatch.delenv("JEV_OPENROUTER_KEY")
    assert jev.api_key() == "general"


def test_post_json_without_a_key_refuses(monkeypatch):
    monkeypatch.delenv("JEV_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(jev.ModelError, match="No OpenRouter key"):
        jev.post_json("https://x.test", {})


def test_post_json_retries_rate_limits_then_returns(monkeypatch, key):
    replies = iter([Response(429), Response(200, {"ok": 1})])
    sent = []

    def post(url, json, headers, timeout):
        sent.append(headers["Authorization"])
        return next(replies)

    monkeypatch.setattr(jev._HTTP, "post", post)
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    assert jev.post_json("https://x.test", {}) == {"ok": 1}
    assert sent == ["Bearer test-key"] * 2


def test_post_json_gives_up_after_three_rate_limits(monkeypatch, key):
    monkeypatch.setattr(jev._HTTP, "post", lambda *a, **k: Response(503))
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    with pytest.raises(jev.ModelError, match="HTTP 503"):
        jev.post_json("https://x.test", {})


def test_post_json_maps_a_non_json_reply(monkeypatch, key):
    class Bad(Response):
        def json(self):
            raise ValueError("Expecting value")

    monkeypatch.setattr(jev._HTTP, "post", lambda *a, **k: Bad(200))
    with pytest.raises(jev.ModelError, match="non-JSON"):
        jev.post_json("https://x.test", {})


def test_post_json_maps_connection_errors(monkeypatch, key):
    def post(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(jev._HTTP, "post", post)
    with pytest.raises(jev.ModelError, match="connection failed"):
        jev.post_json("https://x.test", {})


def test_choose_offers_need_guidance_and_resolves_the_target(monkeypatch, key):
    sent = {}

    def post_json(url, body):
        sent.update(url=url, body=body)
        ops = list(body["questions"]["operation"]["criteria"])
        targets = list(body["questions"]["click_target"]["criteria"])
        return {"answers": {"operation": answer("CLICK", ops, 0.9), "click_target": answer("2", targets, 0.6)}}

    monkeypatch.setattr(jev, "post_json", post_json)
    d = jev.choose(make_state(), "press go", [])

    assert d["choice"] == "e2" and d["operation"] == "CLICK"
    assert (d["confidence"], d["target_confidence"]) == (0.9, 0.6)
    assert sent["url"] == jev.DECISIONS_URL
    assert sent["body"]["model"] == "~typesafe/jev-latest"
    assert {"DONE", "BLOCKED", "NEED_GUIDANCE", "WAIT"} <= set(sent["body"]["questions"]["operation"]["criteria"])


def test_choose_returns_stop_choices_directly(monkeypatch, key):
    def post_json(url, body):
        ops = list(body["questions"]["operation"]["criteria"])
        return {"answers": {"operation": answer("NEED_GUIDANCE", ops, 0.7)}}

    monkeypatch.setattr(jev, "post_json", post_json)
    assert jev.choose(make_state(), "goal", [])["choice"] == "NEED_GUIDANCE"


def test_choose_maps_controls_to_their_action_ids(monkeypatch, key):
    def post_json(url, body):
        ops = list(body["questions"]["operation"]["criteria"])
        return {"answers": {"operation": answer("WAIT", ops)}}

    monkeypatch.setattr(jev, "post_json", post_json)
    assert jev.choose(make_state(), "goal", [])["choice"] == "wait"


@pytest.mark.parametrize("reply", [{}, {"answers": None}, {"answers": {"operation": {"choice": "NOPE"}}}])
def test_choose_rejects_malformed_answers(monkeypatch, key, reply):
    monkeypatch.setattr(jev, "post_json", lambda url, body: reply)
    with pytest.raises(jev.ModelError):
        jev.choose(make_state(), "goal", [])


def test_select_options_get_their_own_target_indices():
    actions = [
        {"id": "e1", "kind": "select", "node": 5, "label": "Class → Economy", "value": "eco", "current_value": ""},
        {"id": "e2", "kind": "select", "node": 5, "label": "Class → Business", "value": "bus", "current_value": ""},
    ]
    elements, targets, _ = jev.action_space(actions)
    assert list(targets["SELECT"]) == ["1:1", "1:2"]
    assert [o["value"] for o in elements[0]["options"]] == ["eco", "bus"]


def chat(content):
    return {"choices": [{"message": {"content": content}}]}


def test_field_text_returns_the_value(monkeypatch, key):
    monkeypatch.setattr(jev, "post_json", lambda url, body: chat(json.dumps({"text": "London"})))
    assert jev.field_text({"goal": "g"}) == "London"


def test_field_text_null_means_the_goal_lacks_the_value(monkeypatch, key):
    monkeypatch.setattr(jev, "post_json", lambda url, body: chat(json.dumps({"text": None})))
    assert jev.field_text({"goal": "g"}) is None


def test_field_text_retries_malformed_output_once(monkeypatch, key):
    replies = iter([chat("not json"), chat(json.dumps({"text": "ok"}))])
    monkeypatch.setattr(jev, "post_json", lambda url, body: next(replies))
    assert jev.field_text({"goal": "g"}) == "ok"


def test_field_text_raises_after_two_malformed_answers(monkeypatch, key):
    monkeypatch.setattr(jev, "post_json", lambda url, body: chat(json.dumps({"text": ""})))
    with pytest.raises(jev.ModelError, match="no valid field value"):
        jev.field_text({"goal": "g"})


def test_field_context_caps_page_text():
    ctx = jev.field_context("g", {"label": "L"}, make_state(text="x" * 9000), [])
    assert len(ctx["page"]["text"]) == 6000
