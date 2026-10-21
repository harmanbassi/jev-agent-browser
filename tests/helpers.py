"""Shared test helpers (a plain module, imported explicitly)."""

from jev_browser import camofox


def make_state(url="https://example.test/", text="Example page", actions=None, marker="m1"):
    """A snapshot.js-shaped page state."""
    if actions is None:
        actions = [
            {"id": "e1", "kind": "fill", "node": 1, "label": "Search", "role": "searchbox", "value": ""},
            {"id": "e2", "kind": "click", "node": 2, "label": "Go", "role": "button"},
            {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
        ]
    state = {
        "url": url,
        "title": "Example",
        "text": text,
        "scroll": {"y": 0, "height": 800},
        "actions": actions,
        "marker": marker,
        "page_key": ["k"],
        "guards": {"1": ["g1"], "2": ["g2"]},
    }
    state["fingerprint"] = camofox.fingerprint(state)
    return state


class FakePage:
    """jev's page interface with scripted observations."""

    def __init__(self, states):
        self.states = list(states)
        self.current = None
        self.acted = []
        self.is_fresh = True

    def observe(self):
        self.current = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return self.current

    def fresh(self, page, action=None):
        return self.is_fresh

    def act(self, action, page, text=None):
        self.acted.append((action["id"], text))

    def press(self, key, page):
        self.acted.append(("press", key))


def decision(choice, operation=None, confidence=0.9, target_confidence=None):
    return {"choice": choice, "operation": operation or choice, "confidence": confidence,
            "target_confidence": target_confidence, "latency_ms": 1, "usage": {}}
