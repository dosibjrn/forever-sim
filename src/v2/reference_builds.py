from __future__ import annotations

"""Optional source-backed reference builds for the Decisions surface.

Reference builds are challengers/comparison aids only. They never participate in
search, pruning, or route authority. A class may expose a sibling
``reference_builds`` module next to its engine with ``reference_build_snapshot``.
"""

import importlib
from dataclasses import replace

from src.class_registry import get_definition


def _progression_prefixes(class_name: str, build: dict) -> dict[str, dict]:
    """Materialize source-backed leveling-order prefixes for listener comparison.

    Stored references are comparison aids, never search authority.  When the
    capture includes an explicit point-by-point ``leveling_order``, derive the
    exact legal allocation at every reachable level so the UI never compares a
    low-level optimizer state against the final L60 split.
    """
    order = [str(x) for x in (build.get("leveling_order") or ())]
    if not order:
        return {}
    definition = get_definition("forever", class_name)
    module_name = definition.talent_module or definition.engine_module
    module = importlib.import_module(module_name)
    rules = dict(getattr(module, "TALENT_RULES", {}) or {})
    talents_type = getattr(module, "Talents", None)
    add_point = getattr(module, "add_point", None)
    legal_add = getattr(module, "legal_add", None)
    tree_points_fn = getattr(module, "tree_points", None)
    final_allocation = getattr(module, "final_allocation", None)
    expected_points = getattr(module, "expected_points_for_level", None)
    if not rules or talents_type is None or not callable(add_point) or not callable(legal_add):
        return {}
    talents = talents_type()
    prefixes: dict[str, dict] = {}
    point_index = 0
    max_level = min(60, int(build.get("level") or 60))
    for level in range(10, max_level + 1):
        expected = int(expected_points(level)) if callable(expected_points) else max(0, min(51, level - 9))
        while point_index < expected:
            if point_index >= len(order):
                return prefixes
            name = order[point_index]
            if name not in rules or not legal_add(talents, name):
                return prefixes
            talents = add_point(talents, name)
            point_index += 1
        ranks = {name: int(getattr(talents, name)) for name in rules if int(getattr(talents, name)) > 0}
        trees = {
            str(tree): int(tree_points_fn(talents, tree)) if callable(tree_points_fn) else 0
            for tree in definition.tree_names
        }
        prefixes[str(level)] = {
            "level": level,
            "points": sum(ranks.values()),
            "talent_ranks": ranks,
            "tree_points": trees,
            "allocation": str(final_allocation(talents)) if callable(final_allocation) else repr(talents),
            "progression_source": "talentsforever_leveling_order",
            "progression_exact": True,
        }
    return prefixes


def _enrich_progression(class_name: str, payload: dict) -> dict:
    builds = []
    for raw in payload.get("builds") or ():
        build = dict(raw)
        prefixes = _progression_prefixes(class_name, build)
        if prefixes:
            build["prefixes_by_level"] = prefixes
            build["progression_status"] = "exact_source_leveling_order"
        builds.append(build)
    payload["builds"] = builds
    groups = payload.get("groups") or {}
    if groups:
        by_id = {b.get("id"): b for b in builds}
        new_groups = {}
        for key, group_raw in groups.items():
            group = dict(group_raw)
            group["builds"] = [by_id.get(b.get("id"), dict(b)) for b in (group.get("builds") or ())]
            new_groups[key] = group
        payload["groups"] = new_groups
    return payload


def reference_build_snapshot(class_name: str) -> dict:
    definition = get_definition("forever", class_name)
    package = definition.engine_module.rsplit(".", 1)[0]
    try:
        module = importlib.import_module(f"{package}.reference_builds")
    except ModuleNotFoundError as exc:
        # Only swallow the optional sibling module being absent. A missing import
        # *inside* a provider is a real provider error and should remain visible.
        if exc.name == f"{package}.reference_builds":
            return {}
        raise
    provider = getattr(module, "reference_build_snapshot", None)
    if not callable(provider):
        return {}
    payload = dict(provider() or {})
    payload.setdefault("schema_version", 1)
    payload.setdefault("class", class_name)
    return _enrich_progression(class_name, payload)


def all_reference_build_snapshots(class_names) -> dict[str, dict]:
    return {name: snap for name in class_names if (snap := reference_build_snapshot(name))}
