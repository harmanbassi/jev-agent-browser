import json
import shutil
import subprocess
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jev_browser import camofox, loop
from jev_browser.camofox import Camofox, CamofoxError, Page, StalePage

from helpers import decision, make_state


class Stub:
    """A local HTTP server standing in for Camofox: records requests, replies from a script."""

    def __init__(self):
        self.requests, self.replies = [], []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                stub.requests.append((self.command, self.path, body, self.headers.get("Authorization")))
                status, payload = stub.replies.pop(0) if stub.replies else (200, {"ok": True})
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_POST = do_DELETE = do_GET = _reply

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.server.shutdown()


def test_evaluate_sends_user_expression_and_auth(stub):
    stub.replies = [(200, {"ok": True, "result": 42})]
    cf = Camofox(stub.url, "u1", "t1", headers={"Authorization": "Bearer k"})
    assert cf.evaluate("6*7") == 42
    assert stub.requests == [("POST", "/tabs/t1/evaluate", {"userId": "u1", "expression": "6*7"}, "Bearer k")]


@pytest.mark.parametrize("status", [409, 422, 500])
def test_changed_page_statuses_become_stale(stub, status):
    stub.replies = [(status, {"error": "x"})]
    with pytest.raises(StalePage):
        Camofox(stub.url, "u", "t").evaluate("1")


def test_other_errors_are_camofox_errors(stub):
    stub.replies = [(404, {"error": "tab not found"})]
    with pytest.raises(CamofoxError, match="404"):
        Camofox(stub.url, "u", "t").evaluate("1")


def test_non_evaluate_server_errors_are_not_mistaken_for_stale(stub):
    stub.replies = [(500, {"error": "boom"})]
    with pytest.raises(CamofoxError, match="500"):
        Camofox(stub.url, "u", "t").click("#x")


def test_non_json_replies_are_camofox_errors(stub):
    stub.replies = [(200, b"<html>proxy error</html>")]
    with pytest.raises(CamofoxError, match="non-JSON"):
        Camofox(stub.url, "u", "t").click("#a")


@pytest.mark.parametrize("reply", [(200, ["no", "result"]), (200, {"ok": True})])
def test_malformed_evaluate_replies_are_camofox_errors(stub, reply):
    stub.replies = [reply]
    with pytest.raises(CamofoxError, match="no result"):
        Camofox(stub.url, "u", "t").evaluate("1")


def test_unreachable_camofox_is_a_camofox_error():
    with pytest.raises(CamofoxError, match="unreachable"):
        Camofox("http://127.0.0.1:9", "u", "t", timeout=2).evaluate("1")


def test_input_routes_and_their_bodies(stub):
    cf = Camofox(stub.url, "u", "t")
    cf.click("#a")
    cf.press("Control+a")
    cf.type_text("hi")
    cf.scroll(-560)
    cf.viewport(1120, 780)
    assert [(p, b) for _, p, b, _ in stub.requests] == [
        ("/tabs/t/click", {"userId": "u", "selector": "#a"}),
        ("/tabs/t/press", {"userId": "u", "key": "Control+a"}),
        ("/tabs/t/type", {"userId": "u", "text": "hi", "mode": "keyboard", "delay": 0}),
        ("/tabs/t/scroll", {"userId": "u", "direction": "up", "amount": 560}),
        ("/tabs/t/viewport", {"userId": "u", "width": 1120, "height": 780}),
    ]


@pytest.mark.parametrize("timeout, resize_timeout", [(60, 5), (2, 2)])
def test_resize_timeout_continues_the_task_on_the_same_tab(stub, monkeypatch, caplog, timeout, resize_timeout):
    request = camofox.requests.request
    resizes = []

    def stalled_resize(method, url, **kw):
        if url.endswith("/viewport"):
            resizes.append(kw["timeout"])
            raise camofox.requests.ReadTimeout("resize acknowledgement stalled")
        return request(method, url, **kw)

    monkeypatch.setattr(camofox.requests, "request", stalled_resize)
    monkeypatch.setattr(loop, "choose", lambda state, goal, history: decision("DONE"))
    state = make_state()
    stub.replies = [(200, {"result": state}), (200, {"result": state["marker"]}), (200, {"result": state})]
    page = Page(Camofox(stub.url, "u", "t", timeout=timeout))

    out = loop.run_task(page, "Read this page")
    assert out["status"] == "done" and out["jev_calls"] == 1 and out["text"] == state["text"]
    assert page.observe()["marker"] == state["marker"]
    assert resizes == [resize_timeout]  # no repeated pending resizes on the tab
    assert "continuing with the current viewport" in caplog.text
    assert all(path == "/tabs/t/evaluate" for _, path, _, _ in stub.requests)


def test_resize_server_error_is_still_reported(stub):
    stub.replies = [(500, {"error": "browser disconnected"})]
    out = loop.run_task(Page(Camofox(stub.url, "u", "t")), "Read this page")
    assert out["status"] == "error" and out["jev_calls"] == 0 and "HTTP 500" in out["reason"]


@pytest.mark.parametrize("operation", ["viewport", "evaluate"])
def test_connection_failure_is_not_ignored(monkeypatch, operation):
    def disconnected(*args, **kw):
        raise camofox.requests.ConnectionError("offline")

    monkeypatch.setattr(camofox.requests, "request", disconnected)
    with pytest.raises(CamofoxError, match="unreachable"):
        cf = Camofox("http://camofox.test", "u", "t")
        cf.viewport(1120, 780) if operation == "viewport" else cf.evaluate("1")


def test_evaluation_read_timeout_remains_a_task_error(monkeypatch):
    def stalled(method, url, **kw):
        if url.endswith("/evaluate"):
            raise camofox.requests.ReadTimeout("evaluation stalled")
        return types.SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(camofox.requests, "request", stalled)
    out = loop.run_task(Page(Camofox("http://camofox.test", "u", "t")), "Read this page")
    assert out["status"] == "error" and out["jev_calls"] == 0 and "/tabs/t/evaluate" in out["reason"]


def test_the_lean_click_is_opt_in(stub, monkeypatch):
    monkeypatch.delenv("JEV_FAST_CLICK", raising=False)
    Camofox(stub.url, "u", "t").click_at(1, 2, "#a")
    assert [p for _, p, _, _ in stub.requests] == ["/tabs/t/click"]


def test_click_at_uses_the_jev_input_plugin(stub, monkeypatch):
    monkeypatch.setenv("JEV_FAST_CLICK", "1")
    Camofox(stub.url, "u", "t").click_at(10.5, 20, "#fallback")
    assert [(p, b) for _, p, b, _ in stub.requests] == [("/tabs/t/jev-click", {"userId": "u", "x": 10.5, "y": 20})]


def test_click_at_falls_back_to_the_selector_click_without_the_plugin_and_remembers(stub, monkeypatch):
    monkeypatch.setenv("JEV_FAST_CLICK", "1")
    cf = Camofox(stub.url, "u", "t")
    stub.replies = [(404, b"<pre>Cannot POST /tabs/t/jev-click</pre>"), (200, {"ok": True}), (200, {"ok": True})]
    cf.click_at(1, 2, "#a")
    cf.click_at(3, 4, "#b")
    assert [p for _, p, _, _ in stub.requests] == ["/tabs/t/jev-click", "/tabs/t/click", "/tabs/t/click"]
    assert cf.fast_click is False


def test_click_at_a_real_plugin_error_is_not_a_fallback(stub, monkeypatch):
    monkeypatch.setenv("JEV_FAST_CLICK", "1")
    stub.replies = [(404, {"error": "tab not found"})]
    with pytest.raises(CamofoxError, match="404"):
        Camofox(stub.url, "u", "t").click_at(1, 2, "#a")


def test_open_creates_a_tab_and_close_deletes_it(stub):
    stub.replies = [(200, {"tabId": "new"}), (500, {"error": "gone"})]
    cf = Camofox.open(stub.url, "u", "sk", "https://example.test/")
    assert cf.tab_id == "new"
    cf.close()  # a failed delete is swallowed; the idle reaper closes it
    assert stub.requests[0][1:3] == ("/tabs", {"userId": "u", "sessionKey": "sk", "url": "https://example.test/"})
    assert stub.requests[1][:2] == ("DELETE", "/tabs/new")
    assert cf.tab_id is None


class FakeCamofox:
    """Records calls; evaluate answers from a script keyed by what the expression is."""

    def __init__(self, target=None, fresh=True):
        target = {"x": 5, "y": 7} if target is None else target
        self.calls, self.target, self.is_fresh = [], target, fresh
        self.states = [make_state()]

    def evaluate(self, expression):
        if expression.startswith(camofox.TARGET_JS):
            self.calls.append(("target", json.loads(expression[len(camofox.TARGET_JS) + 1:-1])["id"]))
            return None if self.target == "covered" else self.target
        if expression.startswith(camofox.SETTLE_JS):
            self.calls.append(("settle",))
            return True
        if expression == camofox.MARKER:
            return self.states[0]["marker"] if self.is_fresh else "other"
        if expression == camofox.READ_STATE:
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return None if state is None else {k: v for k, v in state.items() if k != "fingerprint"}
        if "c.pageKey()" in expression:
            return [["k"], ["g2"]] if self.is_fresh else None
        raise AssertionError(expression[:40])

    def click(self, selector):
        self.calls.append(("click", selector))

    def click_at(self, x, y, selector):
        self.calls.append(("click_at", x, y, selector))

    def press(self, key):
        self.calls.append(("press", key))

    def type_text(self, text):
        self.calls.append(("type", text))

    def scroll(self, delta):
        self.calls.append(("scroll", delta))

    def viewport(self, width, height):
        self.viewport_size = (width, height)


def action(state, id_):
    return next(a for a in state["actions"] if a["id"] == id_)


def test_page_sets_upstreams_viewport_on_first_observe_only():
    cf = FakeCamofox()
    page = Page(cf)
    assert not hasattr(cf, "viewport_size")  # no I/O outside the loop's error handling
    page.observe()
    assert cf.viewport_size == camofox.VIEWPORT == (1120, 780)
    cf.viewport_size = None
    page.observe()
    assert cf.viewport_size is None


def test_fill_clicks_the_checked_node_selects_all_and_types():
    cf, state = FakeCamofox(), make_state()
    Page(cf).act(action(state, "e1"), state, text="gödel")
    assert cf.calls == [
        ("target", "e1"), ("click_at", 5, 7, camofox.TARGET_SELECTOR), ("press", "Control+a"), ("type", "gödel"),
    ]


def test_click_checks_the_node_guard_then_clicks():
    cf, state = FakeCamofox(), make_state()
    Page(cf).act(action(state, "e2"), state)
    assert cf.calls == [("target", "e2"), ("click_at", 5, 7, camofox.TARGET_SELECTOR)]


def test_select_is_done_inside_the_target_check():
    cf = FakeCamofox(target="selected")
    sel = {"id": "e3", "kind": "select", "node": 2, "label": "Class → Economy", "value": "eco"}
    state = make_state(actions=[sel])
    Page(cf).act(sel, state)
    assert cf.calls == [("target", "e3")]


def test_covered_or_changed_target_is_stale():
    cf, state = FakeCamofox(target="covered"), make_state()
    with pytest.raises(StalePage, match="covered"):
        Page(cf).act(action(state, "e2"), state)
    assert all(c[0] == "target" for c in cf.calls)


def test_changed_guard_is_stale_before_any_input():
    cf, state = FakeCamofox(fresh=False), make_state()
    with pytest.raises(StalePage):
        Page(cf).act(action(state, "e2"), state)
    assert cf.calls == []


def test_scroll_and_wait_need_no_target():
    cf, state, slept = FakeCamofox(), make_state(), []
    Page(cf, sleep=slept.append).act({"id": "wait", "kind": "wait"}, state)
    Page(cf).act({"id": "scroll_down", "kind": "scroll", "delta": 560}, state)
    assert cf.calls == [("scroll", 560)] and slept == [0.1]


def test_invalid_node_is_refused():
    cf, state = FakeCamofox(), make_state()
    with pytest.raises(ValueError):
        Page(cf).act({"id": "e9", "kind": "fill", "node": "#x"}, state)


def test_observe_settles_after_input_and_fingerprints():
    cf, state = FakeCamofox(), make_state()
    page = Page(cf)
    page.act(action(state, "e2"), state)
    observed = page.observe()
    assert ("settle",) in cf.calls
    assert observed["fingerprint"] == state["fingerprint"]


def test_observe_retries_while_the_document_is_navigating():
    cf, slept = FakeCamofox(), []
    cf.states = [None, None, make_state()]
    assert Page(cf, sleep=slept.append).observe()["url"] == "https://example.test/"
    assert slept == [0.05, 0.05]


def test_observe_gives_up_on_a_page_that_never_settles():
    cf = FakeCamofox()
    cf.states = [None]
    with pytest.raises(StalePage, match="did not settle"):
        Page(cf, sleep=lambda s: None).observe()


def test_fresh_compares_marker_for_pages_and_guards_for_clicks():
    cf, state = FakeCamofox(), make_state()
    page = Page(cf)
    assert page.fresh(state) is True
    assert page.fresh(state, action(state, "e2")) is True
    assert page.fresh(state, {"kind": "click", "node": "x"}) is False
    cf.is_fresh = False
    assert page.fresh(state) is False


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("name", ["READ_STATE", "MARKER", "TARGET_JS", "SETTLE_JS"])
def test_page_scripts_are_valid_javascript(tmp_path, name):
    source = getattr(camofox, name)
    if name in {"TARGET_JS", "SETTLE_JS"}:
        source += '({"id":"e1","kind":"click","node":1})'
    path = tmp_path / f"{name}.js"
    path.write_text(source)
    subprocess.run(["node", "--check", str(path)], check=True, capture_output=True)


@pytest.mark.parametrize("code", ["tab_timeout", "tab_destroyed", "browser_restarted"])
def test_a_destroyed_tab_is_reported_as_gone(stub, code):
    stub.replies = [(410, {"error": "Tab was destroyed. Open a new tab.", "code": code})]
    with pytest.raises(camofox.TabGone, match="HTTP 410"):
        Camofox(stub.url, "u", "t").click("[data-jev-target]")


def test_reopen_replaces_the_tab_in_the_same_identity(stub):
    stub.replies = [(200, {"tabId": "t1"}), (200, {"tabId": "t2"})]
    cf = Camofox.open(stub.url, "own", "session-1", "https://a.test/")
    page = Page(cf)
    page.sized, page.after_input = True, {"kind": "click"}
    assert page.recover("https://a.test/form", lambda url: None)
    assert cf.tab_id == "t2" and not page.sized and page.after_input is None
    assert stub.requests[1][1:3] == ("/tabs", {"userId": "own", "sessionKey": "session-1", "url": "https://a.test/form"})
    with pytest.raises(CamofoxError, match="Blocked"):
        page.recover("http://10.0.0.1/", lambda url: "Blocked: private")
    assert len(stub.requests) == 2 and cf.tab_id == "t2"


def test_a_tab_this_client_did_not_open_is_not_reopened(stub):
    assert Page(Camofox(stub.url, "shared", "their-tab")).recover("https://a.test/", lambda url: None) is False
    assert stub.requests == []


def test_a_supervisor_key_press_needs_a_fresh_page_and_settles_before_the_next_read():
    cf, state = FakeCamofox(), make_state()
    page = Page(cf)
    page.press("ArrowDown", state)
    page.observe()
    assert cf.calls[0] == ("press", "ArrowDown") and ("settle",) in cf.calls
    with pytest.raises(StalePage):
        Page(FakeCamofox(fresh=False)).press("Enter", state)



def test_a_rejected_input_after_the_target_check_is_uncertain_not_stale():
    cf, state = FakeCamofox(), make_state()

    def abandoned(x, y, selector):  # e.g. the click navigated, then the server's fallbacks gave up
        raise StalePage("/tabs/t/click: page changed (HTTP 422)")

    cf.click_at = abandoned
    page = Page(cf)
    with pytest.raises(camofox.ActionUncertain):
        page.act(action(state, "e2"), state)
    assert page.after_input is not None  # the next read still settles
    with pytest.raises(StalePage) as refused:  # a target check that fails before input stays plain stale
        Page(FakeCamofox(target="covered")).act(action(state, "e2"), state)
    assert not isinstance(refused.value, camofox.ActionUncertain)


def test_downloads_are_listed_without_file_data(stub):
    stub.replies = [(200, {"tabId": "t", "downloads": [{"id": "d1", "suggestedFilename": "setup.exe"}, "junk"]})]
    assert Camofox(stub.url, "u 1", "t").downloads() == [{"id": "d1", "suggestedFilename": "setup.exe"}]
    assert stub.requests[0][:2] == ("GET", "/tabs/t/downloads?userId=u%201")
    stub.replies = [(200, {"tabId": "t"})]
    with pytest.raises(CamofoxError, match="malformed"):
        Camofox(stub.url, "u", "t").downloads()


def test_a_click_reports_only_downloads_it_started():
    cf, state = FakeCamofox(), make_state()
    both = [{"id": "old", "suggestedFilename": "earlier.pdf"}, {"id": "new", "suggestedFilename": "setup.exe"}]
    listings = iter([[{"id": "old", "suggestedFilename": "earlier.pdf"}],
                     [{"id": "old", "suggestedFilename": "earlier.pdf"}], both, both])
    cf.downloads = lambda: next(listings)
    page = Page(cf, sleep=lambda s: None)
    page.act(action(state, "e2"), state)  # the baseline is taken before the first click
    assert page.new_downloads() == ["setup.exe"] and page.new_downloads(wait=0) == []


def test_download_detection_is_skipped_where_the_server_has_no_route():
    cf, state = FakeCamofox(), make_state()

    def missing():
        raise CamofoxError("Camofox /tabs/t/downloads returned HTTP 404")

    cf.downloads = missing
    page = Page(cf, sleep=lambda s: pytest.fail("no polling without a baseline"))
    page.act(action(state, "e2"), state)
    assert page.new_downloads() == []


def test_settle_waits_for_a_toggled_control_to_change_state():
    assert "aria-expanded" in camofox.SETTLE_JS and "action.expanded" in camofox.SETTLE_JS


def test_a_failed_download_is_not_reported_as_started():
    cf, state = FakeCamofox(), make_state()
    listings = iter([[], [{"id": "d1", "suggestedFilename": "setup.exe", "failure": "canceled"}]])
    cf.downloads = lambda: next(listings)
    page = Page(cf, sleep=lambda s: None)
    page.act(action(state, "e2"), state)
    assert page.new_downloads(wait=0) == []


@pytest.mark.parametrize("input_type", ["date", "time", "datetime-local", "month", "week"])
def test_date_and_time_fields_are_filled_in_their_value_format(input_type):
    cf, state = FakeCamofox(), make_state()
    fills = []
    cf.fill = lambda selector, text: fills.append((selector, text))
    target = {**action(state, "e1"), "input_type": input_type}
    Page(cf).act(target, state, text="19:30")
    assert fills == [(camofox.TARGET_SELECTOR, "19:30")]
    assert not any(call[0] in {"click_at", "type", "press"} for call in cf.calls)


@pytest.mark.parametrize("input_type", ["color", "range"])
def test_color_and_range_values_are_set_inside_the_target_check(input_type):
    cf, state = FakeCamofox(target="selected"), make_state()
    target = {**action(state, "e1"), "input_type": input_type}
    Page(cf).act(target, state, text="#ff0000")
    assert ("target", "e1") in cf.calls and not any(call[0] in {"click_at", "type"} for call in cf.calls)
    assert "action.text" in camofox.TARGET_JS


def test_a_target_replaced_before_delivery_is_stale_not_uncertain(stub):
    stub.replies = [(409, {"error": "Click target was replaced before the click was delivered.", "code": "target_replaced"})]
    with pytest.raises(StalePage) as stale:
        Camofox(stub.url, "u", "t").click("[data-jev-target]")
    assert isinstance(stale.value, camofox.TargetReplaced)
    cf, state = FakeCamofox(), make_state()

    def replaced(x, y, selector):
        raise camofox.TargetReplaced("/tabs/t/click: target replaced (HTTP 409)")

    cf.click_at = replaced
    with pytest.raises(StalePage) as refused:
        Page(cf).act(action(state, "e2"), state)
    assert not isinstance(refused.value, camofox.ActionUncertain)


def test_a_download_credited_while_in_progress_is_withdrawn_when_it_fails():
    cf, state = FakeCamofox(), make_state()
    started = {"id": "d1", "suggestedFilename": "source.tar.xz", "failure": None, "state": "in_progress"}
    listings = iter([[], [started], [{**started, "failure": "canceled", "state": "failed"}]])
    cf.downloads = lambda: next(listings)
    page = Page(cf, sleep=lambda s: None)
    page.act(action(state, "e2"), state)
    assert page.new_downloads(wait=0) == ["source.tar.xz"]  # in progress counts as started
    assert page.failed_downloads() == ["source.tar.xz"]
