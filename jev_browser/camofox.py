"""Drive one Camofox tab for the Jev loop: observe, check freshness, act.

Replaces jev-ultrafast's CDP browser.py (browser-use/jev-ultrafast@1231850, MIT).
Camofox has no CDP, so the snapshot and target checks run through its
/evaluate route, and input goes through its /click, /press and /type routes:
real Playwright mouse and keyboard events inside the anti-detect browser.
The executor tags the checked node itself; model output never becomes a selector.
"""

import hashlib
import json
import logging
import time
from pathlib import Path

import requests

from .budget import current
from .policy import URLPolicy
from .environment import get

READ_STATE = Path(__file__).with_name("snapshot.js").read_text()
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"
TARGET_ATTR = "data-jev-target"
# Upstream's viewport. Load-bearing: at Camofox's default 2560x1384 a click on
# Google Flights' ticket-type control does not open its menu, so Jev clicks it
# forever (measured 2026-09-29; at 1120x780 the options appear at once).
VIEWPORT = (1120, 780)
VIEWPORT_TIMEOUT = 5
TARGET_SELECTOR = f'[{TARGET_ATTR}="1"]'

# The same checks as upstream's CDP executor. It returns the hit-tested click
# point (for the jev_input plugin's lean /jev-click) and also tags the node, so
# a Camofox without the plugin can click that node by selector instead.
TARGET_JS = """(action => {
  const e=window.__jevFast?.nodes.get(action.node);
  if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
      !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
  if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
  const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
  if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
  if (!e.contains(document.elementFromPoint(x,y))) return null;
  if (action.kind==='select') {
    if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
        !o.disabled && !o.closest('optgroup[disabled]'))) return null;
    e.value=action.value;
    e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));
    return 'selected';
  }
  document.querySelectorAll('[ATTR]').forEach(n=>n.removeAttribute('ATTR'));
  e.setAttribute('ATTR','1');
  return {x,y};
})""".replace("ATTR", TARGET_ATTR)

# Upstream's post-input wait: two animation frames or 50 ms, or until autocomplete
# options appear after typing into a combobox, search box or aria-autocomplete field
# (Wikipedia's is a searchbox whose suggestions take ~1 s). Upstream capped that at 200 ms on a
# direct connection; through the residential proxy Google's suggestions take
# longer, so a fast click reached the snapshot before them and Jev paused unsure
# (measured 2026-09-30). The wait still ends the moment options are visible.
AUTOCOMPLETE_WAIT_MS = 1500
SETTLE_JS = """(action => new Promise(resolve => {
  const field=window.__jevFast?.nodes.get(action.node);
  const autocomplete=action.kind==='fill' && !!field && (['combobox','searchbox'].includes(field.getAttribute('role'))
    || field.type==='search' || field.hasAttribute('aria-autocomplete'));
  let frames=0, stopped=false;
  const finish=()=>{stopped=true;resolve(true)};
  setTimeout(finish,autocomplete ? AUTOCOMPLETE_WAIT_MS : 50);
  const ready=()=>{
    if (stopped) return;
    const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
      .split(/\\s+/).filter(Boolean);
    const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
    const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
    if (++frames>=2 && (!autocomplete || options.some(e=>{
      const r=e.getBoundingClientRect();
      return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
        e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
    }))) finish();
    else requestAnimationFrame(ready);
  };
  requestAnimationFrame(ready);
}))""".replace("AUTOCOMPLETE_WAIT_MS", str(AUTOCOMPLETE_WAIT_MS))


class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class CamofoxError(RuntimeError):
    """Camofox is unreachable or refused a request for a reason other than a changed page."""


class CamofoxReadTimeout(CamofoxError):
    """A connected server did not finish the requested operation in time."""


class CamofoxAuthError(CamofoxError):
    """The browser rejected credentials or denied a protected operation."""


class Camofox:
    """REST client bound to one Camofox tab."""

    def __init__(self, base_url, user_id, tab_id, headers=None, timeout=60):
        self.base = base_url.rstrip("/")
        self.user_id = user_id
        self.tab_id = tab_id
        self.headers = headers or {}
        self.timeout = timeout
        # Lean /jev-click is opt-in (JEV_FAST_CLICK=1) until it matches the core click on
        # animated widgets: measured 2026-09-30, Google Flights' trip-type menu toggled
        # shut because the snapshot beat its opening animation.
        self.fast_click = get("JEV_FAST_CLICK") == "1"

    @classmethod
    def open(cls, base_url, user_id, session_key, url, headers=None, *, guard=None):
        """Create a new tab (for callers without their own tab management)."""
        if blocked := (URLPolicy() if guard is None else guard)(url):
            raise CamofoxError(blocked)
        client = cls(base_url, user_id, None, headers)
        reply = client._request("post", "/tabs", sessionKey=session_key, url=url)
        if not isinstance(reply, dict) or not isinstance(reply.get("tabId"), str) or not reply["tabId"]:
            raise CamofoxError("Camofox create-tab reply had no tabId")
        client.tab_id = reply["tabId"]
        return client

    def _request(self, method, path, *, request_timeout=None, reply_limit=None, **body):
        wait = self.timeout if request_timeout is None else request_timeout
        if budget := current.get():
            budget.check()
            wait = min(wait, max(0.001, budget.timeout - (time.monotonic() - budget.started)))
        try:
            response = requests.request(
                method, self.base + path, json={"userId": self.user_id, **body},
                headers=self.headers, timeout=wait, allow_redirects=False,
                **({"stream": True} if reply_limit else {}),
            )
        except requests.ReadTimeout as e:
            raise CamofoxReadTimeout(f"Camofox {path} timed out") from None
        except requests.RequestException as e:
            raise CamofoxError("Camofox unreachable (check CAMOFOX_URL and connectivity)") from None
        try:
            return self._reply(response, path, reply_limit)
        finally:
            if reply_limit:
                response.close()

    def _reply(self, response, path, reply_limit):
        if 300 <= response.status_code < 400:
            raise CamofoxError("Camofox control endpoint redirected; configure its final URL explicitly")
        if response.status_code in {409, 422}:
            raise StalePage(f"{path}: page changed (HTTP {response.status_code})")
        if response.status_code in {401, 403}:
            raise CamofoxAuthError(
                f"Camofox rejected browser authentication or permission (HTTP {response.status_code}); "
                "check CAMOFOX_ACCESS_KEY/CAMOFOX_API_KEY against the server configuration")
        if response.status_code >= 400:
            missing = " (Cannot POST)" if not reply_limit and response.status_code == 404 and "Cannot POST" in response.text else ""
            raise CamofoxError(f"Camofox {path} returned HTTP {response.status_code}{missing}")
        try:
            if reply_limit:
                data = bytearray()
                for chunk in response.iter_content(65536):
                    if budget := current.get():
                        budget.check()
                    data.extend(chunk)
                    if len(data) > reply_limit:
                        raise CamofoxError("Camofox observation exceeded the response limit")
                return json.loads(data)
            return response.json()
        except ValueError:
            raise CamofoxError(f"Camofox {path} returned a non-JSON reply") from None
        except requests.RequestException:
            raise CamofoxError("Camofox observation transfer failed") from None

    def _tab(self, action, **body):
        return self._request("post", f"/tabs/{self.tab_id}/{action}", **body)

    def evaluate(self, expression):
        try:
            reply = self._tab("evaluate", expression=expression)
        except CamofoxError as e:
            # A page navigating mid-evaluation surfaces as a 500 from Playwright.
            if "HTTP 5" in str(e):
                raise StalePage("Document changed during evaluation") from None
            raise
        if not isinstance(reply, dict) or "result" not in reply:
            raise CamofoxError("Camofox evaluate reply had no result")
        return reply["result"]

    def click(self, selector):
        self._tab("click", selector=selector)

    def click_at(self, x, y, selector):
        """Lean click at viewport coordinates via the jev_input plugin; the
        core selector click (~2 s: settle + ref rebuild) where it is absent."""
        if self.fast_click:
            try:
                self._tab("jev-click", x=x, y=y)
                return
            except CamofoxError as e:
                if "Cannot POST" not in str(e):  # a real error, not a missing route
                    raise
                self.fast_click = False
        self.click(selector)

    def press(self, key):
        self._tab("press", key=key)

    def type_text(self, text):
        # Types into whatever holds focus, like upstream's CDP Input.insertText.
        self._tab("type", text=text, mode="keyboard", delay=0)

    def scroll(self, delta):
        self._tab("scroll", direction="down" if delta > 0 else "up", amount=abs(delta))

    def viewport(self, width, height):
        # Firefox can stall the resize acknowledgement on a loading document even
        # while the tab remains readable. Do not abort Jev before its first decision
        # or issue another resize: snapshots and hit tests use the actual viewport,
        # and their markers detect a resize that finishes later.
        try:
            self._request("post", f"/tabs/{self.tab_id}/viewport", width=width, height=height,
                          request_timeout=min(self.timeout, VIEWPORT_TIMEOUT))
        except CamofoxReadTimeout:
            logging.getLogger(__name__).warning("Camofox resize timed out; continuing with the current viewport")
        except CamofoxError as error:
            # Some public images cannot resize because Playwright's protocol is
            # newer than Firefox's. A 5xx alone is not enough to ignore: prove
            # the page remains readable, otherwise preserve the original error.
            if "HTTP 5" not in str(error):
                raise
            try:
                actual = self.evaluate("({width:innerWidth,height:innerHeight})")
            except (CamofoxError, StalePage):
                raise error from None
            if not isinstance(actual, dict) or not all(type(actual.get(k)) is int and actual[k] > 0 for k in ("width", "height")):
                raise error
            logging.getLogger(__name__).warning("Camofox resize failed; verified readable page and continuing with the current viewport")

    def close(self):
        if self.tab_id:
            try:
                self._request("delete", f"/tabs/{self.tab_id}")
            except (CamofoxError, StalePage):
                pass  # the reaper closes idle tabs anyway
            self.tab_id = None

    def close_session(self):
        """Destroy an identity we own, including saved state. Never use on a shared Hermes identity."""
        self.close()
        self._request("delete", f"/sessions/{self.user_id}")
        try:
            self._request("delete", f"/sessions/{self.user_id}/storage_state")
        except CamofoxError as e:
            if "HTTP 403" in str(e):
                return False  # legacy servers may require a separate profile-reset key
            if "HTTP 404" not in str(e):  # persistence plugin is optional
                raise
        return True


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


class Page:
    """jev's browser interface (observe / fresh / act) over a Camofox tab."""

    def __init__(self, camofox, sleep=time.sleep):
        self.cf = camofox
        self.sleep = sleep
        self.after_input = None
        self.sized = False

    def observe(self):
        if not self.sized:  # first touch of the tab; inside the loop's error handling, not __init__
            self.cf.viewport(*VIEWPORT)
            self.sized = True
        if self.after_input:
            action, self.after_input = self.after_input, None
            try:
                self.cf.evaluate(SETTLE_JS + "(" + json.dumps(action) + ")")
            except StalePage:
                pass  # navigation interrupted the wait; the read below retries
        for _ in range(10):
            try:
                info = self.cf.evaluate(READ_STATE)
            except StalePage:
                info = None
            if info:
                if (not isinstance(info, dict) or not all(isinstance(info.get(k), str) for k in ("url", "title", "text"))
                        or not isinstance(info.get("actions"), list) or not isinstance(info.get("scroll"), dict)
                        or not all(isinstance(a, dict) and isinstance(a.get("id"), str)
                                   and a.get("kind") in {"click", "fill", "select", "scroll", "wait"} for a in info["actions"])
                        or not all(k in info for k in ("marker", "page_key", "guards"))):
                    raise CamofoxError("Camofox returned a malformed page snapshot")
                info["fingerprint"] = fingerprint(info)
                return info
            self.sleep(0.05)
        raise StalePage("Page did not settle")

    def observe_vision(self, expected_url, run):
        """Only the authenticated masked plugin may supply pixels to a model."""
        from .vision import Frame, MAX_REPLY_BYTES, VisionUnavailable

        run.capture()
        try:
            reply = self.cf._request("post", f"/tabs/{self.cf.tab_id}/jev-observation",
                                     expectedUrl=expected_url, snapshotHash=hashlib.sha256(READ_STATE.encode()).hexdigest(),
                                     request_timeout=10, reply_limit=MAX_REPLY_BYTES)
        except CamofoxAuthError:
            raise
        except CamofoxError as e:
            reason = "vision_capture_unavailable" if "HTTP 404" in str(e) else "vision_capture_failed"
            raise VisionUnavailable(reason) from None
        frame = Frame.decode(reply, hashlib.sha256(READ_STATE.encode()).hexdigest())
        if frame.state["url"] != expected_url:
            raise StalePage("Page changed during visual observation")
        frame.state["fingerprint"] = fingerprint(frame.state)
        return frame

    def fresh(self, page, action=None):
        if action is not None and action["kind"] in {"click", "select"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.cf.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.cf.evaluate(MARKER) == page["marker"]

    def press(self, key, page):
        """A key on whatever holds focus, if the page is still the one observed."""
        if not self.fresh(page):
            raise StalePage("Page changed since this decision. Observe again.")
        self.cf.press(key)
        self.after_input = None

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        kind = action["kind"]
        if kind == "wait":
            self.sleep(0.1)
        elif kind == "scroll":
            self.cf.scroll(action["delta"])
        else:
            if type(action.get("node")) is not int:
                raise ValueError("Invalid observed node")
            point = self.cf.evaluate(TARGET_JS + "(" + json.dumps(action) + ")")
            if point is None:
                raise StalePage("Target changed or is covered. Observe again.")
            if kind in {"click", "fill"}:
                self.cf.click_at(point["x"], point["y"], TARGET_SELECTOR)
            if kind == "fill":
                self.cf.press("Control+a")
                self.cf.type_text(text)
        self.after_input = action if kind != "wait" else None
