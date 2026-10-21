"""Per-call settings bridge, without importing any agent framework in the core."""
from contextlib import contextmanager
from contextvars import ContextVar
import os

_reader = ContextVar("jev_environment_reader", default=None)


def get(name, default=None):
    reader = _reader.get()
    return reader(name, default) if reader is not None else os.environ.get(name, default)


@contextmanager
def use(reader):
    token = _reader.set(reader)
    try:
        yield
    finally:
        _reader.reset(token)
