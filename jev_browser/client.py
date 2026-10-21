"""Standalone, process-local sessions. No Hermes imports or host proxy changes."""
from dataclasses import dataclass, field
import threading
import logging
import time
import uuid

from .budget import limits
from .camofox import Camofox, CamofoxError, Page
from .config import Settings
from .jev import api_key
from .loop import run_task
from .vision import VisionSettings


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
            out = run_task(session.page, goal, history=session.history, max_steps=max_steps,
                           max_model_calls=max_model_calls, timeout=timeout, cancel=session.cancel,
                           guard=self.settings.policy, **visual_options)
            session.history = (session.history + out.get("steps", []))[-10:]
            session.result = {**out, "session_id": session_id}
            return session.result
        finally:
            session.touched = time.monotonic()
            session.lock.release()
            if self._closed:
                self.close(session_id)

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
