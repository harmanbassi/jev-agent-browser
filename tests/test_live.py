"""Opt-in live smoke: real Camofox (127.0.0.1:9377) and real Jev. Costs a few Jev calls.

    JEV_LIVE=1 OPENROUTER_API_KEY=... python3 -m pytest tests/test_live.py -s

Uses a random owned identity and configured browser authentication.
"""

import os
import uuid

import pytest

from jev_browser.camofox import Camofox, Page
from jev_browser.loop import run_task
from jev_browser.config import Settings

pytestmark = pytest.mark.skipif(os.environ.get("JEV_LIVE") != "1", reason="live smoke is opt-in (JEV_LIVE=1)")


def test_wikipedia_article_is_found_and_opened():
    settings = Settings.from_env()
    identity = "jev-browser-live-" + uuid.uuid4().hex
    cf = Camofox(settings.camofox_url, identity, None, headers=settings.headers)
    try:
        cf = Camofox.open(settings.camofox_url, identity, identity,
                          "https://en.wikipedia.org/wiki/Main_Page", headers=settings.headers, guard=settings.policy)
        out = run_task(Page(cf), "Find and open the Wikipedia article about Gödel's incompleteness theorems.",
                       guard=settings.policy)
    finally:
        if cf.close_session() is False:
            pytest.fail("Browser context closed but legacy server denied saved-profile reset")
    print(out["status"], out.get("reason"), out["elapsed_ms"], "ms", out["jev_calls"], "Jev calls", out["steps"])
    assert out["status"] == "done", out
    assert "incompleteness" in out["title"].lower()
