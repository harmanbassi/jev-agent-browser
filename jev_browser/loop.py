"""The Jev decision loop: run until done, or pause and hand control back to the caller.

Adapted from browser-use/jev-ultrafast@1231850 agent.py (MIT, see LICENSE-jev-ultrafast).
Local changes: no inspector/recording; pauses (NEED_GUIDANCE, BLOCKED, low
confidence, no progress, step budget, missing field value) return a result the
calling agent can act on instead of stopping the run; history carries over
between calls so a resumed goal knows what already happened.
"""

import time

from .camofox import ActionUncertain, CamofoxError, StalePage, TabGone
from .jev import ModelError, action_space, choose, field_context, field_text, goal_met, verify_visual
from .policy import URLPolicy, action_block
from .budget import Budget, BudgetExceeded, current, limits
from .vision import VisionRun, VisionSettings, VisionUnavailable

TEXT_LIMIT = 8000
ELEMENT_LIMIT = 80
MAX_STALE = 5
MAX_RECOVERIES = 2  # reopened tabs per task after the browser destroyed one


def run_task(page, goal, *, history=None, max_steps=25, min_confidence=0.35, min_target_confidence=0.2,
             guard=None, max_model_calls=100, timeout=300, cancel=None,
             vision=None, require_visual=False, vision_settings=None):
    """Run on any compatible page driver, without requiring Hermes.

    The default page policy allows public HTTP(S) pages. Supply a URLPolicy
    explicitly to permit private pages. Cancellation/deadlines are cooperative:
    in-flight network calls finish or time out before the task returns.
    """
    try:
        limits(goal, max_steps, max_model_calls, timeout)
        settings = vision_settings or VisionSettings.from_env()
        mode = settings.resolve(vision, require_visual)
        if any(type(v) not in (int, float) or not 0 <= v <= 1 for v in (min_confidence, min_target_confidence)):
            raise ValueError("confidence thresholds must be between 0 and 1")
    except ValueError as e:
        return {"status": "error", "reason": str(e), "steps": [], "jev_calls": 0, "elapsed_ms": 0}
    budget = Budget(max_model_calls, timeout, cancel) if cancel is not None else Budget(max_model_calls, timeout)
    token = current.set(budget)
    try:
        return _run_task(page, goal.strip(), history=history, max_steps=max_steps,
                         min_confidence=min_confidence, min_target_confidence=min_target_confidence, guard=guard,
                         vision_mode=mode, visual=VisionRun(settings, require_visual))
    finally:
        current.reset(token)


def _run_task(page, goal, *, history, max_steps, min_confidence, min_target_confidence, guard,
              vision_mode, visual):
    """Drive `page` towards `goal`. Returns a result dict; never raises for model/browser failures.

    `guard(url)` sees the URL of every page actually read, before any of its text
    goes anywhere (Jev, the text helper, or the returned result), and returns an
    error message to stop on, or None. Checking the read page's own URL, not a
    separate live probe, leaves no gap for a redirect to slip through.
    Target confidence has its own, lower floor: Jev splits probability between
    near-identical targets (e.g. duplicate autocomplete suggestions), so the right
    click often scores 0.4-0.5 (live Wikipedia runs, 2026-09-29). Targets that share a
    destination are pooled before this floor applies (jev.equivalent); suggestions
    without one still split.
    """
    guard = URLPolicy() if guard is None else guard
    history = list(history or [])
    steps, decisions = [], []
    recoveries = 0
    started = time.perf_counter()
    state = cleared = latest = None  # cleared: the last read page whose URL passed the guard
    frame = None
    using_vision = vision_mode == "always" or visual.required
    # Strict floors only where visual verification is the point. An auto-escalated
    # (or always-on) run keeps the text floors: it escalated because it was unsure,
    # and jumping to 0.8 made every escalated run pause anyway.
    strict = 0.8 if visual.required else 0

    def capture():
        if not hasattr(page, "observe_vision"):
            raise VisionUnavailable("vision_capture_unavailable")
        observed = page.observe_vision(state["url"], visual)
        if guard and guard(observed.state["url"]):
            raise VisionUnavailable("vision_url_blocked")
        return observed

    def escalate():
        nonlocal using_vision
        if vision_mode == "auto" and not using_vision:
            using_vision = True
            visual.escalations += 1
            return True
        return False

    def tab_lost(action, text):
        # The action may have taken effect (a submitted form whose response was slow)
        # before the browser destroyed the tab. Never reopen and decide it again.
        nonlocal state
        attempted, state = state["url"], None
        step = {"action": action["label"], "kind": action["kind"], "from_url": attempted,
                "text": text, "page_changed": None, "tab_lost": True}
        steps.append(step)
        history.append(step)
        return result("paused", "tab_lost", url=attempted)

    def landed(url):
        # Where the last action led, recorded only once that page passed the guard.
        # Separate names: Jev read a bare "url" as the page an action led to.
        if steps and "url_after" not in steps[-1]:
            steps[-1]["url_after"] = url

    def result(status, reason=None, **extra):
        out = {"status": status}
        if reason:
            out["reason"] = reason
        if state is not None and state is cleared:
            visible = frame.safe if frame is not None and frame.state is state else state
            out.update(url=state["url"], title=state["title"])
            if not using_vision or visible is not state:
                out["text"] = visible["text"][:TEXT_LIMIT]
                if status == "paused":
                    out["elements"] = action_space(visible["actions"])[0][:ELEMENT_LIMIT]
        out.update(extra)
        out["steps"] = steps
        if recoveries:
            out["recoveries"] = recoveries
        if downloads := [h["download"] for h in history if h.get("download")]:
            out["downloads"] = downloads
        out["jev_calls"] = len(decisions)
        models = list(dict.fromkeys(d["model"] for d in decisions if isinstance(d.get("model"), str)))
        if models:
            out["models"] = models
        if decisions and decisions[-1].get("completion_probability") is not None:
            out["completion_probability"] = decisions[-1]["completion_probability"]
            if status == "done" and decisions[-1].get("goal_check") == "met":
                out["done_by"] = "goal_check"
        out["model_requests"] = current.get().calls
        out["usage"] = current.get().usage_summary()
        out["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        if vision_mode != "off":
            out["vision"] = visual.summary()
        return out

    try:
        stale = 0
        while True:
            current.get().check()
            try:
                if state is None or not page.fresh(state):
                    state = latest = page.observe()
                if state is not cleared:
                    if guard and (blocked := guard(state["url"])):
                        return result("error", blocked)  # uncleared: its text goes nowhere
                    cleared = state
                    landed(state["url"])
                recent = steps[-3:]
                if len(recent) == 3 and all(s["kind"] != "wait" for s in recent) and (
                    all(s["page_changed"] is False for s in recent)
                    # A control that toggles (a picker opening and closing) changes the page
                    # every other click, so also stop on the same action three times running.
                    # Scrolling that keeps revealing new content is progress; max_steps
                    # bounds an endless feed.
                    or len({(s["action"], s["kind"], s["text"]) for s in recent}) == 1
                    and not all(s["kind"] == "scroll" and s["page_changed"] for s in recent)
                ):
                    if not escalate():
                        return result("paused", "no_progress")
                if len(steps) >= max_steps:
                    return result("paused", "step_budget")
                if using_vision:
                    frame = capture()
                    state = cleared = latest = frame.state
                    landed(state["url"])
                    decision = choose(state, goal, history, frame=frame, vision_run=visual,
                                      target_floor=max(min_target_confidence, strict))
                else:
                    decision = choose(state, goal, history)
                current.get().check()
                if goal_met(decision, max(min_confidence, strict), max(min_target_confidence, strict)):
                    decision = {**decision, "choice": "DONE", "operation": "DONE", "goal_check": "met",
                                "confidence": 2 * decision["completion_probability"] - 1}  # Noul confidence |2p-1|
                decisions.append(decision)
                choice = decision["choice"]
                if choice in {"DONE", "BLOCKED", "NEED_GUIDANCE"}:
                    if not page.fresh(state):
                        raise StalePage("Page changed since the decision.")
                    if choice == "DONE":
                        if decision["confidence"] < max(min_confidence, strict):
                            if escalate():
                                continue
                            return result("paused", "low_confidence", confidence=decision["confidence"])
                        # Only a visual requirement needs visual proof; an escalation only helped
                        # choose actions, so the text DONE rules and goal check apply.
                        if visual.required:
                            fresh = capture()
                            if not frame.unchanged(fresh) or state["fingerprint"] != fresh.state["fingerprint"]:
                                raise StalePage("Visual completion changed.")
                            if not verify_visual(fresh, goal, visual, history,
                                                 goal_check=decision.get("completion_probability")):
                                return result("paused", "vision_completion_unverified")
                            verified_frame = capture()
                            if (not fresh.unchanged(verified_frame)
                                    or fresh.state["fingerprint"] != verified_frame.state["fingerprint"]
                                    or not page.fresh(verified_frame.state)):
                                raise StalePage("Page changed during verification.")
                            visual.verified = True
                        return result("done")
                    if choice == "BLOCKED" and escalate():
                        continue
                    return result("paused", choice.lower())
                target_confidence = decision["target_confidence"]
                if decision["confidence"] < max(min_confidence, strict) or (
                    # A box-resolved target was picked among observed candidates by pixels instead.
                    target_confidence is not None and decision.get("target_source") != "box"
                    and target_confidence < max(min_target_confidence, strict)
                ):
                    if escalate():
                        continue
                    detail = {"detail": "The goal check contradicted DONE; no other operation cleared "
                                        "the floor."} if decision.get("goal_check") == "unmet" else {}
                    return result("paused", "low_confidence", confidence=decision["confidence"],
                                  target_confidence=target_confidence, **detail)
                action = next(a for a in state["actions"] if a["id"] == choice)
                if reason := action_block(action):
                    return result("paused", reason)
                if any(h.get("download") and (h.get("action"), h.get("kind"), h.get("from_url"))
                       == (action["label"], action["kind"], state["url"]) for h in history):
                    return result("paused", "download_started")  # never fetch the same file again
                text = None
                if action["kind"] == "fill":
                    text = field_text(field_context(goal, action, frame.safe if using_vision else state, history))
                    if text is None:
                        return result("paused", "missing_value", field=action["label"])
                current.get().check()
                if using_vision:
                    fresh = capture()
                    if (state["fingerprint"] != fresh.state["fingerprint"]
                            or not frame.unchanged(fresh, action if "rect" in action else None)):
                        raise StalePage("Visual target changed.")
                    state = cleared = fresh.state
                    frame = fresh
                effect = None
                try:
                    page.act(action, state, text=text)
                except ActionUncertain:
                    effect = "uncertain"  # recorded below; the re-observation shows what happened
                except TabGone:
                    return tab_lost(action, text)
            except TabGone as gone:
                # A hung read can make the server destroy the tab (HTTP 410). No action was in
                # flight, and cookies survive in the identity: reopen the last page this task cleared.
                if (recoveries >= MAX_RECOVERIES or latest is None or not hasattr(page, "recover")
                        or not page.recover(latest["url"], guard)):  # reopening re-checks the guard
                    return result("error", str(gone))
                recoveries += 1
                step = {"action": "Reopened the page in a new tab", "kind": "recover", "from_url": latest["url"],
                        "text": None, "page_changed": True}
                steps.append(step)
                history.append(step)
                state = frame = None
                continue
            except StalePage:
                stale += 1
                if stale > MAX_STALE:
                    return result("error", "Page kept changing under every decision.")
                state = latest = page.observe()
                continue
            stale = 0
            step = {
                "action": action["label"],
                "kind": action["kind"],
                "from_url": state["url"],  # with url_after, lets Jev see where it has been
                "text": text,
                "confidence": round(decision["confidence"], 3),
                "target_confidence": target_confidence and round(target_confidence, 3),
            }
            steps.append(step)
            history.append(step)
            before = state
            try:
                state = latest = page.observe()
            except TabGone:
                steps.pop()
                history.pop()
                return tab_lost(action, text)
            step["page_changed"] = state["fingerprint"] != before["fingerprint"]
            if effect:
                moved = state["url"] != before["url"] or state["page_key"][:1] != before["page_key"][:1]
                step["effect"] = "taken" if moved else "uncertain"
            if action["kind"] == "click" and not step["page_changed"] and hasattr(page, "new_downloads"):
                if files := page.new_downloads():
                    step["download"] = files[0]
    except BudgetExceeded as e:
        return result("paused", str(e))
    except VisionUnavailable as e:
        return result("paused", str(e))
    except (ModelError, CamofoxError, StalePage) as e:
        return result("error", str(e))
