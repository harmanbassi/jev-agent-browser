import json

import pytest

from jev_browser import hermes_tool
from test_hermes_tool import bc, runs, done  # reuse the existing Hermes contract fixtures


@pytest.mark.parametrize("args", [
    None, [], {"goal": []}, {"goal": "g", "max_steps": "10"},
    {"goal": "g", "max_steps": 101}, {"goal": "g", "max_model_calls": 0},
    {"goal": "g", "timeout": -1}, {"goal": "g", "url": ["https://a.test"]},
])
def test_bad_arguments_are_structured_errors_before_navigation(bc, runs, args):
    out = json.loads(hermes_tool.handle(args))
    assert not out["success"] and not bc.bt.navigated and not runs[0]


def test_explicit_limits_preserve_hermes_guard_and_shared_browser_auth(bc, monkeypatch):
    calls = []

    def run(page, goal, **kw):
        calls.append((page.cf, kw))
        return done()

    monkeypatch.setattr(hermes_tool, "run_task", run)
    out = json.loads(hermes_tool.handle({"goal": "g", "max_model_calls": 5, "timeout": 10}, task_id="own-task"))
    assert out["success"]
    cf, options = calls[0]
    assert options["max_model_calls"] == 5 and options["timeout"] == 10
    assert options["guard"] is hermes_tool.url_block
    assert cf.user_id == bc.session["user_id"] and cf.headers == bc._auth_headers()


def test_hermes_history_session_count_is_bounded(bc, monkeypatch):
    monkeypatch.setattr(hermes_tool, "run_task", lambda *a, **kw: done())
    for i in range(140):
        hermes_tool.handle({"goal": "g"}, task_id=str(i))
    assert len(hermes_tool._history) == 128


def test_history_isolated_by_profile_and_browser_context_even_with_same_task_id(bc, monkeypatch):
    profile, seen = ["profile-a"], []
    monkeypatch.setattr(hermes_tool, "_profile_key", lambda: profile[0])

    def run(*a, **kw):
        seen.append(kw["history"])
        return done([{"action": profile[0], "text": "profile-local value"}])

    monkeypatch.setattr(hermes_tool, "run_task", run)
    hermes_tool.handle({"goal": "g"})
    profile[0] = "profile-b"
    hermes_tool.handle({"goal": "g"})
    profile[0] = "profile-a"
    hermes_tool.handle({"goal": "g"})
    bc.session["tab_id"] = "new-tab"
    hermes_tool.handle({"goal": "g"})
    assert seen[0] is None and seen[1] is None and seen[3] is None
    assert seen[2] == [{"action": "profile-a", "text": "profile-local value"}]
