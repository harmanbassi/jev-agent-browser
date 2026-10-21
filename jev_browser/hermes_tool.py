"""browser_task: the Hermes tool. Jev drives the same Camofox tab the browser_* tools use.

Hermes internals are imported lazily (inside functions) so the core package
stays importable outside Hermes for standalone clients.
"""

import json
import os
import threading

from . import jev
from .camofox import Camofox, Page
from .loop import run_task
from .budget import limits
from . import environment
from .vision import VisionSettings

HISTORY_KEEP = 10
_history = {}  # (profile, browser, identity, tab, task) -> recent executed actions
_visual_requirements = {}
_tab_locks = {}
_registry_lock = threading.Lock()

BROWSING_INSTRUCTIONS = """For interactive web browsing, use browser_task (Jev) first.
Give it a concrete goal with the required values and visible completion condition.
For appearance, pictures, colors or layout requirements, set require_visual=true.
This requires operator-enabled masked vision; never substitute a DOM-only guess
when visual evidence is unavailable. Omitted visual requirements persist on resume.
Break comparisons across several pages into bounded browsing goals and inspect
the returned page text before drawing conclusions. Use a documented API or direct
data fetch when the user does not need browser interaction and no interaction is needed.

If browser_task is not directly listed, discover it with tool_search, inspect its
schema, and invoke it through the host's deferred-tool bridge. Do not switch to a
manual click/type loop just because browser_task is deferred.

browser_task shares the browser_* tab and identity. Omit url to continue from
the current page, including a follow-up that changes the user's requirements.
On paused, resolve the reported reason: clarify the goal, resume within a fresh
budget, or use manual browser controls for an unsupported step. On error, retry
once if appropriate, then use the manual fallback and report the limitation.
Use browser_snapshot/browser_vision for inspection and screenshots; browser_*
controls also handle unsupported iframes, uploads, popups and permitted login
steps. Computer-use skill examples showing manual DOM interaction are this
fallback, not the default while Jev is available. Never use Jev to sign in, pay,
enter personal details, or bypass a URL/sensitive-action block. Follow explicit
user choices about tools, authentication and consequential actions.
"""


def routing_guidance(_session_info):
    """Only advertise Jev in profiles that can actually use it; never include secrets."""
    return BROWSING_INSTRUCTIONS if check() else ""


SCHEMA = {
    "name": "browser_task",
    "description": (
        "The default way to browse. Give a URL and a plain-language goal; a fast decision model "
        "clicks, types and selects on the page until the goal is visibly met, then returns the "
        "final URL, title and visible page text. Much faster and cheaper than driving "
        "browser_click/browser_type yourself. Omit url to continue on the current page.\n"
        "Before browsing, check whether the data is readable without a browser: a documented API, "
        "a .json/.csv URL, or data embedded in the page's HTML (a <script type=\"application/ld+json\"> "
        "or __NEXT_DATA__ block). Fetching those directly (curl, or web_extract where allowed) is faster and more reliable; use "
        "browser_task when the page needs interaction. If the user's intent is unclear (which site, "
        "which dates, what counts as done), confirm it with them first.\n"
        "status 'paused' means it needs you: read `reason` and `elements`, look with browser_vision "
        "or browser_snapshot if needed, then call browser_task again (no url) with a clearer or "
        "smaller goal, do the step yourself with browser_click/browser_type, or ask the user. "
        "Use the browser_* tools directly for iframes, file uploads, pop-up windows and logins. "
        "Never use it to sign in, pay, or enter personal details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "What to achieve, with every value needed (dates, names, filters). "
                "Say what visible state means done.",
            },
            "url": {"type": "string", "description": "Page to start from. Omit to continue on the current tab."},
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 100,
                          "description": "Action budget before pausing (default 25)."},
            "max_model_calls": {"type": "integer", "minimum": 1, "maximum": 500,
                                "description": "Total model HTTP requests including retries (default 100)."},
            "timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": 900,
                        "description": "Cooperative task deadline in seconds (default 300)."},
            "vision": {"type": "string", "enum": ["off", "auto", "always"],
                       "description": "Visual mode, subject to operator opt-in."},
            "require_visual": {"type": "boolean", "description":
                               "Require image evidence for appearance/image goals. Persists on resume when omitted."},
        },
        "required": ["goal"],
    },
}

NEXT = {
    "done": (
        "Check that `text` answers the goal before relying on it. If you worked out a method from an "
        "example (a URL pattern, a filter, a selector), try it on one input that was not the example "
        "before reusing it."
    ),
    "paused": (
        "Jev handed control back. Resolve `reason`: call browser_task again without url and a clearer "
        "or smaller goal, act yourself with browser_click/browser_type on this same page "
        "(browser_vision shows it), or ask the user."
    ),
    "error": "Retry once; if it fails again, fall back to browser_navigate/browser_snapshot/browser_click.",
}


def _camofox():
    from tools import browser_camofox  # Hermes-only; resolved at call time

    return browser_camofox


def _browser_tool():
    from tools import browser_tool  # Hermes-only; resolved at call time

    return browser_tool


def url_block(url):
    """Why a read page's text must not leave the box, or None.

    Page text goes to OpenRouter, a third party, so this applies the rules
    browser_navigate applies to cloud (third-party) browser backends, to the
    URL of every page Jev reads: the metadata floor, private addresses unless
    browser.allow_private_urls, credential-like query parameters, website policy.
    """
    bt = _browser_tool()
    # Hermes split these helpers into sibling modules. Retain the old exports
    # when present so both deployed versions and existing integrations work.
    allow_private = getattr(bt, "_allow_private_urls", None)
    sensitive_query = getattr(bt, "_sensitive_query_param_name", None)
    try:
        if allow_private is None:
            from tools.browser_tool_cloud import _allow_private_urls as allow_private
        if sensitive_query is None:
            from tools.url_safety import sensitive_query_param_name as sensitive_query
    except ImportError:
        return "Blocked: unsupported Hermes URL-policy API; upgrade Hermes or use the standalone adapter."
    if bt._is_always_blocked_url(url):
        return "Blocked: page URL targets a cloud metadata endpoint."
    if not allow_private() and not bt._is_safe_url(url):
        return "Blocked: page is not a public web page; its text is not sent to Jev."
    if key := sensitive_query(url):
        return f"Blocked: page URL carries a credential-like query parameter ({key}); not sent to Jev."
    if policy := bt.check_website_access(url):
        return policy["message"]
    return None


def check():
    try:
        with environment.use(_environment_reader()):
            return _camofox().is_camofox_mode() and bool(jev.api_key())
    except Exception:
        return False


def _error(message):
    return json.dumps({"success": False, "status": "error", "error": message}, ensure_ascii=False)


def _environment_reader():
    try:
        from agent.secret_scope import get_secret  # New Hermes: profile-scoped credentials/settings.
    except ImportError:
        return os.environ.get  # Older Hermes still exports its .env into the process.
    return get_secret


def _profile_key():
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        return os.environ.get("HERMES_HOME", "")  # older hosts are single-profile
    return str(get_hermes_home())


def handle(args, **kw):
    with environment.use(_environment_reader()):
        try:
            if not jev.api_key():
                return _error("No OpenRouter key in the active Hermes profile")
            return _handle(args, **kw)
        except RuntimeError:
            # SecretScopeError fails closed in a multiplexed gateway with no
            # active profile scope. Do not expose the exception's private data.
            return _error("Hermes browser task failed; check the active profile's secret scope and browser configuration")


def _handle(args, **kw):
    # Serialize before navigation: adopted native tabs can be shared by task IDs.
    identity = _profile_key()
    with _registry_lock:
        lock, users = _tab_locks.get(identity, (threading.Lock(), 0))
        _tab_locks[identity] = (lock, users + 1)
    acquired = lock.acquire(blocking=False)
    try:
        if not acquired:
            return _error("Browser profile is busy; wait for the active task")
        return _handle_unlocked(args, **kw)
    finally:
        if acquired:
            lock.release()
        with _registry_lock:
            _, users = _tab_locks[identity]
            if users == 1:
                del _tab_locks[identity]
            else:
                _tab_locks[identity] = (lock, users - 1)


def _handle_unlocked(args, **kw):
    if not isinstance(args, dict):
        return _error("arguments must be an object")
    task_id = kw.get("task_id")
    goal = args.get("goal", "")
    max_steps = args.get("max_steps", 25)
    try:
        limits(goal, max_steps, args.get("max_model_calls", 100), args.get("timeout", 300))
        VisionSettings.from_env().resolve(args.get("vision"), args.get("require_visual", False))
    except ValueError as e:
        return _error(str(e))
    goal = goal.strip()
    url = args.get("url") or ""
    if not isinstance(url, str):
        return _error("url must be a string")
    url = url.strip()
    bc = _camofox()
    if url:
        # browser_navigate runs Hermes' URL checks, then hands off to Camofox.
        navigated = json.loads(_browser_tool().browser_navigate(url, task_id=task_id))
        if navigated.get("success") is False or navigated.get("error"):
            return _error(navigated.get("error") or "Navigation failed")
    session = bc._get_session(task_id)
    if not session.get("tab_id"):
        return _error("No page is open. Pass url.")

    page = Page(Camofox(bc.get_camofox_url(), session["user_id"], session["tab_id"], headers=bc._auth_headers()))
    key = (_profile_key(), page.cf.base, page.cf.user_id, page.cf.tab_id, task_id or "default")
    if url:
        _history.pop(key, None)
        _visual_requirements.pop(key, None)
    required = args.get("require_visual", _visual_requirements.get(key, False))
    options = {name: args[name] for name in ("max_model_calls", "timeout", "vision") if name in args}
    if required or "require_visual" in args:
        options["require_visual"] = required
    result = run_task(page, goal, history=_history.get(key), max_steps=max_steps, guard=url_block, **options)
    _visual_requirements[key] = required
    _history[key] = (_history.get(key, []) + result["steps"])[-HISTORY_KEEP:]
    while len(_history) > 128:
        removed = next(iter(_history))
        _history.pop(removed)
        _visual_requirements.pop(removed, None)
    result["success"] = result["status"] != "error"
    result["next"] = NEXT[result["status"]]
    return json.dumps(result, ensure_ascii=False)
