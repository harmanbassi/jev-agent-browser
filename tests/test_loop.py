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
    script(monkeypatch, [{**decision("DONE"), "completion_probability": 0.97}])

    out = loop.run_task(page, "goal")

    assert out["status"] == "done" and out["completion_probability"] == 0.97 and "done_by" not in out


def test_duplicate_links_no_longer_split_the_target_below_the_floor(monkeypatch):
    from test_jev import duplicates, split_reply
    from jev_browser import jev
    before = duplicates(("Comments", "item?id=1", "link"), ("Hide", "hide?id=1", "link"),
                        ("Comments", "item?id=1", "link"))
    page = FakePage([before, make_state(marker="after")])
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "test-key")
    monkeypatch.setattr(jev, "post_json", split_reply({"1": 0.45, "2": 0.1, "3": 0.45}, "1"))

    out = loop.run_task(page, "open the comments", max_steps=1)

    assert page.acted == [("e1", None)] and out["reason"] == "step_budget"


def test_each_step_records_the_page_it_ran_on_and_the_page_it_led_to(monkeypatch):
    page = FakePage([make_state(url="https://a.test/", marker="a"), make_state(url="https://a.test/item", marker="b")])
    seen = script(monkeypatch, [decision("e2", "CLICK"), decision("DONE")])

    out = loop.run_task(page, "goal")

    assert out["steps"][0]["from_url"] == "https://a.test/" and out["steps"][0]["url_after"] == "https://a.test/item"
    assert seen[1][0]["from_url"] == "https://a.test/" and seen[1][0]["url_after"] == "https://a.test/item"


def test_a_blocked_destination_is_never_recorded_in_steps(monkeypatch):
    page = FakePage([make_state(marker="a"), make_state(url="http://10.0.0.1/admin", marker="b")])
    script(monkeypatch, [decision("e2", "CLICK")])

    out = loop.run_task(page, "goal", guard=lambda url: "Blocked" if "10.0.0.1" in url else None)

    assert out["status"] == "error" and "10.0.0.1" not in str(out)


SCROLL = [{"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560}]


def test_scrolling_through_a_changing_page_is_progress(monkeypatch):
    page = FakePage([make_state(marker=str(i), text=f"section {i}", actions=SCROLL) for i in range(6)])
    script(monkeypatch, [decision("scroll_down", "SCROLL")] * 4 + [decision("DONE")])

    out = loop.run_task(page, "scroll to the references")

    assert out["status"] == "done" and len(out["steps"]) == 4


def test_scrolling_without_change_or_past_the_step_budget_still_pauses(monkeypatch):
    page = FakePage([make_state(actions=SCROLL)])
    script(monkeypatch, [decision("scroll_down", "SCROLL")] * 3)
    assert loop.run_task(page, "goal")["reason"] == "no_progress"

    endless = FakePage([make_state(marker=str(i), text=f"feed {i}", actions=SCROLL) for i in range(30)])
    script(monkeypatch, [decision("scroll_down", "SCROLL")] * 30)
    out = loop.run_task(endless, "goal", max_steps=12)
    assert out["reason"] == "step_budget" and len(out["steps"]) == 12


def test_results_report_token_usage_next_to_call_counts(monkeypatch):
    from jev_browser.budget import current
    page = FakePage([make_state()])

    def choose(state, goal, history):
        current.get().record("typesafe/jev-1.13", {"input_tokens": 900, "output_tokens": 40})
        return decision("DONE")

    monkeypatch.setattr(loop, "choose", choose)
    out = loop.run_task(page, "goal")

    assert out["usage"] == {"input_tokens": 900, "output_tokens": 40,
                            "by_model": {"typesafe/jev-1.13": {"input_tokens": 900, "output_tokens": 40}}}


class Recoverable(FakePage):
    """The browser destroys the tab during a freshness read, an action, or the read after it."""

    def __init__(self, states, gone=1, owned=True, during="fresh"):
        super().__init__(states)
        self.gone, self.owned, self.during, self.reopened, self.observed = gone, owned, during, [], 0

    def lose(self, phase):
        from jev_browser.camofox import TabGone
        if self.during == phase and self.gone:
            self.gone -= 1
            raise TabGone(f"Camofox /tabs/t/{phase} returned HTTP 410")

    def fresh(self, page, action=None):
        self.lose("fresh")
        return True

    def observe(self):
        self.observed += 1
        if self.observed > 1:  # the read after an action
            self.lose("observe")
        return super().observe()

    def act(self, action, page, text=None):
        self.lose("act")
        super().act(action, page, text)

    def recover(self, url, guard):
        self.reopened.append((url, guard("https://a.test/form")))
        return self.owned


def test_a_tab_destroyed_during_a_read_reopens_the_latest_page_and_continues(monkeypatch):
    page = Recoverable([make_state(url="https://a.test/form", marker="a"),
                        make_state(url="https://a.test/sent", marker="b")])
    script(monkeypatch, [decision("e2", "CLICK"), decision("DONE")])

    out = loop.run_task(page, "goal")

    assert out["status"] == "done" and out["recoveries"] == 1
    assert page.reopened == [("https://a.test/sent", None)]  # never the form page the click left
    assert [s["kind"] for s in out["steps"]] == ["click", "recover"] and page.acted == [("e2", None)]


@pytest.mark.parametrize("during", ["act", "observe"])
def test_a_tab_destroyed_during_or_right_after_an_action_is_never_retried(monkeypatch, during):
    # The click may have submitted the form before the tab died: reopening and
    # deciding again could submit it twice.
    page = Recoverable([make_state(url="https://a.test/form", marker="a")], during=during)
    script(monkeypatch, [decision("e2", "CLICK"), decision("e2", "CLICK")])

    out = loop.run_task(page, "submit the form")

    assert out["status"] == "paused" and out["reason"] == "tab_lost" and out["url"] == "https://a.test/form"
    assert page.reopened == [] and "recoveries" not in out and "text" not in out
    assert out["steps"][-1]["action"] == "Go" and out["steps"][-1]["tab_lost"] is True
    assert len(out["steps"]) == 1


@pytest.mark.parametrize("gone, owned", [(9, True), (1, False)])
def test_tab_recovery_is_bounded_and_needs_an_owned_tab(monkeypatch, gone, owned):
    page = Recoverable([make_state(marker=str(i)) for i in range(9)], gone=gone, owned=owned)
    script(monkeypatch, [decision("e2", "CLICK")] * 9)

    out = loop.run_task(page, "goal")

    assert out["status"] == "error" and "HTTP 410" in out["reason"]
    assert out.get("recoveries", 0) == (loop.MAX_RECOVERIES if owned else 0)


def test_overruled_done_without_a_confident_alternative_says_why(monkeypatch):
    page = FakePage([make_state()])
    script(monkeypatch, [{**decision("e2", "CLICK", confidence=0.05), "goal_check": "unmet"}])

    out = loop.run_task(page, "goal")

    assert out["reason"] == "low_confidence" and "contradicted DONE" in out["detail"] and page.acted == []


def test_a_confident_goal_check_finishes_where_the_head_leaves_room(monkeypatch):
    page = FakePage([make_state()])
    script(monkeypatch, [{**decision("e2", "CLICK", confidence=0.6, target_confidence=0.9),
                          "completion_probability": 0.95, "done_probability": 0.3}])

    out = loop.run_task(page, "open the comments")

    assert out["status"] == "done" and out["done_by"] == "goal_check" and page.acted == []


def test_a_confident_action_is_taken_despite_a_confident_goal_check(monkeypatch):
    page = FakePage([make_state(marker="a"), make_state(marker="b")])
    script(monkeypatch, [{**decision("e2", "CLICK", confidence=0.9, target_confidence=0.9),
                          "completion_probability": 0.95, "done_probability": 0.05}, decision("DONE")])

    out = loop.run_task(page, "submit the form")

    assert page.acted == [("e2", None)] and out.get("done_by") is None


class Uncertain(FakePage):
    """The browser abandons the click after it may have reached the page."""

    def act(self, action, page, text=None):
        from jev_browser.camofox import ActionUncertain
        self.acted.append((action["id"], text))
        raise ActionUncertain("/tabs/t/click: page changed (HTTP 422)")


@pytest.mark.parametrize("after, effect", [
    (make_state(url="https://a.test/downloads/", marker="b"), "taken"),
    (make_state(url="https://a.test/", marker="b", text="same page, new banner"), "uncertain"),
])
def test_an_abandoned_click_is_still_recorded(monkeypatch, after, effect):
    page = Uncertain([make_state(url="https://a.test/", marker="a"), after])
    seen = script(monkeypatch, [decision("e2", "CLICK"), decision("DONE")])

    out = loop.run_task(page, "open the downloads page")

    step = out["steps"][0]
    assert step["effect"] == effect and step["url_after"] == after["url"]
    assert seen[1][0]["effect"] == effect  # Jev knows it clicked
    # DONE without a confident goal check is not accepted right after an uncertain click.
    assert out["status"] == ("done" if effect == "taken" else "paused")


class Downloading(FakePage):
    def __init__(self, states):
        super().__init__(states)
        self.files = []

    def act(self, action, page, text=None):
        super().act(action, page, text)
        self.files = ["python-3.15.1.exe"]

    def new_downloads(self):
        files, self.files = self.files, []
        return files


def test_a_click_that_starts_a_download_is_recorded_and_never_repeated(monkeypatch):
    page = Downloading([make_state(url="https://a.test/downloads/")])
    seen = script(monkeypatch, [decision("e2", "CLICK"), decision("e2", "CLICK")])

    out = loop.run_task(page, "open the latest release page")

    assert out["status"] == "paused" and out["reason"] == "download_started"
    assert out["downloads"] == ["python-3.15.1.exe"] and page.acted == [("e2", None)]
    assert out["steps"][0]["download"] == "python-3.15.1.exe" and seen[1][0]["download"] == "python-3.15.1.exe"


def test_a_download_that_lands_after_its_click_still_stops_a_repeat(monkeypatch):
    # A large file is listed only once saved, after the click's own short check.
    page = Downloading([make_state(url="https://a.test/downloads/")])
    checks = iter([[], ["python-3.15.1.tar.xz"]])
    page.new_downloads = lambda: next(checks)
    script(monkeypatch, [decision("e2", "CLICK"), decision("e2", "CLICK")])

    out = loop.run_task(page, "download the latest release")

    assert out["reason"] == "download_started" and page.acted == [("e2", None)]
    assert out["steps"][0]["download"] == "python-3.15.1.tar.xz"


def test_a_delivered_but_slow_submit_is_never_clicked_again(monkeypatch):
    # Without the image's slow-navigation fix the browser abandons the click after
    # ~12 s while the POST is still loading: same page, effect uncertain.
    page = Uncertain([make_state(url="https://a.test/form", marker="a")])
    script(monkeypatch, [decision("e2", "CLICK"), decision("e2", "CLICK")])

    out = loop.run_task(page, "submit the order")

    assert out["status"] == "paused" and out["reason"] == "action_uncertain"
    assert page.acted == [("e2", None)] and out["steps"][0]["effect"] == "uncertain"


def test_a_different_action_after_an_uncertain_one_proceeds(monkeypatch):
    page = Uncertain([make_state(url="https://a.test/form", marker="a")])
    script(monkeypatch, [decision("e2", "CLICK"), decision("e1", "TYPE_TEXT"), decision("DONE")], texts=["x"])

    out = loop.run_task(page, "fill and submit")

    assert page.acted == [("e2", None), ("e1", "x")]


def test_done_right_after_an_uncertain_step_needs_a_confident_goal_check(monkeypatch):
    # The destination option click was abandoned and the list stayed open: only the
    # origin is set, so the head's DONE must not end the task.
    page = Uncertain([make_state(url="https://a.test/flights", marker="a")])
    script(monkeypatch, [decision("e2", "CLICK"), {**decision("DONE"), "completion_probability": 0.69}])

    out = loop.run_task(page, "set origin Paris and destination London")

    assert out["status"] == "paused" and out["reason"] == "action_uncertain"


def test_done_after_an_uncertain_step_is_accepted_when_the_goal_check_confirms_it(monkeypatch):
    page = Uncertain([make_state(url="https://a.test/flights", marker="a")])
    script(monkeypatch, [decision("e2", "CLICK"), {**decision("DONE"), "completion_probability": 0.95}])

    assert loop.run_task(page, "set the destination")["status"] == "done"


def test_a_download_that_failed_after_being_credited_may_be_retried(monkeypatch):
    page = Downloading([make_state(url="https://a.test/downloads/")])
    page.failed_downloads = lambda: ["python-3.15.1.exe"]  # aborted after it was listed as started
    script(monkeypatch, [decision("e2", "CLICK"), decision("e2", "CLICK"), decision("DONE")])

    out = loop.run_task(page, "download the latest release")

    assert page.acted == [("e2", None), ("e2", None)] and out["status"] == "done"
    assert out["steps"][0]["download_failed"] == "python-3.15.1.exe" and "download" not in out["steps"][0]
