"""Standalone, process-local sessions. No Hermes imports or host proxy changes."""
from dataclasses import dataclass, field
import threading
import logging
import time
import uuid

from .budget import limits
from .camofox import Camofox, CamofoxError, Page, StalePage
from .config import Settings
from .jev import action_space, api_key
from .loop import run_task
from .vision import VisionSettings

# The supervisor path: an agent acts itself on observed element ids when Jev pauses.
# Values it types are never recorded in history, so they never reach the model.
SUPERVISOR_TEXT = "(entered by the supervising agent)"
OPERATIONS = {"click": "CLICK", "type": "TYPE_TEXT", "select": "SELECT"}
KEYS = {"Enter", "Tab", "Escape", "Backspace", "Space", "ArrowDown", "ArrowUp", "ArrowLeft",
        "ArrowRight", "Home", "End", "PageDown", "PageUp"}
OBSERVE_AGAIN = "The page changed since it was observed; call browser_snapshot and retry with current ids."
FALLBACKS = {
    "sensitive_action": "Jev never enters sensitive values or presses sign-in/payment controls. If the user "
                        "supplied the value and approved this step, do it yourself with browser_snapshot and "
                        "browser_act, then continue with browser_task.",
    "missing_value": "The goal does not supply this field's value. Ask the user, or type the value they gave "
                     "with browser_act, then continue with browser_task.",
    "tab_lost": "The browser closed the tab while the last step ran; it may already have taken effect (for "
                "example a submitted form). Check the result before repeating it: browser_task reopens the "
                "latest page in this session, or open the reported url in a new session.",
    "action_uncertain": "The browser gave up on the last step after sending it and the page has not changed "
                        "yet; it may already have taken effect (for example a slow form submission). Check with "
                        "browser_snapshot before repeating it.",
    "download_started": "A click started a file download (listed in downloads) and Jev will not repeat it. "
                        "If the goal was the file, it is done; otherwise give browser_task a goal that avoids "
                        "that link.",
}
CONTINUE = "Continue with browser_task (no new information needed) within a fresh budget."
BUDGETS = {"step_budget", "model_budget", "timeout", "vision_budget", "vision_capture_budget", "cancelled"}
INSPECT = ("Inspect the page with browser_snapshot. Give browser_task a clearer or smaller goal, or do the "
           "unclear step yourself with browser_act (for example ArrowDown then Enter in an autocomplete), "
           "then continue with browser_task.")


def error(message):
    return {"status": "error", "reason": message}


@dataclass
class Session:
    cf: Camofox
    page: Page
    history: list = field(default_factory=list)
    result: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    cancel: threading.Event = field(default_factory=threading.Event)
    touched: float = field(default_factory=time.monotonic)
    require_visual: bool = False
    observed: dict | None = None  # the observation a supervisor's element ids refer to


class Browser:
    """One owner per instance; session IDs are opaque capabilities, not shared logins.

    Use as a context manager. Each session has its own cookie identity. This
    client leaves existing Camofox instances, proxy settings and Hermes tabs alone.
    """
    def __init__(self, settings=None, *, max_sessions=16, idle_seconds=900):
        if type(max_sessions) is not int or not 1 <= max_sessions <= 64 or not 0 < idle_seconds <= 86400:
            raise ValueError("invalid session capacity or idle timeout")
        self.settings = settings or Settings.from_env()
        self.max_sessions, self.idle_seconds = max_sessions, idle_seconds
        self._sessions, self._lock, self._closed = {}, threading.RLock(), False
        self.cleanup_warnings = []

    def start(self, url, goal, *, max_steps=25, max_model_calls=100, timeout=300,
              vision=None, require_visual=None):
        try:
            limits(goal, max_steps, max_model_calls, timeout)
            VisionSettings.from_env().resolve(vision, False if require_visual is None else require_visual)
        except ValueError as e:
            return error(str(e))
        opened = self.open(url)
        if opened["status"] == "error":
            return opened
        return self.run(opened["session_id"], goal, max_steps=max_steps, max_model_calls=max_model_calls,
                        timeout=timeout, vision=vision, require_visual=require_visual)

    def open(self, url):
        """Open without executing model decisions; returns an ID usable for cancellation."""
        try:
            if not api_key():
                return error("Set JEV_OPENROUTER_KEY or OPENROUTER_API_KEY")
            if blocked := self.settings.policy(url):
                return error(blocked)
            with self._lock:
                self._reap()
                if self._closed or len(self._sessions) >= self.max_sessions:
                    return error("Browser is closed or session capacity reached; close an existing session")
                sid = uuid.uuid4().hex
                try:
                    cf = Camofox.open(self.settings.camofox_url, f"jev-{sid}", sid, url,
                                      headers=self.settings.headers, guard=self.settings.policy)
                except (ValueError, CamofoxError):
                    # Creation can allocate a context before navigation fails or
                    # its reply is lost. This random identity belongs only to us.
                    self._cleanup(Camofox(self.settings.camofox_url, f"jev-{sid}", None,
                                          headers=self.settings.headers))
                    raise
                self._sessions[sid] = Session(cf, Page(cf))
            return {"status": "ready", "session_id": sid}
        except (ValueError, CamofoxError) as e:
            return error(str(e))

    def _get(self, sid):
        if not isinstance(sid, str):
            return None
        with self._lock:
            session = self._sessions.get(sid)
            if session and time.monotonic() - session.touched > self.idle_seconds and not session.lock.locked():
                self.close(sid)
                return None
            return session

    def run(self, session_id, goal, *, max_steps=25, max_model_calls=100, timeout=300, cancel=None,
            vision=None, require_visual=None):
        with self._lock:
            session = self._get(session_id)
            if session is None:
                return error("Unknown or expired session")
            if not session.lock.acquire(blocking=False):
                return error("Session is busy; cancel it before starting another task")
            session.cancel = cancel if cancel is not None else threading.Event()
        try:
            required = session.require_visual if require_visual is None else require_visual
            try:
                VisionSettings.from_env().resolve(vision, required)
            except ValueError as e:
                return error(str(e))
            session.require_visual = required
            visual_options = {}
            if vision is not None or required:
                visual_options = {"vision": vision, "require_visual": required}
            session.observed = None
            out = run_task(session.page, goal, history=session.history, max_steps=max_steps,
                           max_model_calls=max_model_calls, timeout=timeout, cancel=session.cancel,
                           guard=self.settings.policy, **visual_options)
            if out.get("status") == "paused":
                reason = out.get("reason")
                out["fallback"] = FALLBACKS.get(reason) or (CONTINUE if reason in BUDGETS else INSPECT)
            session.history = (session.history + out.get("steps", []))[-10:]
            session.result = {**out, "session_id": session_id}
            return session.result
        finally:
            session.touched = time.monotonic()
            session.lock.release()
            if self._closed:
                self.close(session_id)

    def snapshot(self, session_id):
        """The current page and its element ids for a supervising agent; no model call."""
        session, failed = self._claim(session_id)
        if failed:
            return failed
        try:
            return self._observe(session_id, session, text=True)
        except (CamofoxError, StalePage, ValueError) as e:
            return error(str(e))
        finally:
            session.touched = time.monotonic()
            session.lock.release()

    def act(self, session_id, element_id, action, value=None):
        """Do one step for Jev on an element id from the latest snapshot/act result.

        The same executor checks as Jev's actions apply: the observation must still be
        current and the target must still be the observed, visible, uncovered control.
        Sensitive fields are allowed here: this is the supervisor's explicit path.
        """
        session, failed = self._claim(session_id)
        if failed:
            return failed
        try:
            state = session.observed
            if state is None:
                return error("Call browser_snapshot first; element ids refer to its observation.")
            target, text = self._target(state, element_id, action, value)
            if isinstance(target, str):
                return error(target)
            session.observed = None  # ids are single-use: the page is about to change
            try:
                if action == "press":
                    session.page.press(value, state)
                else:
                    session.page.act(target, state, text=text)
            except StalePage:
                return error(OBSERVE_AGAIN)
            step = {"action": target["label"] if target else value, "kind": target["kind"] if target else "press",
                    "from_url": state["url"], "text": SUPERVISOR_TEXT if text is not None else None}
            out = self._observe(session_id, session)
            step["page_changed"] = out.get("changed")
            if out["status"] == "ready":
                step["url_after"] = out["url"]
            session.history = (session.history + [step])[-10:]
            return out
        except (CamofoxError, StalePage, ValueError) as e:
            return error(str(e))
        finally:
            session.touched = time.monotonic()
            session.lock.release()

    def _claim(self, session_id):
        with self._lock:
            session = self._get(session_id)
            if session is None:
                return None, error("Unknown or expired session")
            if not session.lock.acquire(blocking=False):
                return None, error("Session is busy; wait for the task or cancel it first")
        return session, None

    def _observe(self, session_id, session, text=False):
        previous = session.observed
        state = session.page.observe()
        if blocked := self.settings.policy(state["url"]):
            return error(blocked)  # this page's content goes nowhere
        session.observed = state
        out = {"status": "ready", "session_id": session_id, "url": state["url"], "title": state["title"]}
        if text:
            out["text"] = state["text"]
        else:
            out["changed"] = previous is None or previous.get("fingerprint") != state.get("fingerprint")
        out["elements"] = action_space(state["actions"])[0]
        return out

    @staticmethod
    def _target(state, element_id, action, value):
        """(observed action, text to type) or an error message. Never a selector or script."""
        if action == "press":
            return None if value in KEYS else f"press needs one of: {', '.join(sorted(KEYS))}", None
        if action == "scroll":
            target = next((a for a in state["actions"] if a["id"] == f"scroll_{value}"), None)
            return target or "scroll needs value up or down, where the page can scroll that way", None
        if action not in OPERATIONS:
            return "action must be click, type, select, press or scroll", None
        targets = action_space(state["actions"])[1].get(OPERATIONS[action], {})
        if action == "select":
            target = next((a for index, a in targets.items() if index.split(":")[0] == element_id
                           and value in (a["value"], a["label"].split(" → ", 1)[-1])), None)
            return target or f"Element {element_id} has no option {value!r}", None
        target = targets.get(element_id) if isinstance(element_id, str) else None
        if target is None:
            return f"Element {element_id} cannot be used with {action}; use an id from the latest snapshot", None
        if action == "type":
            if not isinstance(value, str) or not value or len(value) > 2000:
                return "type needs a value of 1 to 2000 characters", None
            return target, value
        return target, None

    def inspect(self, session_id):
        session = self._get(session_id)
        if session is None:
            return error("Unknown or expired session")
        if session.lock.locked():
            return {"status": "running", "session_id": session_id}
        return dict(session.result)

    def cancel(self, session_id):
        with self._lock:
            session = self._get(session_id)
            if session is None:
                return error("Unknown or expired session")
            session.cancel.set()
        return {"status": "cancelling", "session_id": session_id}

    def close(self, session_id):
        with self._lock:
            if not isinstance(session_id, str):
                return error("Unknown or expired session")
            session = self._sessions.get(session_id)
            if session is None:
                return error("Unknown or expired session")
            session.cancel.set()
            if not session.lock.acquire(blocking=False):
                return error("Session is busy; cancellation requested; retry close after it stops")
            self._sessions.pop(session_id)
        try:
            cleaned, warning = self._cleanup(session.cf)
        finally:
            session.lock.release()
        if not cleaned:
            return error(warning)
        out = {"status": "closed", "session_id": session_id}
        if warning:
            out["warning"] = warning
        return out

    def _cleanup(self, cf):
        cleaned = True
        warning = None
        try:
            if cf.close_session() is False:
                warning = "Browser context closed; legacy server denied saved-profile reset. Configure browser authentication to permit cleanup."
        except (CamofoxError, ValueError):
            cleaned = False
            warning = "Session removed locally; browser cleanup failed; check server context and saved-profile cleanup"
        if warning:
            self.cleanup_warnings.append(warning)
            logging.getLogger(__name__).warning(warning)
        return cleaned, warning

    def _reap(self):
        for sid, session in list(self._sessions.items()):
            if time.monotonic() - session.touched > self.idle_seconds and not session.lock.locked():
                self.close(sid)

    def shutdown(self):
        with self._lock:
            self._closed = True
            sessions = list(self._sessions)
        for sid in sessions:
            self.close(sid)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown()
