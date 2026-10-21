"""Visual evidence must gate actions and completion, without changing text defaults."""
import json

import pytest

from jev_browser import loop, jev
from jev_browser.camofox import fingerprint
from jev_browser.vision import VisionSettings, VisionUnavailable, VisionRun
from helpers import FakePage, decision
from test_vision import frame
from test_jev import answer, Response


class VisualPage(FakePage):
    def __init__(self, frames):
        self.frames = frames
        self.captures = 0
        super().__init__([frames[0].state])

    def observe_vision(self, url, run):
        run.capture()
        self.captures += 1
        return self.frames[min(self.captures - 1, len(self.frames) - 1)]


def run(page, **options):
    return loop.run_task(page, "Choose the red circle", vision_settings=VisionSettings(enabled=True), **options)


def test_required_visual_action_and_completion_are_checked(monkeypatch):
    f = frame()
    page = VisualPage([f])
    decisions = iter([decision("e1", "CLICK", target_confidence=.99), decision("DONE")])
    monkeypatch.setattr(loop, "choose", lambda *a, **k: next(decisions))
    monkeypatch.setattr(loop, "verify_visual", lambda *a: True)
    out = run(page, require_visual=True)
    assert out["status"] == "done" and out["vision"]["verified"]
    assert page.acted == [("e1", None)] and page.captures == 5
    assert "data:image" not in json.dumps(out)


@pytest.mark.parametrize("verified", [True, False])
def test_done_requires_visual_completion_and_freshness(monkeypatch, verified):
    page = VisualPage([frame()])
    monkeypatch.setattr(loop, "choose", lambda *a, **k: decision("DONE"))
    monkeypatch.setattr(loop, "verify_visual", lambda *a: verified)
    out = run(page, require_visual=True)
    assert out["status"] == ("done" if verified else "paused")
    assert out["vision"]["verified"] is verified
    if not verified:
        assert out["reason"] == "vision_completion_unverified"


def test_auto_escalates_once_on_low_confidence(monkeypatch):
    page = VisualPage([frame()])
    calls = []
    def choose(*a, **k):
        calls.append(bool(k.get("frame")))
        return decision("DONE", confidence=.2 if not k else .99)
    monkeypatch.setattr(loop, "choose", choose)
    monkeypatch.setattr(loop, "verify_visual", lambda *a: True)
    out = run(page)
    assert out["status"] == "done" and calls == [False, True]
    assert out["vision"]["escalations"] == 1


def test_missing_capture_never_uses_dom_fallback(monkeypatch):
    page = FakePage([frame().state])
    monkeypatch.setattr(loop, "choose", lambda *a, **k: pytest.fail("No model call without capture"))
    out = run(page, require_visual=True)
    assert out["status"] == "paused" and out["reason"] == "vision_capture_unavailable"
    assert not page.acted


def test_changed_target_pixels_prevent_action(monkeypatch):
    page = VisualPage([frame(), frame(color="blue")])
    monkeypatch.setattr(loop, "choose", lambda *a, **k: decision("e1", "CLICK", target_confidence=.99))
    # Force changing pixels at every pre-action check, exercising bounded stale retries.
    red, blue = frame(), frame(color="blue")
    def capture(url, run):
        run.capture()
        page.captures += 1
        return red if page.captures % 2 else blue
    page.observe_vision = capture
    out = run(page, require_visual=True)
    assert out["status"] in {"error", "paused"} and not page.acted


def test_visual_target_low_confidence_and_sensitive_action_pause(monkeypatch):
    f = frame()
    page = VisualPage([f])
    monkeypatch.setattr(loop, "choose", lambda *a, **k: decision("e1", "CLICK", target_confidence=.4))
    assert run(page, require_visual=True)["reason"] == "low_confidence"
    f.state["actions"][0]["label"] = "Pay now"
    f.state["fingerprint"] = fingerprint(f.state)
    monkeypatch.setattr(loop, "choose", lambda *a, **k: decision("e1", "CLICK", target_confidence=.99))
    assert run(page, require_visual=True)["status"] == "paused"
    assert not page.acted


def test_visual_model_receives_safe_metadata_and_pixels(monkeypatch):
    f = frame()
    f.state["text"] = "private raw value"
    f.safe = {**f.safe, "text": "Masked page"}
    run_state = VisionRun(VisionSettings(enabled=True, box=True))
    def post(url, body, **kwargs):
        assert body["model"] == "typesafe/jev-1.14"
        assert "private raw value" not in json.dumps(body)
        assert body["state"][1]["type"] == "image_url"
        ops = body["questions"]["operation"]["criteria"]
        targets = body["questions"]["click_target"]["criteria"]
        assert body["state"][0]["elements"][0]["image_rectangle"]["x"] == 10
        return {"model": "typesafe/jev-1.14-20261014", "answers": {
            "operation": answer("CLICK", ops, .99), "click_target": answer("1", targets, .99),
            "target_present": {"noul": .99}, "target_box": {
                "box": {"top": .03, "bottom": .1, "left": .03, "right": .1}, "confidence": .99}}}
    monkeypatch.setattr(jev, "post_json", post)
    out = jev.choose(f.state, "red", [], frame=f, vision_run=run_state)
    assert out["choice"] == "e1" and run_state.models == ["typesafe/jev-1.14-20261014"]


def test_every_image_retry_consumes_image_budget(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "test-key")
    monkeypatch.setattr(jev._HTTP, "post", lambda *a, **k: Response(503))
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    from jev_browser.budget import BudgetExceeded
    f = frame()
    run_state = VisionRun(VisionSettings(enabled=True, max_calls=1))
    with pytest.raises(BudgetExceeded, match="vision_budget"):
        jev.post_json(jev.DECISIONS_URL, {}, frame=f, vision_run=run_state)
    assert run_state.calls == 1
    f.received -= 31
    with pytest.raises(VisionUnavailable, match="expired"):
        jev.post_json(jev.DECISIONS_URL, {}, frame=f, vision_run=run_state)


@pytest.mark.parametrize("value,expected", [(1, True), (.94, False), (float("nan"), None), ("1", None)])
def test_verification_validates_noul(monkeypatch, value, expected):
    monkeypatch.setattr(jev, "post_json", lambda *a, **k: {"answers": {"satisfied": {"noul": value}}})
    f = frame()
    state = VisionRun(VisionSettings(enabled=True))
    if expected is None:
        with pytest.raises(jev.ModelError):
            jev.verify_visual(f, "red", state)
    else:
        assert jev.verify_visual(f, "red", state) is expected


def test_visual_pause_never_returns_raw_control_values(monkeypatch):
    f = frame()
    f.state['actions'] = [{**a, 'value': 'private-value'} for a in f.state['actions']]
    f.state['text'] = 'private raw text'
    f.safe = {**f.safe, 'text': 'Safe text'}
    monkeypatch.setattr(loop, 'choose', lambda *a, **k: decision('BLOCKED'))
    out = run(VisualPage([f]), require_visual=True)
    assert out['status'] == 'paused' and 'private' not in json.dumps(out)
    assert out['text'] == 'Safe text'


def test_completion_changed_during_verification_is_never_done(monkeypatch):
    page = VisualPage([frame()])
    red, blue = frame(), frame(color='blue')
    def capture(url, run):
        run.capture()
        page.captures += 1
        return blue if page.captures % 3 == 0 else red
    page.observe_vision = capture
    monkeypatch.setattr(loop, 'choose', lambda *a, **k: decision('DONE'))
    monkeypatch.setattr(loop, 'verify_visual', lambda *a: True)
    out = run(page, require_visual=True)
    assert out['status'] != 'done' and not out['vision']['verified']


def test_verification_receives_executed_history_and_records_probability(monkeypatch):
    seen = []
    monkeypatch.setattr(jev, 'post_json', lambda url, body, **kw: seen.append(body) or {
        'answers': {'satisfied': {'noul': .99}}})
    visual = VisionRun(VisionSettings(enabled=True))
    history = [{'action': 'Choose', 'kind': 'click', 'text': None, 'page_changed': True}]
    assert jev.verify_visual(frame(), 'Choose red', visual, history)
    assert seen[0]['state'][0]['executed_actions'] == history
    assert visual.summary()['completion_probability'] == .99
