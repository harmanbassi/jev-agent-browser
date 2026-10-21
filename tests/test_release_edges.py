import sys
import types

import pytest

from jev_browser import camofox, hermes_tool
from jev_browser.policy import URLPolicy
from jev_browser.loop import run_task
from helpers import FakePage, make_state, decision
from test_camofox import stub
from test_hermes_tool import bc


@pytest.mark.parametrize("storage_status", [200, 404, 500])
def test_owned_context_cleanup_purges_profiles_but_allows_no_persistence_plugin(stub, storage_status):
    cf = camofox.Camofox(stub.url, "own-user", "t")
    stub.replies = [(200, {}), (200, {}), (storage_status, {})]
    if storage_status == 500:
        with pytest.raises(camofox.CamofoxError):
            cf.close_session()
    else:
        cf.close_session()
    assert [r[1] for r in stub.requests] == ["/tabs/t", "/sessions/own-user", "/sessions/own-user/storage_state"]


def test_control_redirects_and_raw_error_bodies_are_not_forwarded(stub):
    stub.replies = [(302, {}), (500, {"error": "credential-do-not-print"})]
    cf = camofox.Camofox(stub.url, "u", "t")
    with pytest.raises(camofox.CamofoxError, match="redirected"):
        cf.click("#a")
    with pytest.raises(camofox.CamofoxError) as caught:
        cf.click("#a")
    assert "credential-do-not-print" not in str(caught.value)


def test_known_viewport_protocol_mismatch_uses_actual_viewport(stub, caplog):
    stub.replies = [(500, {"error": "internal error"}), (200, {"result": {"width": 1280, "height": 720}})]
    camofox.Camofox(stub.url, "u", "t").viewport(1120, 780)
    assert "current viewport" in caplog.text


def test_legacy_profile_reset_auth_does_not_prevent_context_close(stub):
    stub.replies = [(200, {}), (200, {}), (403, {})]
    assert camofox.Camofox(stub.url, "u", "t").close_session() is False


@pytest.mark.parametrize("url", ["http://[fd00:ec2::254]", "https://a.test/?apiKey=secret", "https://a.test/#access_token=secret"])
def test_metadata_and_camel_case_credentials_blocked_even_with_private_opt_in(url):
    assert URLPolicy(allow_private=True)(url)


@pytest.mark.parametrize("reply", [[1], {"url": "https://a.test"}])
def test_malformed_browser_snapshot_is_a_controlled_error(stub, reply):
    stub.replies = [(200, {}), (200, {"result": reply})]
    with pytest.raises(camofox.CamofoxError, match="malformed page snapshot"):
        camofox.Page(camofox.Camofox(stub.url, "u", "t")).observe()


def test_new_hermes_layout_keeps_url_checks(bc, monkeypatch):
    # Instance methods are class attributes; shadow them to model removed exports.
    monkeypatch.setattr(bc.bt, "_allow_private_urls", None, raising=False)
    monkeypatch.setattr(bc.bt, "_sensitive_query_param_name", None, raising=False)
    cloud = types.ModuleType("tools.browser_tool_cloud")
    cloud._allow_private_urls = lambda: False
    safety = types.ModuleType("tools.url_safety")
    safety.sensitive_query_param_name = lambda url: "token" if "token=" in url else None
    monkeypatch.setitem(sys.modules, "tools.browser_tool_cloud", cloud)
    monkeypatch.setitem(sys.modules, "tools.url_safety", safety)
    assert hermes_tool.url_block("https://a.test") is None
    assert "credential-like" in hermes_tool.url_block("https://a.test/?token=private")
    monkeypatch.setitem(sys.modules, "tools.browser_tool_cloud", None)
    assert "unsupported Hermes" in hermes_tool.url_block("https://a.test")


def test_uncertain_done_is_a_pause_for_the_calling_agent(monkeypatch):
    monkeypatch.setattr("jev_browser.loop.choose", lambda *a: decision("DONE", confidence=0.1))
    assert run_task(FakePage([make_state()]), "g")["reason"] == "low_confidence"
