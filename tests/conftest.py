"""Offline fixtures: reserved .test names represent public fixture pages."""
import pytest

from jev_browser import policy


@pytest.fixture(autouse=True)
def fixture_dns(monkeypatch):
    original = policy.addresses

    def resolve(host):
        if host.endswith(".test"):
            return {"93.184.215.14"}
        return original(host)

    monkeypatch.setattr(policy, "addresses", resolve)
