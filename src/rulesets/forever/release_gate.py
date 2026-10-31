from __future__ import annotations

"""Executable Forever release-equivalent gate for M46.

This is deliberately small and deterministic.  It exercises the same canonical
player-facing decision-row path used by the listener for Mage, Paladin and Druid
at L20/L40/L60.  It is not route optimization (M47) and it does not pretend to
be a Monte-Carlo precision ladder.  Instead it is the release gate for the
Forever production surface that M46 actually publishes.
"""

import dataclasses
import math

from src import game_context
from src.engine_registry import get_engine, reset_engine_cache
from src.v2.spec_matrix import build_matrix
from src.v2.decision_dashboard import _canonical_route_rows

LEVELS = (20, 40, 60)
FAMILY = {"mage": "frost", "paladin": "protection", "druid": "feral"}


def fixed_fixture_rows(cls: str) -> list[dict]:
    """Build legal fixed-route canonical rows through the production renderer."""
    game_context.configure("forever", cls)
    reset_engine_cache()
    engine = get_engine()
    talents = engine.Talents()
    steps = []
    family = FAMILY[cls]
    for level in range(10, 61):
        legal = [k for k in engine.TALENT_RULES if engine.legal_add(talents, k)]
        if not legal:
            raise RuntimeError(f"no legal talent at {cls} L{level}")
        legal.sort(key=lambda k: (engine.TALENT_RULES[k][0] != family, k))
        talents = engine.add_point(talents, legal[0])
        if level in LEVELS:
            ranks = {k: v for k, v in dataclasses.asdict(talents).items() if v}
            steps.append({"level": level, "talent_ranks": ranks, "allocation": engine.final_allocation(talents)})

    matrix = build_matrix(engine, {"steps": steps}, class_name=cls, route="m46_release_fixture", target=60)
    endpoint = {"targets": {"60": {"routes": {"m46_release_fixture": {"status": "available", "path": {"steps": steps}}}}}}
    canonical = _canonical_route_rows(cls, endpoint, {"matrices": {"60:m46_release_fixture": matrix}})
    return canonical["60"]["routes"]["m46_release_fixture"]["rows"]


def _named_gear_count(row: dict) -> int:
    slots = ((row.get("gear_stats") or {}).get("slots") or {})
    return sum(1 for item in slots.values() if isinstance(item, dict) and str(item.get("name") or "").strip())


def _measured_weight_count(row: dict) -> int:
    stats = ((row.get("stat_weights") or {}).get("stats") or {})
    count = 0
    for item in stats.values():
        if not isinstance(item, dict) or item.get("status") != "measured":
            continue
        val = item.get("seconds_saved_per_100_per_point")
        if isinstance(val, (int, float)) and math.isfinite(float(val)):
            count += 1
    return count


def build_release_gate() -> dict:
    # Validation must be observational: running the gate must not change which
    # engine later production/release code sees in the same Python process.
    prior = game_context.current()
    checks: list[dict] = []
    failures: list[str] = []
    try:
        for cls in ("mage", "paladin", "druid"):
            rows = fixed_fixture_rows(cls)
            by_level = {int(r["level"]): r for r in rows if int(r.get("level", -1)) in LEVELS}
            for level in LEVELS:
                row = by_level.get(level)
                prefix = f"{cls}:L{level}"
                if row is None:
                    failures.append(f"{prefix}:missing_canonical_row")
                    continue
                mph = row.get("mobs_per_hour")
                rotation = str(row.get("rotation") or "").strip()
                allocation = str(row.get("allocation") or "").strip()
                ref = str((row.get("stat_weights") or {}).get("reference_stat") or "").strip()
                named_gear = _named_gear_count(row)
                measured_weights = _measured_weight_count(row)
                missing = list(row.get("missing") or [])
                ok = (
                    isinstance(mph, (int, float)) and math.isfinite(float(mph)) and float(mph) > 0
                    and bool(rotation) and bool(allocation) and bool(ref)
                    and named_gear > 0 and measured_weights > 0
                    and not any(x in {"rotation", "gear_stats", "stat_weights"} for x in missing)
                )
                checks.append({
                    "class": cls,
                    "level": level,
                    "ok": ok,
                    "mobs_per_hour": mph,
                    "rotation": rotation,
                    "allocation": allocation,
                    "reference_stat": ref,
                    "named_gear_slots": named_gear,
                    "measured_stat_weights": measured_weights,
                    "missing": missing,
                })
                if not ok:
                    failures.append(f"{prefix}:production_row_contract_failed")

    finally:
        game_context.configure(prior.ruleset, prior.class_name)
        reset_engine_cache()

    return {
        "schema_version": 1,
        "scope": "Forever production decision release-equivalent gate; fixed L20/L40/L60 fixtures, not M47 optimization",
        "checks": checks,
        "failures": failures,
        "ok": not failures,
    }
