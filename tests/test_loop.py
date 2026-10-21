import pytest

from jev_browser import loop
from jev_browser.camofox import CamofoxError, StalePage
from jev_browser.jev import ModelError

from helpers import FakePage, decision, make_state


def script(monkeypatch, decisions, texts=()):
    """Feed loop.choose / loop.field_text scripted answers; record what choose saw."""
    decisions, texts, seen = list(decisions), list(texts), []

    def choose(state, goal, history):
        seen.append([dict(h) for h in history])
        d = decisions.pop(0)
        if isinstance(d, Exception):
            raise d
        return d

    monkeypatch.setattr(loop, "choose", choose)
    monkeypatch.setattr(loop, "field_text", lambda ctx: texts.pop(0))
    return seen


def test_done_returns_page_content_and_steps(monkeypatch):
    before, after = make_state(marker="a"), make_state(url="https://example.test/r", text="Results", marker="b")
    page = FakePage([before, after])
    script(monkeypatch, [decision("e1", "TYPE_TEXT"), decision("DONE")], texts=["gödel"])

    out = loop.run_task(page, "search gödel")

    assert out["status"] == "done"
    assert out["url"] == "https://example.test/r" and out["text"] == "Results"
    assert page.acted == [("e1", "gödel")]
    assert out["steps"][0]["action"] == "Search" and out["steps"][0]["page_changed"] is True
    assert out["jev_calls"] == 2 and "elements" not in out


@pytest.mark.parametrize("stop, reason", [("NEED_GUIDANCE", "need_guidance"), ("BLOCKED", "blocked")])
def test_stop_choices_pause_with_the_element_table(monkeypatch, stop, reason):
    page = FakePage([make_state()])
    script(monkeypatch, [decision(stop)])

    out = loop.run_task(page, "goal")

    assert out["status"] == "paused" and out["reason"] == reason
    assert [e["label"] for e in out["elements"]] == ["Search", "Go"]


def test_low_confidence_pauses_before_acting(monkeypatch):
    page = FakePage([make_state()])
    script(monkeypatch, [decision("e2", "CLICK", confidence=0.2)])

    out = loop.run_task(page, "goal", min_confidence=0.35)

    assert out["reason"] == "low_confidence" and out["confidence"] == 0.2
    assert page.acted == []


def test_split_target_confidence_still_acts(monkeypatch):
    page = FakePage([make_state(marker="a"), make_state(marker="b")])
    script(monkeypatch, [decision("e2", "CLICK", confidence=0.95, target_confidence=0.41), decision("DONE")])

    out = loop.run_task(page, "goal")

    assert out["status"] == "done" and out["steps"][0]["target_confidence"] == 0.41


def test_very_uncertain_target_pauses(monkeypatch):
    page = FakePage([make_state()])
    script(monkeypatch, [decision("e2", "CLICK", confidence=0.95, target_confidence=0.1)])

    out = loop.run_task(page, "goal")

    assert out["reason"] == "low_confidence" and out["target_confidence"] == 0.1
    assert page.acted == []


def test_missing_field_value_pauses_and_names_the_field(monkeypatch):
    page = FakePage([make_state()])
    script(monkeypatch, [decision("e1", "TYPE_TEXT")], texts=[None])

    out = loop.run_task(page, "goal")

    assert out["reason"] == "missing_value" and out["field"] == "Search"
    assert page.acted == []


def test_three_actions_without_page_change_pause_as_no_progress(monkeypatch):
    page = FakePage([make_state()])
    script(monkeypatch, [decision("e2", "CLICK")] * 3)

    out = loop.run_task(page, "goal")

    assert out["reason"] == "no_progress" and len(out["steps"]) == 3


def test_the_same_action_three_times_running_pauses_even_if_the_page_flickers(monkeypatch):
    page = FakePage([make_state(marker=str(i), text=f"page {i}") for i in range(6)])
    script(monkeypatch, [decision("e2", "CLICK")] * 3)

    out = loop.run_task(page, "goal")

    assert out["reason"] == "no_progress" and len(out["steps"]) == 3
    assert all(s["page_changed"] for s in out["steps"])


def test_different_actions_that_change_the_page_keep_going(monkeypatch):
    page = FakePage([make_state(marker=str(i), text=f"page {i}") for i in range(6)])
    script(monkeypatch, [decision("e2", "CLICK"), decision("e1", "TYPE_TEXT"), decision("e2", "CLICK"),
                         decision("DONE")], texts=["x"])

    assert loop.run_task(page, "goal")["status"] == "done"


def test_step_budget_pauses(monkeypatch):
    page = FakePage([make_state(marker=str(i)) for i in range(5)])
    script(monkeypatch, [decision("e2", "CLICK")] * 5)

    out = loop.run_task(page, "goal", max_steps=2)

    assert out["reason"] == "step_budget" and len(out["steps"]) == 2


def test_stale_page_is_observed_again_then_retried(monkeypatch):
    page = FakePage([make_state(marker="a"), make_state(marker="b")])
    calls = {"n": 0}

    def act(action, state, text=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StalePage("moved")
        page.acted.append((action["id"], text))

    page.act = act
    script(monkeypatch, [decision("e2", "CLICK"), decision("e2", "CLICK"), decision("DONE")])

    out = loop.run_task(page, "goal")

    assert out["status"] == "done" and page.acted == [("e2", None)]


def test_endlessly_stale_page_stops_with_an_error(monkeypatch):
    page = FakePage([make_state()])

    def act(action, state, text=None):
        raise StalePage("moved")

    page.act = act
    script(monkeypatch, [decision("e2", "CLICK")] * (loop.MAX_STALE + 1))

    out = loop.run_task(page, "goal")

    assert out["status"] == "error" and "kept changing" in out["reason"]


def test_stale_page_at_a_stop_choice_is_rechecked(monkeypatch):
    page = FakePage([make_state(marker="a"), make_state(marker="b")])
    freshness = iter([False, True, True])
    page.fresh = lambda state, action=None: next(freshness)
    script(monkeypatch, [decision("DONE"), decision("DONE")])

    out = loop.run_task(page, "goal")

    assert out["status"] == "done" and out["jev_calls"] == 2


def test_guard_stops_before_any_decision(monkeypatch):
    page = FakePage([make_state()])
    script(monkeypatch, [])

    out = loop.run_task(page, "goal", guard=lambda url: "Blocked: private address")

    assert out["status"] == "error" and out["reason"] == "Blocked: private address"
    assert out["jev_calls"] == 0 and "text" not in out


def test_a_page_the_guard_blocks_after_a_click_returns_no_content(monkeypatch):
    page = FakePage([make_state(marker="a"), make_state(url="http://10.0.0.1/admin", text="secret", marker="b")])
    script(monkeypatch, [decision("e2", "CLICK")])

    out = loop.run_task(page, "goal", guard=lambda url: "Blocked: private address" if "10.0.0.1" in url else None)

    assert out["status"] == "error" and out["jev_calls"] == 1
    assert "text" not in out and "url" not in out and "elements" not in out


def test_the_guard_judges_each_page_that_was_read_once(monkeypatch):
    urls = ["https://a.test/", "https://a.test/next", "https://b.test/"]
    page = FakePage([make_state(url=u, marker=u) for u in urls])
    seen = []
    script(monkeypatch, [decision("e2", "CLICK"), decision("e2", "CLICK"), decision("DONE")])

    out = loop.run_task(page, "goal", guard=lambda url: seen.append(url))

    assert out["status"] == "done" and seen == urls


def test_a_redirect_between_steps_is_caught_on_the_page_actually_read(monkeypatch):
    # The page read after the click is private: Jev must never see it.
    page = FakePage([make_state(marker="a"), make_state(url="http://169.254.169.254/", text="creds", marker="b")])
    sent = []

    def choose(state, goal, history):
        sent.append(state["url"])
        return decision("e2", "CLICK")

    monkeypatch.setattr(loop, "choose", choose)
    out = loop.run_task(page, "goal", guard=lambda url: "Blocked" if "169.254" in url else None)

    assert sent == ["https://example.test/"] and out["status"] == "error" and "text" not in out


@pytest.mark.parametrize("failure", [ModelError("no key"), CamofoxError("down")])
def test_model_and_browser_failures_become_error_results(monkeypatch, failure):
    page = FakePage([make_state()])
    script(monkeypatch, [failure])

    out = loop.run_task(page, "goal")

    assert out["status"] == "error" and out["reason"] == str(failure)


def test_page_that_never_settles_is_an_error_not_an_exception(monkeypatch):
    page = FakePage([make_state()])

    def observe():
        raise StalePage("Page did not settle")

    page.observe = observe
    script(monkeypatch, [])

    out = loop.run_task(page, "goal")

    assert out["status"] == "error" and "url" not in out


def test_history_from_earlier_calls_reaches_jev(monkeypatch):
    page = FakePage([make_state()])
    earlier = [{"action": "Search", "kind": "fill", "text": "x", "page_changed": True}]
    seen = script(monkeypatch, [decision("DONE")])

    loop.run_task(page, "goal", history=earlier)

    assert seen[0] == earlier


def test_long_text_and_element_tables_are_capped(monkeypatch):
    actions = [{"id": f"e{i}", "kind": "click", "node": i, "label": f"L{i}"} for i in range(1, 200)]
    page = FakePage([make_state(text="x" * 20000, actions=actions)])
    script(monkeypatch, [decision("BLOCKED")])

    out = loop.run_task(page, "goal")

    assert len(out["text"]) == loop.TEXT_LIMIT and len(out["elements"]) == loop.ELEMENT_LIMIT


def test_results_report_the_last_goal_check(monkeypatch):
    page = FakePage([make_state()])
    script(monkeypatch, [{**decision("DONE"), "completion_probability": 0.97, "goal_check": "met"}])

    out = loop.run_task(page, "goal")

    assert out["status"] == "done" and out["completion_probability"] == 0.97 and out["done_by"] == "goal_check"
