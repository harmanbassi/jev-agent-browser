from concurrent.futures import ThreadPoolExecutor
import json
import sys
import threading
import types

import pytest

from jev_browser import environment, hermes_tool, jev
from jev_browser.config import Settings
from helpers import make_state
from test_hermes_tool import bc, done


def test_concurrent_profile_settings_do_not_leak_or_change_process_environment(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "global-key")
    barrier = threading.Barrier(2)

    def read(name):
        settings = {"JEV_OPENROUTER_KEY": name, "JEV_MODEL": name + "-model"}
        with environment.use(settings.get):
            barrier.wait(timeout=3)
            assert jev.api_key() == name
            assert environment.get("JEV_MODEL") == name + "-model"
        return jev.api_key()

    with ThreadPoolExecutor(2) as workers:
        assert list(workers.map(read, ("profile-a", "profile-b"))) == ["global-key", "global-key"]
    assert jev.api_key() == "global-key"


def test_profile_miss_never_uses_global_key_or_development_override(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "global-key")
    monkeypatch.setenv("JEV_ALLOW_INSECURE_MODEL_URLS", "1")
    with environment.use({}.get):
        with pytest.raises(jev.ModelError, match="No OpenRouter key"):
            jev.post_json("https://provider.test", {})
    with environment.use({"OPENROUTER_API_KEY": "scoped-key"}.get):
        with pytest.raises(jev.ModelError, match="HTTPS"):
            jev.post_json("http://provider.test", {})


def test_model_and_text_endpoints_and_browser_settings_use_the_scope(monkeypatch):
    sent = []
    monkeypatch.setattr(jev, "post_json", lambda url, body: sent.append((url, body)) or {})
    values = {"JEV_URL": "https://a.test/decisions", "JEV_MODEL": "a-model",
              "JEV_TEXT_URL": "https://a.test/text", "JEV_TEXT_MODEL": "a-text-model",
              "CAMOFOX_ACCESS_KEY": "a-browser-key"}
    with environment.use(values.get):
        with pytest.raises(jev.ModelError):
            jev.choose(make_state(), "g", [])
        with pytest.raises(jev.ModelError):
            jev.field_text({})
        assert Settings.from_env().headers == {"Authorization": "Bearer a-browser-key"}
    assert sent[0][0] == values["JEV_URL"] and sent[0][1]["model"] == values["JEV_MODEL"]
    assert sent[1][0] == values["JEV_TEXT_URL"] and sent[1][1]["model"] == values["JEV_TEXT_MODEL"]


def test_hermes_checks_and_calls_bind_the_active_profile_and_restore_afterwards(bc, monkeypatch):
    values = {"OPENROUTER_API_KEY": "profile-key"}
    monkeypatch.setattr(hermes_tool, "_environment_reader", lambda: values.get)

    def run(*a, **kw):
        assert jev.api_key() == "profile-key"
        return done()

    monkeypatch.setattr(hermes_tool, "run_task", run)
    assert hermes_tool.check()
    assert json.loads(hermes_tool.handle({"goal": "g"}))["success"]
    assert jev.api_key() == "k"  # existing fixture's process env, restored
    values.clear()
    assert not hermes_tool.check()
    assert not json.loads(hermes_tool.handle({"goal": "g"}))["success"]


def test_older_hermes_falls_back_to_environment_and_missing_scope_fails_closed(bc, monkeypatch):
    monkeypatch.setitem(sys.modules, "agent.secret_scope", None)
    assert hermes_tool._environment_reader()("JEV_OPENROUTER_KEY") == "k"

    def missing_scope(name, default=None):
        raise RuntimeError("private-profile-state-do-not-print")

    monkeypatch.setattr(hermes_tool, "_environment_reader", lambda: missing_scope)
    assert not hermes_tool.check()
    out = json.loads(hermes_tool.handle({"goal": "g"}))
    assert not out["success"] and "private-profile-state" not in str(out)


def test_history_profile_key_uses_host_context_and_supports_older_hosts(monkeypatch):
    module = types.ModuleType("hermes_constants")
    module.get_hermes_home = lambda: "active-profile"
    monkeypatch.setitem(sys.modules, "hermes_constants", module)
    assert hermes_tool._profile_key() == "active-profile"
    monkeypatch.setitem(sys.modules, "hermes_constants", None)
    monkeypatch.setenv("HERMES_HOME", "legacy-home")
    assert hermes_tool._profile_key() == "legacy-home"
