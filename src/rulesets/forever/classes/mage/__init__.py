from __future__ import annotations

from . import engine as _engine


def __getattr__(name: str):
    return getattr(_engine, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_engine)))
