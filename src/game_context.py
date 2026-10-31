from __future__ import annotations

"""Runtime game selection and state namespacing.

This module is intentionally dependency-light so it can bootstrap ``--ruleset``
and ``--class`` before the rest of the simulator imports stateful modules.
Classic Era Mage keeps the historical ``state/`` layout byte-for-byte compatible;
all new game/class combinations are isolated below ``state/games/<key>/``.
"""

from dataclasses import dataclass
from pathlib import Path
import argparse
import os
import sys
from typing import Iterable

from src.class_registry import class_names, get_definition, registered_games, rulesets

RULESET_ENV = "WOW_SIM_RULESET"
CLASS_ENV = "WOW_SIM_CLASS"
STATE_BASE_ENV = "WOW_SIM_STATE_BASE"
RULESETS = rulesets()
CLASSES = class_names()
DEFAULT_RULESET = "classic"
DEFAULT_CLASS = "mage"

# Availability comes from the explicit M45 class registry.
SUPPORTED_GAMES = set(registered_games())


@dataclass(frozen=True)
class GameSpec:
    ruleset: str
    class_name: str

    @property
    def key(self) -> str:
        return f"{self.ruleset}-{self.class_name}"

    @property
    def is_legacy_default(self) -> bool:
        return self.ruleset == DEFAULT_RULESET and self.class_name == DEFAULT_CLASS

    @property
    def experimental(self) -> bool:
        return self.ruleset == "forever"


def _normalize(ruleset: str | None, class_name: str | None) -> GameSpec:
    r = str(ruleset or DEFAULT_RULESET).strip().lower()
    c = str(class_name or DEFAULT_CLASS).strip().lower()
    if r not in RULESETS:
        raise ValueError(f"unsupported ruleset {r!r}; choose one of {', '.join(RULESETS)}")
    if c not in CLASSES:
        raise ValueError(f"unsupported class {c!r}; choose one of {', '.join(CLASSES)}")
    if (r, c) not in SUPPORTED_GAMES:
        raise ValueError(f"{r}/{c} is not implemented; supported: " + ", ".join(f"{a}/{b}" for a,b in sorted(SUPPORTED_GAMES)))
    # Registry lookup is the authoritative support check and gives clearer
    # failures if a future registry edit becomes internally inconsistent.
    get_definition(r, c)
    return GameSpec(r, c)


def configure(ruleset: str | None = None, class_name: str | None = None) -> GameSpec:
    """Select the active game for this process and future spawned children."""
    spec = _normalize(ruleset or os.environ.get(RULESET_ENV), class_name or os.environ.get(CLASS_ENV))
    os.environ[RULESET_ENV] = spec.ruleset
    os.environ[CLASS_ENV] = spec.class_name
    return spec


def configure_from_argv(argv: Iterable[str] | None = None) -> GameSpec:
    """Pre-parse only game-selection flags, leaving all other CLI args untouched."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ruleset", choices=RULESETS, default=None)
    parser.add_argument("--class", dest="class_name", choices=CLASSES, default=None)
    ns, _ = parser.parse_known_args(list(sys.argv[1:] if argv is None else argv))
    return configure(ns.ruleset, ns.class_name)


def current() -> GameSpec:
    return _normalize(os.environ.get(RULESET_ENV), os.environ.get(CLASS_ENV))


def add_game_arguments(parser: argparse.ArgumentParser) -> None:
    spec = current()
    parser.add_argument("--ruleset", choices=RULESETS, default=spec.ruleset,
                        help="game ruleset (default: classic)")
    parser.add_argument("--class", dest="class_name", choices=CLASSES, default=spec.class_name,
                        help="class simulation backend (default: mage)")


def validate_cli_selection(parser: argparse.ArgumentParser, args) -> GameSpec:
    try:
        return configure(getattr(args, "ruleset", None), getattr(args, "class_name", None))
    except ValueError as exc:
        parser.error(str(exc))
        raise AssertionError("unreachable")


def base_state_root(project_root: Path) -> Path:
    override = os.environ.get(STATE_BASE_ENV)
    return Path(override) if override else Path(project_root) / "state"


def state_root(project_root: Path) -> Path:
    spec = current()
    base = base_state_root(project_root)
    return base if spec.is_legacy_default else base / "games" / spec.key


def v2_state_root(project_root: Path) -> Path:
    return state_root(project_root) / "v2"


def describe() -> dict[str, object]:
    spec = current()
    return {
        "ruleset": spec.ruleset,
        "class": spec.class_name,
        "game_key": spec.key,
        "experimental": spec.experimental,
        "legacy_state_layout": spec.is_legacy_default,
    }


if __name__ == "__main__":
    configure_from_argv()
    print(current().key)
