"""Per-task cooperative deadlines, cancellation and model HTTP request limits."""
from contextvars import ContextVar
from dataclasses import dataclass, field
import math
import threading
import time

current = ContextVar("jev_task_budget", default=None)


class BudgetExceeded(RuntimeError):
    pass


def limits(goal, max_steps, max_calls, timeout):
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 16000:
        raise ValueError("goal must be a non-empty string of at most 16000 characters")
    for name, value, maximum in (("max_steps", max_steps, 100), ("max_model_calls", max_calls, 500)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"{name} must be an integer between 1 and {maximum}")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 900:
        raise ValueError("timeout must be a finite number between 0 and 900 seconds")


@dataclass
class Budget:
    max_calls: int
    timeout: float
    cancel: threading.Event = field(default_factory=threading.Event)
    calls: int = 0
    started: float = field(default_factory=lambda: time.monotonic())
    usage: dict = field(default_factory=dict)  # model -> token/cost totals

    def check(self):
        if self.cancel.is_set():
            raise BudgetExceeded("cancelled")
        if time.monotonic() - self.started >= self.timeout:
            raise BudgetExceeded("timeout")

    def request(self, default_timeout):
        self.check()
        if self.calls >= self.max_calls:
            raise BudgetExceeded("model_budget")
        self.calls += 1
        return min(default_timeout, max(0.001, self.timeout - (time.monotonic() - self.started)))


    def record(self, model, usage):
        """Add one reply's reported usage. Decisions report input/output tokens, chat
        completions prompt/completion tokens; malformed values are ignored."""
        if not isinstance(usage, dict):
            return
        counts = {"input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
                  "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
                  "cost": usage.get("cost")}
        for name, value in counts.items():
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                totals = self.usage.setdefault(str(model), {})
                totals[name] = totals.get(name, 0) + value

    def usage_summary(self):
        out = {"input_tokens": 0, "output_tokens": 0}
        for totals in self.usage.values():
            for name, value in totals.items():
                out[name] = out.get(name, 0) + value
        if "cost" in out:
            out["cost"] = round(out["cost"], 6)
        out["by_model"] = {model: dict(totals) for model, totals in self.usage.items()}
        return out


def request_timeout(default_timeout):
    budget = current.get()
    return budget.request(default_timeout) if budget else default_timeout
