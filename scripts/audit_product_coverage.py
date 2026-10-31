#!/usr/bin/env python3
"""WF-P00a: executable, fail-closed Forever 1–60 product coverage audit.

Source IR, queue admission, bounded route evaluation and fully optimized
leveling are independent capabilities. This command never runs the optimizer,
changes game facts or promotes route snapshots to product readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.game.data.forever.queue_capabilities import native_generic_queue_levels
from src.game.data.forever.registry import (
    build_game_ir_slice, generic_default_ready_levels, generic_planning_levels,
    generic_source_level_bounds, registered_class_keys,
)
from src.v2.generic_frontier import (
    GENERIC_DRUID_ROUTE_LEVELS, ROUTE_AUTHORITY as DRUID_ROUTE_AUTHORITY,
    ROUTE_PUBLICATION_CACHE_SCHEMA as DRUID_SCHEMA,
)
from src.v2.generic_melee_routes import (
    MELEE_CORRIDORS, MELEE_CACHE_SCHEMA, ROUTE_AUTHORITY as MELEE_ROUTE_AUTHORITY,
    _fingerprint as melee_source_fingerprint,
)
from src.version import SOFTWARE_VERSION

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ("druid", "hunter", "mage", "paladin", "priest", "rogue", "shaman", "warlock", "warrior")
STATUSES = ("unsupported", "source_only", "evaluated", "optimized", "route_complete", "validated")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_snapshot(path: Path, *, version: str, db_sha: str, schema: int,
                     levels, authority: str, source_fingerprint: str | None = None) -> dict:
    """Validate immutable cache identity before trusting even bounded route rows."""
    result = {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
              "valid": False, "sha256": None, "failures": []}
    if not path.is_file():
        result["failures"].append("missing_snapshot")
        return result
    result["sha256"] = sha256(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checks = {
            "schema": data.get("schema_version") == schema,
            "version": data.get("software_version") == version,
            "ruleset": data.get("ruleset") == "forever",
            "authority": data.get("route_authority") == authority,
            "levels": data.get("levels") == levels,
            "canonical_item_db": data.get("canonical_item_db_sha256") == db_sha,
        }
        if source_fingerprint is not None:
            checks["source_code_fingerprint"] = data.get("source_code_fingerprint") == source_fingerprint
        result["failures"] = [key for key, valid in checks.items() if not valid]
        result["valid"] = not result["failures"]
        if result["valid"]:
            result["data"] = data
    except (OSError, ValueError, TypeError) as exc:
        result["failures"].append(f"unreadable:{type(exc).__name__}")
    return result


def _positive_seconds(step: dict) -> bool:
    value = step.get("seconds_per_mob")
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def full_optimization_blockers(step: dict) -> list[str]:
    """A scored route or IR never passes these independent product gates."""
    blockers = []
    gear = step.get("gear_stats") or {}
    weights = step.get("stat_weights") or {}
    timing = step.get("timing") or {}
    proof = step.get("optimization_evidence") or {}
    if gear.get("selection_method") not in {"selected_named_catalogue_gear", "verified_attainable_normal_gear"} or not gear.get("slots"):
        blockers.append("attainable_selected_gear_not_proven")
    if not weights.get("stats") or not weights.get("method"):
        blockers.append("stat_sensitivity_not_proven")
    if not step.get("policy_ir") or not _positive_seconds(step):
        blockers.append("executed_policy_and_score_not_proven")
    if (timing.get("timing_complete") is not True or timing.get("timing_consistent") is not True
            or timing.get("travel_seconds_per_mob") is None or timing.get("recovery_seconds_per_mob") is None):
        blockers.append("complete_cycle_and_travel_timing_not_proven")
    if (proof.get("producer") != "joint_generic_gear_talent_policy_optimizer"
            or type(proof.get("evaluated_candidate_count")) is not int
            or proof["evaluated_candidate_count"] < 2
            or proof.get("legal_talents_and_gear") is not True
            or proof.get("recovery_and_survival_risk") is not True
            or step.get("fixed_point_converged") is not True):
        blockers.append("joint_search_legality_recovery_and_competitors_not_proven")
    return blockers


def classify_level(*, source_ir: bool, route_step: dict | None,
                   complete_route_proof: bool = False,
                   independent_reference_proof: bool = False) -> tuple[str, list[str]]:
    """Never infer optimization from registry bounds, queue, or bounded route."""
    if not source_ir:
        return "unsupported", ["no_executable_source_ir"]
    if not route_step or route_step.get("legacy_fallback") is not False or not _positive_seconds(route_step):
        return "source_only", ["no_version_pinned_evaluated_native_route_step"]
    blockers = full_optimization_blockers(route_step)
    if blockers:
        return "evaluated", blockers
    if not complete_route_proof:
        return "optimized", ["continuous_legal_route_not_proven"]
    if not independent_reference_proof:
        return "route_complete", ["independent_reference_not_proven"]
    return "validated", []


def _bounded_steps(root: Path, version: str, db_sha: str) -> tuple[dict, dict]:
    snapshots = {}
    steps = {}
    druid = inspect_snapshot(
        root / "data/forever/generic_druid_route_publication_v1.json",
        version=version, db_sha=db_sha, schema=DRUID_SCHEMA,
        levels=list(GENERIC_DRUID_ROUTE_LEVELS), authority=DRUID_ROUTE_AUTHORITY,
    )
    snapshots["druid"] = {k: v for k, v in druid.items() if k != "data"}
    if druid["valid"]:
        candidates = druid["data"].get("selected_route_steps") or []
        if (len(candidates) == len(GENERIC_DRUID_ROUTE_LEVELS)
                and [x.get("level") for x in candidates] == list(GENERIC_DRUID_ROUTE_LEVELS)
                and all(x.get("backend") == "generic" for x in candidates)):
            steps["druid"] = {x["level"]: x for x in candidates}
        else:
            snapshots["druid"]["valid"] = False
            snapshots["druid"]["failures"].append("invalid_or_incomplete_selected_steps")
    melee = inspect_snapshot(
        root / "data/forever/generic_melee_route_publication_v1.json",
        version=version, db_sha=db_sha, schema=MELEE_CACHE_SCHEMA,
        levels={k: list(v) for k, v in MELEE_CORRIDORS.items()},
        authority=MELEE_ROUTE_AUTHORITY, source_fingerprint=melee_source_fingerprint(),
    )
    snapshots["melee"] = {k: v for k, v in melee.items() if k != "data"}
    if melee["valid"]:
        for cls, levels in MELEE_CORRIDORS.items():
            class_pub = (melee["data"].get("classes") or {}).get(cls) or {}
            target = (class_pub.get("route_rows") or {}).get(str(max(levels))) or {}
            route = (target.get("routes") or {}).get("unconstrained") or {}
            rows = route.get("rows") or []
            if (route.get("status") == "available" and len(rows) == len(levels)
                    and [r.get("level") for r in rows] == list(levels)
                    and all(r.get("legacy_fallback") is False for r in rows)):
                steps[cls] = {r["level"]: r for r in rows}
            else:
                snapshots["melee"]["valid"] = False
                snapshots["melee"]["failures"].append(f"invalid_or_incomplete_{cls}_route_rows")
        if not snapshots["melee"]["valid"]:
            for cls in MELEE_CORRIDORS:
                steps.pop(cls, None)
    return snapshots, steps


def _native_evidence_identity(root: Path) -> str:
    """Invalidates cached real L2 replay after source/IR/engine/data changes.

    Replay all 157 witnesses only once for an identical loaded release. A
    data-only patch or changed scenario HP/ruleset invalidates the identity,
    avoiding repeated full kills on every read-only coverage request.
    """
    h=hashlib.sha256()
    files=list((root/'src').rglob('*.py'))
    files += [root/'data/forever/catalogue/items_2026-09-29.sqlite',
              root/'data/forever/catalogue/forever_abilities.sqlite',
              root/'data/forever/source_bounded_level_routes_v1.json',
              root/'data/forever/wf289_parent_druid_l1_60_replay.json']
    for path in sorted(files):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes() if path.is_file() else b'<MISSING>')
    return h.hexdigest()


@lru_cache(maxsize=4)
def _checked_native_route_evidence(root_path: str, version: str,
                                   item_db_sha: str, source_identity: str):
    from src.v2.source_bounded_route_evidence import checked_source_scenario_routes
    from src.v2.source_reference_route_evidence import checked_reference_druid_route
    root=Path(root_path)
    return (checked_source_scenario_routes(root,version=version,item_db_sha=item_db_sha),
            checked_reference_druid_route(root,version=version))


def audit(root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    db_path = root / "data/forever/catalogue/items_2026-09-29.sqlite"
    db_sha = sha256(db_path)
    snapshots, steps = _bounded_steps(root, SOFTWARE_VERSION, db_sha)
    # Independent, version/source-checked 9-class *bounded* native source
    # corridors. Their scores may enter 'evaluated'; they cannot certify gear
    # acquisition, full routes or validated product checkpoints.
    (bounded_diag, bounded_steps), (reference_diag, reference_steps) = _checked_native_route_evidence(
        str(root), SOFTWARE_VERSION, db_sha, _native_evidence_identity(root))
    snapshots['source_scenario_corridors'] = bounded_diag
    snapshots['druid_fullpoint_heldout_reference'] = reference_diag
    registered = set(registered_class_keys())
    rows = []
    # Some class providers are canonical SQLite-backed generic native slices,
    # not a per-class Python file. Use their *real shared provider* as source
    # identity instead of crashing the entire 9x60 audit on missing paths.
    provider_dir = root / "src/game/data/forever"
    source_paths = {
        cls: (provider_dir / f"{cls}.py"
              if (provider_dir / f"{cls}.py").is_file()
              else provider_dir / "native_source_provider.py")
        for cls in registered
    }
    source_hashes = {cls: sha256(path) for cls, path in source_paths.items()}
    for cls in CLASSES:
        bounds = generic_source_level_bounds(cls) if cls in registered else None
        queue_levels = set(native_generic_queue_levels(cls)) if cls in registered else set()
        planning_levels = set(generic_planning_levels(cls)) if cls in registered else set()
        default_ready = set(generic_default_ready_levels(cls)) if cls in registered else set()
        for level in range(1, 61):
            ir = None
            ir_error = None
            if bounds and bounds[0] <= level <= bounds[1]:
                try:
                    ir = build_game_ir_slice(class_key=cls, level=level)
                except Exception as exc:  # fail closed, retain diagnosis
                    ir_error = f"{type(exc).__name__}: {exc}"
            step = ((reference_steps.get((cls,level)) or bounded_steps.get((cls,level)) or (steps.get(cls) or {}).get(level))
                    if ir is not None else None)
            status, blockers = classify_level(source_ir=ir is not None, route_step=step)
            if ir_error:
                blockers.append("ir_exception:" + ir_error)
            if level in default_ready and status not in ("route_complete", "validated"):
                blockers.append("CONTRADICTORY_GENERIC_DEFAULT_DECLARATION")
            row = {
                "class": cls, "level": level, "status": status,
                "registered": cls in registered,
                "source_ir_executed": ir is not None,
                "source_ir_declared_bounds": list(bounds) if bounds else None,
                "queue_source_only_declared": level in queue_levels,
                "bounded_route_planning_declared": level in planning_levels,
                "bounded_native_evaluation": step is not None,
                "gear_selected_named": bool(step and (step.get("gear_stats") or {}).get("slots")
                                            and (step.get("gear_stats") or {}).get("selection_method") != "explicit_scenario_proxy_not_named_gear"),
                "stat_sensitivity_present": bool(step and (step.get("stat_weights") or {}).get("stats")),
                "complete_timing": bool(step and (step.get("timing") or {}).get("timing_complete") is True),
                "generic_default_declared": level in default_ready,
                "blockers": blockers,
                "evidence": {
                    "source_provider_sha256": source_hashes.get(cls) if ir is not None else None,
                    "queue_declaration_sha256": sha256(root / "src/game/data/forever/queue_capabilities.py") if level in queue_levels else None,
                    "route_snapshot_sha256": (reference_diag['sha256'] if (cls,level) in reference_steps
                                              else bounded_diag['sha256'] if (cls,level) in bounded_steps
                                              else snapshots["druid" if cls == "druid" else "melee"]["sha256"]
                                              if step is not None else None),
                },
            }
            rows.append(row)
    summary = {}
    for cls in CLASSES:
        cr = [x for x in rows if x["class"] == cls]
        summary[cls] = {status: sum(r["status"] == status for r in cr) for status in STATUSES}
        summary[cls].update({
            "source_ir_executed": sum(r["source_ir_executed"] for r in cr),
            "queue_source_only_declared": sum(r["queue_source_only_declared"] for r in cr),
            "bounded_native_evaluation": sum(r["bounded_native_evaluation"] for r in cr),
            "fully_optimized": sum(r["status"] in STATUSES[3:] for r in cr),
        })
    contradictions = [f"{r['class']}:L{r['level']}" for r in rows
                      if "CONTRADICTORY_GENERIC_DEFAULT_DECLARATION" in r["blockers"]]
    return {
        "schema_version": 2, "audit": "WF-P00a", "software_version": SOFTWARE_VERSION,
        "ruleset": "forever", "level_range": [1, 60],
        "scope": "native_generic_only; legacy is never counted",
        "canonical_item_db_sha256": db_sha,
        "snapshot_validation": snapshots,
        "bounded_source_scenario_routes": {
            "full_L10_to_L20_corridors": bounded_diag.get('full_bounded_corridors',0),
            "fullpoint_Druid_L1_to_L60_bounded_reference": reference_diag.get('independently_replayed_levels',0)==60,
            "distinct_source_scenario_evaluated_level_slices": len(set(bounded_steps)|set(reference_steps)),
            "scratch_verified_source_scenario_steps": bounded_diag.get('scratch_verified_source_scenario_steps',0),
            "required_L10_to_L20_class_corridors": 9,
            "required_L10_to_L20_scenario_steps": 99,
            "complete_leveling_routes": 0,
            "source_complete_validated_class_level_checkpoints": 0,
            "not_a_complete_route": True,
        },
        "summary": summary, "contradictory_default_declarations": contradictions,
        "rows": rows,
        "notes": [
            "Source IR is an executed provider slice, not a validated game fact or optimizer.",
            "Bounded native route evaluation is distinct from complete 1–60 route and full timing.",
            "A snapshot whose release/source identity is stale cannot yield evaluated coverage.",
            "Route continuity, legal gear acquisition, full recovery/travel/risk and independent reference gates are not inferred.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="coverage_forever_1_60_v2.json")
    parser.add_argument("--text", default="coverage_forever_1_60_v2.txt")
    args = parser.parse_args(argv)
    report = audit()
    out = ROOT / args.output
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    header = "class       source  queue  evaluated  optimized  route  validated"
    lines = [f"WF-P00a native Forever 1–60 coverage • {SOFTWARE_VERSION}", header]
    for cls, row in report["summary"].items():
        lines.append(f"{cls:<12}{row['source_ir_executed']:>4} {row['queue_source_only_declared']:>6}"
                     f" {row['evaluated']:>10} {row['fully_optimized']:>10}"
                     f" {row['route_complete']:>6} {row['validated']:>10}")
    lines.append(f"Contradictory default declarations: {report['contradictory_default_declarations']}")
    lines.append("Evaluated means a bounded scored native route, NOT full leveling optimization.")
    text = "\n".join(lines) + "\n"
    (ROOT / args.text).write_text(text, encoding="utf-8")
    print(text, end="")
    return 1 if report["contradictory_default_declarations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
