import json
import sys
import types

import pytest

import jev_browser
from jev_browser import hermes_tool


class FakeBrowserCamofox(types.ModuleType):
    """Stands in for Hermes' tools.browser_camofox."""

    def __init__(self):
        super().__init__("tools.browser_camofox")
        self.camofox_mode = True
        self.session = {"user_id": "hermes_abc", "tab_id": "tab1"}

    def is_camofox_mode(self):
        return self.camofox_mode

    def camofox_navigate(self, url, task_id=None):
        raise AssertionError("must navigate through browser_tool.browser_navigate (Hermes' URL checks)")

    def _get_session(self, task_id):
        return self.session

    def get_camofox_url(self):
        return "http://camofox.test"

    def _auth_headers(self):
        return {"Authorization": "Bearer k"}


class FakeBrowserTool(types.ModuleType):
    """Stands in for Hermes' tools.browser_tool: navigation + URL safety helpers."""

    def __init__(self):
        super().__init__("tools.browser_tool")
        self.navigated, self.nav_reply = [], {"success": True}
        self.allow_private, self.policy = False, None

    def browser_navigate(self, url, task_id=None):
        self.navigated.append((url, task_id))
        return json.dumps(self.nav_reply)

    def _is_always_blocked_url(self, url):
        return "169.254.169.254" in url

    def _is_safe_url(self, url):
        return url.startswith("https://")

    def _allow_private_urls(self):
        return self.allow_private

    def _sensitive_query_param_name(self, url):
        return "api_key" if "api_key=" in url else None

    def check_website_access(self, url):
        return self.policy


@pytest.fixture
def bc(monkeypatch):
    fake, bt = FakeBrowserCamofox(), FakeBrowserTool()
    fake.bt = bt
    tools = types.ModuleType("tools")
    tools.browser_camofox, tools.browser_tool = fake, bt
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.browser_camofox", fake)
    monkeypatch.setitem(sys.modules, "tools.browser_tool", bt)
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "k")
    monkeypatch.setattr(hermes_tool, "_history", {})
    return fake


@pytest.fixture
def runs(monkeypatch):
    """Replace the loop; record what the tool passed it."""
    calls, results = [], []

    def run_task(page, goal, history=None, max_steps=25, guard=None):
        calls.append({"page": page, "goal": goal, "history": history, "max_steps": max_steps, "guard": guard})
        return results.pop(0)

    monkeypatch.setattr(hermes_tool, "run_task", run_task)
    return calls, results


def done(steps=()):
    return {"status": "done", "url": "u", "title": "t", "text": "x", "steps": list(steps), "jev_calls": 1}


def test_check_needs_camofox_and_a_key(bc, monkeypatch):
    assert hermes_tool.check() is True
    bc.camofox_mode = False
    assert hermes_tool.check() is False
    bc.camofox_mode = True
    monkeypatch.delenv("JEV_OPENROUTER_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert hermes_tool.check() is False


def test_check_is_false_outside_hermes(monkeypatch):
    monkeypatch.setitem(sys.modules, "tools", None)
    assert hermes_tool.check() is False


def test_url_navigates_through_hermes_checks_then_runs_on_the_shared_tab(bc, runs):
    calls, results = runs
    results.append(done())

    out = json.loads(hermes_tool.handle({"goal": "find x", "url": "https://a.test"}, task_id="t1"))

    assert bc.bt.navigated == [("https://a.test", "t1")]
    assert calls[0]["guard"] is hermes_tool.url_block
    cf = calls[0]["page"].cf
    assert (cf.base, cf.user_id, cf.tab_id, cf.headers) == (
        "http://camofox.test", "hermes_abc", "tab1", {"Authorization": "Bearer k"})
    assert out["success"] is True and out["status"] == "done" and "text" in out["next"]


def test_goal_is_required(bc, runs):
    out = json.loads(hermes_tool.handle({"goal": "  "}))
    assert out["success"] is False and "goal" in out["error"]


def test_a_url_hermes_refuses_is_reported_and_never_browsed(bc, runs):
    bc.bt.nav_reply = {"success": False, "error": "Blocked: URL targets a private or internal address"}
    out = json.loads(hermes_tool.handle({"goal": "g", "url": "http://10.0.0.1"}))
    assert out["error"] == "Blocked: URL targets a private or internal address" and runs[0] == []


def test_continue_without_an_open_tab_asks_for_a_url(bc, runs):
    bc.session = {"user_id": "u", "tab_id": None}
    out = json.loads(hermes_tool.handle({"goal": "g"}))
    assert "Pass url" in out["error"]


def test_continue_carries_history_and_a_new_url_resets_it(bc, runs):
    calls, results = runs
    step = {"action": "Go", "kind": "click", "text": None, "page_changed": True}
    paused = {**done([step]), "status": "paused", "reason": "need_guidance"}
    results.extend([paused, done(), done()])

    first = json.loads(hermes_tool.handle({"goal": "g", "url": "https://a.test"}, task_id="t"))
    hermes_tool.handle({"goal": "smaller goal"}, task_id="t")
    hermes_tool.handle({"goal": "g", "url": "https://b.test"}, task_id="t")

    assert first["success"] is True and "browser_vision" in first["next"]
    assert calls[1]["history"] == [step]
    assert calls[2]["history"] is None


def test_history_is_kept_short(bc, runs):
    calls, results = runs
    many = [{"action": f"a{i}", "kind": "click", "text": None, "page_changed": True} for i in range(15)]
    results.extend([done(many), done()])
    hermes_tool.handle({"goal": "g", "url": "https://a.test"})
    hermes_tool.handle({"goal": "g"})
    assert len(calls[1]["history"]) == hermes_tool.HISTORY_KEEP


def test_max_steps_reaches_the_loop(bc, runs):
    calls, results = runs
    results.append(done())
    hermes_tool.handle({"goal": "g", "url": "https://a.test", "max_steps": 7})
    assert calls[0]["max_steps"] == 7


@pytest.mark.parametrize("url, why", [
    ("http://169.254.169.254/latest", "metadata"),
    ("http://10.0.0.1/admin", "not a public web page"),
    ("https://a.test/?api_key=x", "credential-like"),
])
def test_url_block_refuses_what_a_third_party_reader_may_not_see(bc, url, why):
    assert why in hermes_tool.url_block(url)


def test_url_block_passes_public_pages_and_honours_policy_and_allow_private(bc):
    assert hermes_tool.url_block("https://a.test/") is None
    bc.bt.allow_private = True
    assert hermes_tool.url_block("http://10.0.0.1/") is None
    bc.bt.policy = {"message": "Blocked by website policy"}
    assert hermes_tool.url_block("https://a.test/") == "Blocked by website policy"

def test_errors_are_unsuccessful_with_a_fallback_hint(bc, runs):
    calls, results = runs
    results.append({"status": "error", "reason": "down", "steps": [], "jev_calls": 0})
    out = json.loads(hermes_tool.handle({"goal": "g", "url": "https://a.test"}))
    assert out["success"] is False and "browser_navigate" in out["next"]


def test_register_offers_browser_task_in_its_own_toolset():
    registered = {}

    class Ctx:
        def register_tool(self, **kw):
            registered.update(kw)

    jev_browser.register(Ctx())
    assert registered["name"] == "browser_task" and registered["toolset"] == "browser_task"
    assert registered["schema"]["name"] == "browser_task"
    assert registered["handler"] is hermes_tool.handle and registered["check_fn"] is hermes_tool.check


def test_visual_requirement_persists_in_native_shared_tab(bc, monkeypatch):
    monkeypatch.setenv("JEV_VISION_ENABLED", "1")
    monkeypatch.setattr(hermes_tool, "_visual_requirements", {})
    seen = []
    monkeypatch.setattr(hermes_tool, "run_task", lambda *a, **kw: seen.append(kw) or done())
    for args in [{"require_visual": True}, {}, {"require_visual": False}]:
        assert json.loads(hermes_tool.handle({"goal": "red", **args}))["success"]
    assert [kw.get("require_visual") for kw in seen] == [True, True, False]
    assert not hermes_tool._tab_locks
    monkeypatch.setenv("JEV_VISION_ENABLED", "0")
    assert not json.loads(hermes_tool.handle({"goal": "red", "require_visual": True}))["success"]


def test_native_profile_busy_prevents_navigation(bc, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    def run(*a, **kw):
        entered.set()
        assert release.wait(3)
        return done()
    monkeypatch.setattr(hermes_tool, "run_task", run)
    thread = threading.Thread(target=hermes_tool.handle, args=({"goal": "g"},))
    thread.start()
    try:
        assert entered.wait(3)
        out = json.loads(hermes_tool.handle({"goal": "g", "url": "https://a.test"}, task_id="another"))
        assert "busy" in out["error"] and not bc.bt.navigated
    finally:
        release.set()
        thread.join(3)
    assert not hermes_tool._tab_locks


def test_paused_guidance_names_the_manual_tools_then_continuing(bc, runs):
    calls, results = runs
    results.append({**done(), "status": "paused", "reason": "sensitive_action"})
    out = json.loads(hermes_tool.handle({"goal": "g", "url": "https://a.test"}, task_id="t"))
    assert all(tool in out["next"] for tool in ("browser_snapshot", "browser_type", "browser_press"))
    assert "browser_task again" in out["next"] and "sensitive_action" in out["next"]
