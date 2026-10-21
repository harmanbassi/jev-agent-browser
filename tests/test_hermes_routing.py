from types import SimpleNamespace

import jev_browser
from jev_browser import hermes_tool
from test_hermes_tool import bc  # existing Hermes contract fixture


def test_plugin_supplies_profile_gated_routing_with_direct_and_deferred_paths(bc):
    tools, sections = [], []
    ctx = SimpleNamespace(register_tool=lambda **kw: tools.append(kw),
                          register_system_prompt_section=lambda **kw: sections.append(kw))
    jev_browser.register(ctx)
    assert tools[0]["handler"] is hermes_tool.handle
    section, = sections
    assert section["id"] == "jev-browser.browsing"
    content = section["content"]({"platform": "telegram"})
    assert len(content) <= section["max_chars"]
    assert "use browser_task (Jev) first" in content
    assert "tool_search" in content and "deferred-tool bridge" in content
    assert "Omit url" in content and "screenshots" in content
    bc.camofox_mode = False
    assert section["content"]({"platform": "telegram"}) == ""


def test_routing_is_absent_for_a_profile_without_its_own_key(bc, monkeypatch):
    monkeypatch.setattr(hermes_tool, "_environment_reader", lambda: {}.get)
    assert hermes_tool.routing_guidance({}) == ""


def test_non_callable_prompt_api_keeps_older_hermes_registration_compatible():
    registered = []
    jev_browser.register(SimpleNamespace(register_tool=lambda **kw: registered.append(kw),
                                         register_system_prompt_section=None))
    assert registered[0]["name"] == "browser_task"
