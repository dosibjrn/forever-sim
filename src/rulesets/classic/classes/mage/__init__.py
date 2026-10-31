from __future__ import annotations

"""Classic Era Mage ruleset adapter.

The mature simulator remains in its historical module for v0.10 compatibility.
The registry imports it through the ruleset/class ownership tree so callers no
longer need to know that legacy location.  A later mechanical file split can be
performed behind this boundary without changing registry/users.
"""

from importlib import import_module

_impl = import_module("src.classic_mage_leveling_optimizer_v10")


def __getattr__(name: str):
    return getattr(_impl, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_impl)))
