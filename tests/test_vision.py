import base64
from dataclasses import replace
import io
import json
import math
import sys
import time
import types
import uuid

import pytest
from PIL import Image

from jev_browser import environment, vision
from jev_browser.budget import Budget, BudgetExceeded, current
from helpers import make_state
from test_camofox import stub


def wire(size=(1120, 780), color="red"):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    state = make_state(actions=[{"id": "e1", "kind": "click", "node": 1, "label": "Choose", "role": "button",
                                 "rect": {"x": 10, "y": 10, "w": 200, "h": 200}}])
    state.update(w=size[0], h=size[1])
    return {"protocol": 1, "snapshotHash": "hash", "masked": True, "captureId": str(uuid.uuid4()),
            "snapshot": state, "safe": {k: state[k] for k in ("url", "title", "text", "actions")},
            "image": {"format": "png", "data": base64.b64encode(stream.getvalue()).decode()}}


def frame(size=(1120, 780), color="red"):
    return vision.Frame.decode(wire(size, color), "hash")


def test_vision_permission_is_distinct_from_task_mode_and_requirement(monkeypatch):
    default = vision.VisionSettings.from_env()
    assert not default.enabled and default.resolve() == "off"
    for mode, required in [("always", False), ("auto", True)]:
        with pytest.raises(vision.VisionUnavailable, match="vision_disabled"):
            default.resolve(mode, required)
    enabled = vision.VisionSettings(enabled=True)
    assert enabled.resolve() == "auto" and enabled.resolve("always", True) == "always"
    assert enabled.resolve("off") == "off"
    with pytest.raises(ValueError):
        enabled.resolve("bad")
    with pytest.raises(ValueError):
        enabled.resolve(require=1)
    with pytest.raises(vision.VisionUnavailable):
        replace(enabled, mode="off").resolve(require=True)
    with pytest.raises(vision.VisionUnavailable):
        replace(enabled, mode="off").resolve("always")


@pytest.mark.parametrize("kwargs", [{"enabled": 1}, {"mode": "bad"}, {"mode": []}, {"max_calls": 0}, {"max_calls": True},
                                   {"max_calls": 33}, {"model": "unknown"}, {"box": "yes"}])
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        vision.VisionSettings(**kwargs)


def test_profile_settings_do_not_inherit_global_permission(monkeypatch):
    monkeypatch.setenv("JEV_VISION_ENABLED", "1")
    with environment.use({}.get):
        assert vision.VisionSettings.from_env().resolve() == "off"
    values = {"JEV_VISION_ENABLED": "1", "JEV_VISION_MODE": "always", "JEV_VISION_MAX_CALLS": "8", "JEV_VISION_BOX": "1"}
    with environment.use(values.get):
        settings = vision.VisionSettings.from_env()
        assert settings.enabled and settings.box and settings.max_calls == 8
        values["JEV_VISION_MAX_CALLS"] = "invalid-private-detail"
        with pytest.raises(ValueError) as caught:
            vision.VisionSettings.from_env()
        assert "invalid-private-detail" not in str(caught.value)


def test_optional_dependency_failure_is_actionable(monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(vision.VisionUnavailable, match="vision extra"):
        vision.dependencies()


@pytest.mark.parametrize("size, expected", [((1120, 780), (1120, 780)), ((200, 100), (280, 280)),
                                          ((2000, 1000), (1568, 784)), ((2001, 1001), (1568, 784))])
def test_images_fit_limits_and_coordinates_round_trip(size, expected):
    f = frame(size)
    assert f.size == expected
    assert "pixels" not in repr(f) and "data:image" not in repr(f)
    part = f.image_part()
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
    rect = f.rect(f.safe["actions"][0])
    assert rect["x"] == 10 * f.scale + f.offset[0]


@pytest.mark.parametrize("change", [
    lambda w: w.update(protocol=2), lambda w: w.update(masked=False), lambda w: w.update(snapshotHash="wrong"),
    lambda w: w.update(captureId="private-invalid-id"), lambda w: w["safe"].update(url="https://other.test"),
    lambda w: w["safe"].update(text=[]), lambda w: w["safe"].update(actions=[{"id": "invented"}]),
    lambda w: w["image"].update(format="jpeg"), lambda w: w["image"].update(data="not-base64"),
    lambda w: w["snapshot"].update(w=100), lambda w: w["image"].update(data="A" * (12 * 1024 * 1024)),
])
def test_invalid_frames_fail_without_echoing_payload(change):
    value = wire()
    change(value)
    with pytest.raises(vision.VisionUnavailable, match="vision_invalid_observation"):
        vision.Frame.decode(value, "hash")


def test_freshness_uses_pixels_dimensions_and_age():
    f, same, changed = frame(), frame(), frame(color="blue")
    action = f.safe["actions"][0]
    assert f.unchanged(same) and f.unchanged(same, action)
    assert not f.unchanged(changed) and not f.unchanged(changed, action)
    assert not f.unchanged(frame((500, 500)))
    f.received -= 31
    assert not f.unchanged(same)
    f.received = time.monotonic()
    action["rect"]["x"] = float("nan")
    assert not f.unchanged(same, action)


def test_image_requests_and_captures_are_bounded_and_cancelled():
    run = vision.VisionRun(vision.VisionSettings(enabled=True, max_calls=1), True)
    f = frame()
    run.request(f)
    with pytest.raises(BudgetExceeded, match="vision_budget"):
        run.request(f)
    for _ in range(3):
        run.capture()
    with pytest.raises(BudgetExceeded, match="vision_capture_budget"):
        run.capture()
    assert run.summary()["calls"] == 1 and run.summary()["required"]
    token = current.set(Budget(4, 30))
    try:
        current.get().cancel.set()
        with pytest.raises(BudgetExceeded, match="cancelled"):
            vision.VisionRun(run.settings).capture()
        with pytest.raises(BudgetExceeded, match="cancelled"):
            vision.VisionRun(run.settings).request(f)
    finally:
        current.reset(token)


def test_box_requires_presence_valid_edges_and_unique_observed_target():
    f = frame()
    action = f.safe["actions"][0]
    box = {"box": {"top": 0.03, "bottom": 0.1, "left": 0.03, "right": 0.1}, "confidence": 0.9}
    vision.validate_box(box, {"noul": 0.99}, f, action)
    for bad in [dict(box, confidence=0.1), dict(box, box={**box["box"], "left": -1}),
                dict(box, box={**box["box"], "right": math.nan}), {},
                dict(box, box={**box["box"], "top": 0.9})]:
        with pytest.raises(vision.VisionUnavailable):
            vision.validate_box(bad, {"noul": 0.99}, f, action)
    with pytest.raises(vision.VisionUnavailable):
        vision.validate_box(box, {"noul": 0.2}, f, action)
    f.safe["actions"].append({**action, "node": 2})
    with pytest.raises(vision.VisionUnavailable):
        vision.validate_box(box, {"noul": 0.99}, f, action)


def test_masked_transport_is_bounded_and_never_falls_back_to_raw_screenshot(stub):
    import hashlib
    from jev_browser.camofox import Camofox, Page, READ_STATE, CamofoxError, CamofoxAuthError, StalePage

    cf = Camofox(stub.url, "own", "tab")
    run = vision.VisionRun(vision.VisionSettings(enabled=True, max_calls=8))
    value = wire()
    value["snapshotHash"] = hashlib.sha256(READ_STATE.encode()).hexdigest()
    stub.replies = [(200, value)]
    f = Page(cf).observe_vision(value["snapshot"]["url"], run)
    assert f.capture_id and len(stub.requests) == 1
    assert stub.requests[0][1] == "/tabs/tab/jev-observation"
    for code, exception in [(404, vision.VisionUnavailable), (503, vision.VisionUnavailable),
                            (403, CamofoxAuthError), (409, StalePage)]:
        stub.replies = [(code, {"error": "do-not-print"})]
        with pytest.raises(exception):
            Page(cf).observe_vision(value["snapshot"]["url"], run)
    stub.replies = [(200, b"x" * 100)]
    with pytest.raises(CamofoxError, match="response limit"):
        cf._request("post", "/small", reply_limit=10)
    stub.replies = [(200, b"not-json")]
    with pytest.raises(CamofoxError, match="non-JSON"):
        cf._request("post", "/small", reply_limit=10)
    stub.replies = [(200, value)]
    with pytest.raises(StalePage):
        Page(cf).observe_vision("https://other.test/", run)
