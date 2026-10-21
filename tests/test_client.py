import threading
import types

import pytest

from jev_browser import client
from jev_browser.config import Settings


@pytest.fixture
def browser(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "test-key")
    opened = []

    def open_tab(base, user, session, url, **kw):
        cf = types.SimpleNamespace(user_id=user, closed=False, released=False)
        cf.close = lambda: setattr(cf, "closed", True)
        cf._request = lambda *a: setattr(cf, "released", True)
        cf.close_session = lambda: (cf.close(), cf._request("delete", "owned-session"))
        opened.append((cf, kw))
        return cf

    monkeypatch.setattr(client.Camofox, "open", open_tab)
    monkeypatch.setattr(client, "run_task", lambda *a, **kw: {"status": "paused", "reason": "need_guidance", "steps": []})
    with client.Browser(Settings(camofox_api_key="test-auth"), idle_seconds=30, max_sessions=2) as b:
        b.opened = opened
        yield b
    assert all(cf.closed and cf.released for cf, _ in opened)


def test_sessions_isolate_cookies_and_use_browser_auth(browser):
    first = browser.start("https://a.test", "g")
    second = browser.start("https://a.test", "g")
    assert first["session_id"] != second["session_id"]
    assert browser.opened[0][0].user_id != browser.opened[1][0].user_id
    assert browser.opened[0][1]["headers"] == {"Authorization": "Bearer test-auth"}
    assert browser.inspect(first["session_id"])["reason"] == "need_guidance"
    assert browser.start("https://a.test", "g")["status"] == "error"
    assert browser.close(first["session_id"])["status"] == "closed"
    assert browser.inspect(first["session_id"])["status"] == "error"


def test_continuation_keeps_only_its_own_history(browser, monkeypatch):
    seen = []

    def run(page, goal, **kw):
        seen.append(kw["history"])
        return {"status": "done", "steps": [{"action": "search"}] * 15}

    monkeypatch.setattr(client, "run_task", run)
    sid = browser.start("https://a.test", "g")["session_id"]
    browser.run(sid, "continue")
    browser.start("https://a.test", "other")
    assert seen[0] == [] and len(seen[1]) == 10 and seen[2] == []


def test_expired_sessions_are_cleaned_and_unknown_ids_are_safe(browser):
    sid = browser.start("https://a.test", "g")["session_id"]
    browser._sessions[sid].touched -= 31
    assert browser.run(sid, "g")["status"] == "error"
    assert browser.cancel("missing")["status"] == "error"
    assert browser.inspect([])["status"] == "error"
    assert browser.close([])["status"] == "error"


def test_busy_session_can_be_cancelled_but_not_run_or_closed(browser, monkeypatch):
    sid = browser.start("https://a.test", "g")["session_id"]
    entered, cancelled = threading.Event(), threading.Event()

    def run(*a, cancel, **kw):
        entered.set()
        assert cancel.wait(3)
        cancelled.set()
        return {"status": "paused", "reason": "cancelled", "steps": []}

    monkeypatch.setattr(client, "run_task", run)
    worker = threading.Thread(target=browser.run, args=(sid, "g"))
    worker.start()
    assert entered.wait(3)
    assert browser.inspect(sid)["status"] == "running"
    assert browser.run(sid, "g")["status"] == "error"
    assert browser.close(sid)["status"] == "error"
    worker.join(3)
    assert cancelled.is_set() and not worker.is_alive()
    assert browser.cancel(sid)["status"] == "cancelling"


def test_shutdown_of_running_task_eventually_cleans_its_context(browser, monkeypatch):
    sid = browser.start("https://a.test", "g")["session_id"]
    entered = threading.Event()

    def run(*a, cancel, **kw):
        entered.set()
        assert cancel.wait(3)
        return {"status": "paused", "steps": []}

    monkeypatch.setattr(client, "run_task", run)
    worker = threading.Thread(target=browser.run, args=(sid, "g"))
    worker.start()
    assert entered.wait(3)
    browser.shutdown()
    worker.join(3)
    assert not browser._sessions and not worker.is_alive()


def test_validation_prevents_network_and_closed_browser_rejects_start(browser, monkeypatch):
    assert browser.start("http://127.0.0.1", "g")["status"] == "error"
    assert browser.start("https://a.test", "g", max_steps="bad")["status"] == "error"
    monkeypatch.setattr(client, "api_key", lambda: "")
    assert browser.start("https://a.test", "g")["status"] == "error"
    monkeypatch.setattr(client, "api_key", lambda: "k")
    browser.shutdown()
    assert browser.start("https://a.test", "g")["status"] == "error"


def test_open_and_cleanup_errors_are_reported(browser, monkeypatch):
    sid = browser.start("https://a.test", "g")["session_id"]

    def failed(*a, **kw):
        raise client.CamofoxError("offline")

    browser._sessions[sid].cf._request = failed
    assert "cleanup failed" in browser.close(sid)["reason"]
    browser.opened.clear()
    monkeypatch.setattr(client.Camofox, "open", failed)
    assert browser.start("https://a.test", "g")["reason"] == "offline"


def test_invalid_capacity():
    with pytest.raises(ValueError):
        client.Browser(max_sessions=0)


def test_cancellation_before_worker_start_is_preserved(browser, monkeypatch):
    sid = browser.open("https://a.test")["session_id"]
    stop = threading.Event()
    stop.set()

    def run(*a, cancel, **kw):
        assert cancel is stop and cancel.is_set()
        return {"status": "paused", "reason": "cancelled", "steps": []}

    monkeypatch.setattr(client, "run_task", run)
    assert browser.run(sid, "g", cancel=stop)["reason"] == "cancelled"


def test_legacy_reset_warning_is_retained_for_shutdown_clients(browser, monkeypatch, caplog):
    sid = browser.open("https://a.test")["session_id"]
    cf = browser._sessions[sid].cf

    def close():
        cf.closed = cf.released = True
        return False

    monkeypatch.setattr(cf, "close_session", close)
    out = browser.close(sid)
    assert out["status"] == "closed" and "saved-profile reset" in out["warning"]
    assert browser.cleanup_warnings == [out["warning"]]
    assert "saved-profile reset" in caplog.text


def test_failed_creation_cleans_only_the_new_owned_identity(browser, monkeypatch):
    existing = browser.open("https://a.test")["session_id"]
    attempts, cleaned = [], []

    def failed(base, user, session, url, **kw):
        attempts.append(user)
        raise client.CamofoxError("navigation failed after allocation")

    monkeypatch.setattr(client.Camofox, "open", failed)
    monkeypatch.setattr(client.Camofox, "close_session", lambda cf: cleaned.append((cf.user_id, cf.headers)))
    assert browser.open("https://a.test")["reason"] == "navigation failed after allocation"
    assert cleaned == [(attempts[0], {"Authorization": "Bearer test-auth"})]
    assert browser._sessions[existing].cf.user_id != attempts[0]


def test_cancel_during_worker_initialization_is_not_lost(browser, monkeypatch):
    sid = browser.open("https://a.test")["session_id"]
    initializing, release, cancel_returned = threading.Event(), threading.Event(), threading.Event()
    stop = threading.Event()

    def event():
        initializing.set()
        assert release.wait(3)
        return stop

    def run(*a, cancel, **kw):
        assert cancel.wait(3), "cancel was lost while the worker initialized"
        return {"status": "paused", "reason": "cancelled", "steps": []}

    def cancel():
        browser.cancel(sid)
        cancel_returned.set()

    worker = threading.Thread(target=browser.run, args=(sid, "g"))
    canceller = threading.Thread(target=cancel)
    monkeypatch.setattr(client, "threading", types.SimpleNamespace(Event=event))
    monkeypatch.setattr(client, "run_task", run)
    try:
        worker.start()
        assert initializing.wait(3)
        canceller.start()
        cancel_returned.wait(0.1)
    finally:
        release.set()
        worker.join(4)
        canceller.join(4)
    assert not worker.is_alive() and not canceller.is_alive()
    assert browser.inspect(sid)["reason"] == "cancelled"


def test_visual_requirement_persists_and_can_be_explicitly_cleared(browser, monkeypatch):
    monkeypatch.setenv("JEV_VISION_ENABLED", "1")
    seen = []
    monkeypatch.setattr(client, "run_task", lambda *a, **kw: seen.append(kw) or {"status": "paused", "steps": []})
    sid = browser.start("https://a.test", "red", require_visual=True)["session_id"]
    browser.run(sid, "continue")
    browser.run(sid, "text only", require_visual=False)
    assert seen[0]["require_visual"] and seen[1]["require_visual"]
    assert "require_visual" not in seen[2]
    monkeypatch.setenv("JEV_VISION_ENABLED", "0")
    assert browser.start("https://a.test", "red", require_visual=True)["reason"] == "vision_disabled"
    assert browser.run(sid, "red", require_visual=True)["reason"] == "vision_disabled"
