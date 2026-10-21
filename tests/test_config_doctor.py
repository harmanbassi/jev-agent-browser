import types

import pytest
import requests

from jev_browser import doctor, jev
from jev_browser import environment
from jev_browser.config import Settings, endpoint, flag
from test_camofox import stub


def test_environment_config_and_secrets_are_not_printed(monkeypatch):
    monkeypatch.setenv("CAMOFOX_API_KEY", "private-browser-key")
    monkeypatch.setenv("JEV_ALLOW_PRIVATE_URLS", "1")
    monkeypatch.setenv("JEV_ALLOWED_HOSTS", "Example.COM., localhost")
    s = Settings.from_env()
    assert "private-browser-key" not in repr(s)
    assert s.headers == {"Authorization": "Bearer private-browser-key"}
    assert s.policy.allow_private and s.policy.allowed_hosts == ("example.com", "localhost")
    monkeypatch.setenv("JEV_ALLOW_PRIVATE_URLS", "maybe")
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize("url", ["ftp://a.test", "http://a.test", "https://user:secret@a.test", "https://a.test/?key=secret", "https://a.test:invalid", "https://a.test/#secret"])
def test_model_endpoints_reject_insecure_or_credential_urls(url):
    with pytest.raises(ValueError) as caught:
        endpoint(url, "JEV_URL")
    assert "secret" not in str(caught.value)


def test_remote_camofox_requires_tls_or_explicit_opt_in(monkeypatch):
    with pytest.raises(ValueError, match="HTTPS"):
        Settings("http://browser.test:9377")
    monkeypatch.setenv("JEV_ALLOW_INSECURE_CAMOFOX", "1")
    assert Settings("http://browser.test:9377").headers == {}
    assert Settings("https://browser.test").camofox_url.startswith("https:")
    assert Settings("http://localhost:9377")


def test_model_key_never_sent_to_insecure_endpoint(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "secret")
    with pytest.raises(jev.ModelError, match="HTTPS"):
        jev.post_json("http://provider.test", {})


@pytest.fixture
def health(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "secret")
    monkeypatch.setattr(doctor.requests, "get", lambda *a, **kw: types.SimpleNamespace(status_code=200, json=lambda: {"ok": True}))


def test_doctor_read_only_and_does_not_make_paid_model_calls(health, monkeypatch):
    monkeypatch.setattr(doctor.Camofox, "open", lambda *a, **kw: pytest.fail("opened tab"))
    out = doctor.diagnose()
    assert out["ok"] and "secret" not in str(out)
    monkeypatch.delenv("JEV_OPENROUTER_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert not doctor.diagnose()["ok"]


def test_doctor_reports_config_endpoint_and_connection_errors(health, monkeypatch):
    monkeypatch.setenv("JEV_ALLOW_PRIVATE_URLS", "invalid")
    assert not doctor.diagnose()["ok"]
    monkeypatch.delenv("JEV_ALLOW_PRIVATE_URLS")
    monkeypatch.setenv("JEV_URL", "http://insecure.test")

    def failed(*a, **kw):
        raise requests.ConnectionError("secret must not be shown")

    monkeypatch.setattr(doctor.requests, "get", failed)
    out = doctor.diagnose()
    assert not out["ok"] and "secret must" not in str(out)


def test_doctor_probe_closes_only_its_throwaway_identity(health, monkeypatch):
    calls = []
    cf = types.SimpleNamespace(user_id="jev-doctor-fixture", evaluate=lambda expression: 2,
                               close=lambda: calls.append("close"), _request=lambda *a: calls.append(a))
    cf.close_session = lambda: calls.append("close_session")
    monkeypatch.setattr(doctor.Camofox, "open", lambda *a, **kw: cf)
    assert doctor.diagnose(probe=True)["ok"]
    assert calls == ["close_session"]

    def failed(*a, **kw):
        raise doctor.CamofoxError("offline")

    monkeypatch.setattr(doctor.Camofox, "open", failed)
    monkeypatch.setattr(doctor.Camofox, "close_session", lambda cf: calls.append(cf.user_id))
    assert not doctor.diagnose(probe=True)["ok"]
    assert calls[-1].startswith("jev-doctor-")


def test_doctor_uses_profile_endpoints_and_reports_legacy_cleanup_denial(health, monkeypatch):
    with environment.use({"JEV_OPENROUTER_KEY": "scoped", "JEV_URL": "http://insecure.test"}.get):
        assert not doctor.diagnose()["ok"]
    cf = types.SimpleNamespace(evaluate=lambda expression: 2, close_session=lambda: False)
    monkeypatch.setattr(doctor.Camofox, "open", lambda *a, **kw: cf)
    out = doctor.diagnose(probe=True)
    assert not out["ok"] and out["checks"][-1]["name"] == "cleanup"
    assert "saved-profile reset" in out["checks"][-1]["message"]


def test_doctor_malformed_health_status_is_a_diagnostic_failure(health, monkeypatch):
    monkeypatch.setattr(doctor.requests, "get", lambda *a, **kw: types.SimpleNamespace(
        status_code=200, json=lambda: {"status": []}))
    assert not doctor.diagnose()["ok"]


def test_example_model_key_is_rejected_before_probe_or_provider_call(health, monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "replace-with-your-openrouter-key")
    monkeypatch.setattr(doctor.Camofox, "open", lambda *a, **kw: pytest.fail("opened tab"))
    monkeypatch.setattr(jev._HTTP, "post", lambda *a, **kw: pytest.fail("called provider"))
    out = doctor.diagnose(probe=True)
    check = next(c for c in out["checks"] if c["name"] == "model_key")
    assert not out["ok"] and not check["ok"] and "replace example" in check["message"]
    assert "Key configured" not in str(out)
    with pytest.raises(jev.ModelError, match="Replace the example"):
        jev.post_json(jev.DECISIONS_URL, {})


@pytest.mark.parametrize("name", ["CAMOFOX_ACCESS_KEY", "CAMOFOX_API_KEY"])
def test_example_browser_key_fails_configuration_without_network(monkeypatch, name):
    monkeypatch.delenv("CAMOFOX_ACCESS_KEY", raising=False)
    monkeypatch.setenv(name, "replace-with-a-long-random-browser-key")
    monkeypatch.setattr(doctor.requests, "get", lambda *a, **kw: pytest.fail("sent placeholder"))
    out = doctor.diagnose(probe=True)
    assert not out["ok"] and "Replace the example" in out["checks"][0]["message"]


@pytest.mark.parametrize("status", [401, 403])
def test_probe_auth_rejection_is_clear_without_spurious_cleanup(health, stub, monkeypatch, status):
    monkeypatch.setenv("CAMOFOX_URL", stub.url)
    monkeypatch.setenv("JEV_ALLOW_INSECURE_CAMOFOX", "1")
    monkeypatch.setenv("CAMOFOX_ACCESS_KEY", "wrong-private-browser-key")
    stub.replies = [(status, {"error": "private-server-detail"})]
    out = doctor.diagnose(probe=True)
    assert not out["ok"]
    check = next(c for c in out["checks"] if c["name"] == "authentication")
    assert "CAMOFOX_ACCESS_KEY" in check["message"] and f"HTTP {status}" in check["message"]
    assert len(stub.requests) == 1 and stub.requests[0][1] == "/tabs"
    assert not any(c["name"] == "cleanup" for c in out["checks"])
    for misleading in ("configuration/version", "idle reaper", "wrong-private", "private-server-detail"):
        assert misleading not in str(out)


def test_doctor_health_auth_rejection_does_not_require_json(health, monkeypatch):
    monkeypatch.setattr(doctor.requests, "get", lambda *a, **kw: types.SimpleNamespace(status_code=401))
    out = doctor.diagnose()
    check = next(c for c in out["checks"] if c["name"] == "camofox")
    assert not out["ok"] and "rejected browser authentication" in check["message"]


def test_probe_reports_auth_loss_after_creation_and_during_cleanup(health, monkeypatch):
    def rejected(*args):
        raise doctor.CamofoxAuthError("Camofox rejected browser authentication")

    cf = types.SimpleNamespace(evaluate=rejected, close_session=rejected)
    monkeypatch.setattr(doctor.Camofox, "open", lambda *a, **kw: cf)
    out = doctor.diagnose(probe=True)
    assert not out["ok"] and out["checks"][-1]["name"] == "cleanup"
    assert "idle reaper" not in str(out) and "configuration/version" not in str(out)


@pytest.mark.parametrize("compatible,paid", [(True, False), (True, True), (False, False)])
def test_vision_diagnostics_separate_free_capture_from_paid_probe(health, monkeypatch, compatible, paid):
    import hashlib
    from jev_browser import camofox
    from test_vision import frame
    monkeypatch.setenv("JEV_VISION_ENABLED", "1")
    monkeypatch.setattr(doctor.Camofox, "_request", lambda *a, **kw: {
        "protocol": 1, "masked": True, "snapshotHash": hashlib.sha256(camofox.READ_STATE.encode()).hexdigest() if compatible else "old"})
    cf = types.SimpleNamespace(evaluate=lambda s: 2, close_session=lambda: True)
    monkeypatch.setattr(doctor.Camofox, "open", lambda *a, **kw: cf)
    monkeypatch.setattr(doctor.Page, "observe_vision", lambda *a: frame())
    calls = []
    monkeypatch.setattr(jev, "verify_visual", lambda *a: calls.append(1) or True)
    out = doctor.diagnose(vision=True, vision_model_probe=paid)
    assert out["ok"] is compatible
    assert bool(calls) is (compatible and paid)
    monkeypatch.setenv("JEV_VISION_ENABLED", "0")
    assert not doctor.diagnose(vision=True)["ok"]


def test_vision_doctor_handles_malformed_capabilities(health, monkeypatch):
    monkeypatch.setenv('JEV_VISION_ENABLED', '1')
    monkeypatch.setattr(doctor.Camofox, '_request', lambda *a, **kw: [])
    cf = types.SimpleNamespace(evaluate=lambda s: 2, close_session=lambda: True)
    monkeypatch.setattr(doctor.Camofox, 'open', lambda *a, **kw: cf)
    assert not doctor.diagnose(vision=True)['ok']
