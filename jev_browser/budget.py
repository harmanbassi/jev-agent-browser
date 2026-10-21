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


def request_timeout(default_timeout):
    budget = current.get()
    return budget.request(default_timeout) if budget else default_timeout
