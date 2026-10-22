import pytest

from jev_browser import policy
from jev_browser.loop import run_task
from helpers import FakePage, make_state


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "javascript:alert(1)", "http://", "http://a.test:",
    "https://user:secret@a.test", "https://a.test/?api_key=secret", "https://a.test/?code=secret",
    "https://a.test/\nsecret", "http://[broken", "https://a.test\\@evil.test", None,
    "http://127.0.0.1", "http://10.0.0.1", "http://[::1]", "http://[::ffff:127.0.0.1]",
    "http://100.64.0.1", "http://169.254.169.254", "http://metadata.google.internal",
])
def test_default_policy_blocks_unsafe_urls(url):
    assert policy.URLPolicy()(url)


def test_public_pages_and_explicit_private_opt_in():
    assert policy.URLPolicy()("https://a.test/page?q=hello") is None
    assert policy.URLPolicy(allow_private=True)("http://127.0.0.1:8000") is None
    assert policy.URLPolicy(allowed_hosts=("a.test",))("https://b.test")
    assert policy.URLPolicy(allowed_hosts=("a.test",))("https://a.test") is None


@pytest.mark.parametrize("url", ["http://169.254.169.254", "http://100.100.100.200", "http://metadata"])
def test_private_opt_in_never_allows_metadata(url):
    assert policy.URLPolicy(allow_private=True)(url)


def test_dns_mixed_public_private_and_resolution_failure_fail_closed(monkeypatch):
    monkeypatch.setattr(policy, "addresses", lambda host: {"93.184.215.14", "127.0.0.1"})
    assert policy.URLPolicy()("https://a.test")
    monkeypatch.setattr(policy, "addresses", lambda host: set())
    assert policy.URLPolicy()("https://a.test")

    def failed(host):
        raise OSError("unavailable")

    monkeypatch.setattr(policy, "addresses", failed)
    assert policy.URLPolicy()("https://a.test")


def test_standalone_default_never_sends_private_page_to_model(monkeypatch):
    monkeypatch.setattr("jev_browser.loop.choose", lambda *a: pytest.fail("private content reached model"))
    out = run_task(FakePage([make_state(url="http://127.0.0.1/private", text="secret")]), "read page")
    assert out["status"] == "error" and "text" not in out and out["jev_calls"] == 0


@pytest.mark.parametrize("action", [
    {"kind": "fill", "label": "Email", "sensitive": True},
    {"kind": "fill", "label": "Card number"},
    {"kind": "click", "label": "Sign in"},
    {"kind": "click", "label": "Pay now"},
    {"kind": "click", "label": "Delete account"},
])
def test_sensitive_controls_pause_before_typing_or_clicking(monkeypatch, action):
    from helpers import decision
    action.update(id="e1", node=1)
    monkeypatch.setattr("jev_browser.loop.choose", lambda *a: decision("e1"))
    page = FakePage([make_state(actions=[action])])
    out = run_task(page, "do something")
    assert out["reason"] == "sensitive_action" and not page.acted


def test_normal_search_is_not_sensitive():
    assert policy.action_block({"kind": "fill", "label": "Search flights"}) is None


@pytest.mark.parametrize("input_type, good, bad", [
    ("time", ["19:30", "07:05:09"], ["7:30 pm", "1930", ""]),
    ("date", ["2026-10-22"], ["22/10/2026", "2026-10-22T10:00"]),
    ("datetime-local", ["2026-10-22T19:30"], ["2026-10-22 19:30"]),
    ("month", ["2026-10"], ["Oct 2026"]),
    ("week", ["2026-W43"], ["2026-43"]),
    ("color", ["#ff0000", "#A0b1C2"], ["red", "#fff", "ff0000"]),
    ("range", ["7", "-2.5"], ["seven", "7px"]),
    (None, ["anything at all"], []),
])
def test_typed_field_values_must_use_the_html_value_format(input_type, good, bad):
    assert all(policy.value_format_ok(input_type, v) for v in good)
    assert not any(policy.value_format_ok(input_type, v) for v in bad)
