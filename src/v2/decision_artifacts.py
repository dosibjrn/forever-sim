from __future__ import annotations

"""Bounded, player-facing decision artifacts.

The optimizer owns generation.  The listener only reads these files, so HTTP
requests can never accidentally launch talent search or stat-weight probes.
"""

import json
from pathlib import Path
from typing import Any

from .runtime_state import atomic_write_json
from src import game_context


ROOT = Path(__file__).resolve().parents[2]
DECISION_ROOT = game_context.base_state_root(ROOT) / "decisions" / "forever"
MILESTONE_LEVELS = (20, 30, 40, 60)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def game_state_root(class_name: str) -> Path:
    return game_context.base_state_root(ROOT) / "games" / f"forever-{class_name}" / "v2"


def frontier_path(class_name: str) -> Path:
    return game_state_root(class_name) / "decision_frontier.json"


def update_scoped(path: Path, class_name: str, payload: dict) -> Path:
    """Update one class without deleting artifacts produced by other runs."""
    current = read_json(path, {}) or {}
    if not isinstance(current, dict):
        current = {}
    current.setdefault("schema_version", 1)
    current.setdefault("ruleset", "forever")
    current.setdefault("classes", {})[str(class_name)] = payload
    atomic_write_json(path, current)
    return path


def write_frontier(class_name: str, payload: dict) -> Path:
    path = frontier_path(class_name)
    atomic_write_json(path, payload)
    return path


def bounded_candidate(candidate: dict, *, include_steps: bool = False) -> dict:
    """Keep decision semantics, not the scorer's full debug payload."""
    out = {
        key: candidate.get(key)
        for key in (
            "level", "allocation", "talent_ranks", "tree_points",
            "talent_family", "combat_profile", "gear", "gear_stats",
            "pull_size", "policy", "aura", "mana_plan", "mobs_per_hour",
            "score_s_per_100", "cumulative_objective_s", "source",
            "model_fidelity",
        )
        if candidate.get(key) is not None
    }
    if include_steps:
        out["steps"] = [
            {
                key: step.get(key)
                for key in (
                    "level", "talent_added", "allocation", "talent_ranks",
                    "tree_points", "talent_family", "combat_profile", "gear",
                    "gear_stats", "pull_size", "policy", "rotation", "aura",
                    "mana_plan", "mobs_per_hour",
                    "score_s_per_100",
                )
                if step.get(key) is not None
            }
            for step in candidate.get("steps", ())
        ]
    return out
