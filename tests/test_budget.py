import threading

import pytest

from jev_browser import budget, jev, loop
from jev_browser.camofox import Camofox, CamofoxError
from helpers import FakePage, decision, make_state


@pytest.mark.parametrize("args", [
    {"goal": ""}, {"goal": 1}, {"max_steps": 0}, {"max_steps": True}, {"max_steps": 101},
    {"max_model_calls": 0}, {"max_model_calls": "3"}, {"timeout": float("nan")},
    {"timeout": 901}, {"min_confidence": -1}, {"min_target_confidence": "x"},
])
def test_invalid_limits_return_errors_without_observing(args):
    out = loop.run_task(FakePage([]), **{"goal": "g", **args})
    assert out["status"] == "error" and not out["steps"]


def test_cancellation_and_timeout_pause_without_actions(monkeypatch):
    stop = threading.Event()
    stop.set()
    assert loop.run_task(FakePage([]), "g", cancel=stop)["reason"] == "cancelled"
    clock = iter([0, 2])
    monkeypatch.setattr(budget.time, "monotonic", lambda: next(clock))
    assert loop.run_task(FakePage([]), "g", timeout=1)["reason"] == "timeout"


def test_request_budget_counts_retry_and_text_helper_calls(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "secret")
    replies = iter([type("Reply", (), {"status_code": 503, "close": lambda self: None})()])
    monkeypatch.setattr(jev._HTTP, "post", lambda *a, **k: next(replies))
    monkeypatch.setattr(jev.time, "sleep", lambda _: None)
    # First decision attempts an HTTP request, then the retry must stop.
    monkeypatch.setattr(loop, "choose", lambda *a: jev.post_json("https://provider.test", {}))
    out = loop.run_task(FakePage([make_state()]), "g", max_model_calls=1)
    assert out["reason"] == "model_budget" and out["model_requests"] == 1
    assert budget.current.get() is None


def test_deadline_checked_again_before_acting(monkeypatch):
    stop = threading.Event()

    def choose(*a):
        stop.set()
        return decision("e2")

    monkeypatch.setattr(loop, "choose", choose)
    page = FakePage([make_state()])
    out = loop.run_task(page, "g", cancel=stop)
    assert out["reason"] == "cancelled" and not page.acted


def test_http_timeouts_follow_remaining_budget(monkeypatch):
    token = budget.current.set(budget.Budget(2, 2))
    try:
        assert 0 < budget.request_timeout(25) <= 2
        assert budget.current.get().calls == 1
    finally:
        budget.current.reset(token)
    assert budget.request_timeout(25) == 25


def test_create_tab_rejects_private_url_before_network(monkeypatch):
    monkeypatch.setattr("jev_browser.camofox.requests.request", lambda *a, **k: pytest.fail("navigated"))
    with pytest.raises(CamofoxError, match="public address"):
        Camofox.open("http://127.0.0.1:9377", "u", "s", "http://127.0.0.1/private")


def test_create_tab_validates_server_reply(monkeypatch):
    monkeypatch.setattr("jev_browser.camofox.requests.request", lambda *a, **k: type(
        "Reply", (), {"status_code": 200, "json": lambda self: {"ok": True}})())
    with pytest.raises(CamofoxError, match="tabId"):
        Camofox.open("http://127.0.0.1:9377", "u", "s", "https://public.test")
