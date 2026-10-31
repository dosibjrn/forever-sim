from __future__ import annotations

"""Canonical TalentsForever-backed Druid reference builds.

Runtime is deliberately offline: capture/normalization is owned by
``tools/capture_talentsforever_references.py`` and this provider only reads the
last-known-good canonical snapshot checked into ``data/``.
"""

import json
from copy import deepcopy
from pathlib import Path

from .talents import (
    Talents, TALENT_RULES, TALENT_SCHEMA_BUILD, allocation_schema_errors,
    expected_points_for_level, final_allocation, tree_points, legal_add, add_point,
)

_CANONICAL = Path(__file__).resolve().parents[5] / "data" / "forever" / "reference_builds" / "talentsforever" / "druid.json"


def validate_exact_reference_build(build: dict) -> dict:
    """Validate an exact TalentsForever allocation against current runtime schema."""
    ranks = {str(k): int(v) for k, v in dict(build.get("talent_ranks") or {}).items() if int(v) != 0}
    unknown = sorted(set(ranks) - set(TALENT_RULES))
    errors: list[str] = [f"unknown_talent:{name}" for name in unknown]
    known = {k: v for k, v in ranks.items() if k in TALENT_RULES}
    talents = Talents(**known)
    errors.extend(allocation_schema_errors(talents))
    level = int(build.get("level", 60) or 60)
    expected = expected_points_for_level(level)
    if talents.points() != expected:
        errors.append(f"point_budget:{talents.points()}!={expected}")
    declared = dict(build.get("tree_points") or {})
    actual = {tree: tree_points(talents, tree) for tree in ("balance", "feral", "restoration")}
    if declared and {k: int(v) for k, v in declared.items()} != actual:
        errors.append(f"tree_points:{declared}!={actual}")
    order = [str(x) for x in (build.get("leveling_order") or ())]
    if order:
        prefix = Talents()
        for idx, name in enumerate(order, 1):
            if name not in TALENT_RULES:
                errors.append(f"progression_unknown_talent:{name}")
                break
            if not legal_add(prefix, name):
                errors.append(f"progression_illegal_step:{idx}:{name}")
                break
            prefix = add_point(prefix, name)
        if len(order) != expected:
            errors.append(f"progression_point_budget:{len(order)}!={expected}")
        if final_allocation(prefix) != final_allocation(talents):
            errors.append("progression_final_allocation_mismatch")
    return {
        "ok": not errors,
        "schema_build": TALENT_SCHEMA_BUILD,
        "level": level,
        "points": talents.points(),
        "tree_points": actual,
        "allocation": final_allocation(talents),
        "errors": errors,
    }


def reference_build_snapshot() -> dict:
    payload = json.loads(_CANONICAL.read_text(encoding="utf-8"))
    if payload.get("class") != "druid" or not isinstance(payload.get("builds"), list):
        raise ValueError(f"invalid canonical Druid reference-build snapshot: {_CANONICAL}")
    for build in payload.get("builds", []):
        if build.get("allocation_detail_status") != "exact":
            continue
        validation = validate_exact_reference_build(build)
        if not validation["ok"]:
            raise ValueError(f"exact Druid reference build is stale/invalid for {TALENT_SCHEMA_BUILD}: {validation['errors']}")
        build["runtime_schema_validation"] = validation
    payload.setdefault("source", {})["runtime_talent_schema_build"] = TALENT_SCHEMA_BUILD
    return deepcopy(payload)
