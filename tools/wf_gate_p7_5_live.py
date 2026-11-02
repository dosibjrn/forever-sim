"""P7.5 first cold source-legal joint candidate -> real pinned Rust <-> gsim 2D.

Reuse the existing native joint candidate generator and the existing live world
evaluator. This is a bounded *production* diagnostic, never the independent
300-second balanced-RNG search or 1000-stochastic-fight frozen holdout.
The accepted-compatible P7.1-P7.4 comparator must not be invented.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile

from tools.wf_gate_p7_1_live import (
    PINNED_RUST, SAVED_BALANCE_RAW_SHA, _source_native_world_parity,
)
from tools.wf_gate_p7_2_live import _pinned_source_runtime, _source_module
from tools.wf_gate_coverage import p7_required_dps


def _cold_joint(base: dict, pools: dict, rng: random.Random, joint,
                validator, item_names: dict) -> dict:
    """Free all three axes; source/Rust legality precedes paid evaluation."""
    candidate = joint.make_candidate(
        base, pools, rng, elite=None, item_names=item_names)
    old = base["raid"]["parties"][0]["players"][0]
    new = candidate["raid"]["parties"][0]["players"][0]
    if (new["equipment"] == old["equipment"]
            or new["talentsString"] == old["talentsString"]
            or new["rotation"]["priorityList"] == old["rotation"]["priorityList"]):
        raise ValueError("P7_5_COLD_JOINT_DID_NOT_FREE_ALL_THREE_AXES")
    if not joint.validate(joint.parse(new["talentsString"])):
        raise ValueError("P7_5_COLD_SOURCE_TALENTS_ILLEGAL")
    equipment = new["equipment"]["items"]
    validator.validate(
        [int(item["id"]) for item in equipment],
        [item.get("enchant", 0) for item in equipment])
    return candidate


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.5")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    upstream = binary.parents[2]
    catalogue = root / "data/forever/catalogue/items_2026-09-29.sqlite"
    items = upstream / "data/items.jsonl"
    enchants = upstream / "data/enchants.jsonl"
    if any(not path.is_file() for path in (catalogue, items, enchants)):
        return {"status": "BLOCKED",
                "reasons": ["P7_5_PINNED_SOURCE_OR_NATIVE_ITEM_DATABASE_MISSING"]}

    source_dir = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(source_dir))
    try:
        # Existing native P7.5 source-legal gear/talent/APL generator;
        # no second gate-specific optimizer or made-up item pool.
        joint = _source_module(source_dir / "p75_joint_search.py",
                               "p75_existing_source_joint_generator")
    finally:
        sys.path.remove(str(source_dir))
    production = _source_module(source_dir / "live_world_probe.py",
                                "p75_existing_production_native_world")

    rng = random.Random(670)
    player = base["raid"]["parties"][0]["players"][0]
    validator = joint.GearValidator(catalogue, items, enchants, base)
    best = None
    paid = 0
    failures = []
    try:
        pools, excluded = joint.candidate_pool(validator, limit=15)
        names = {int(i): str(row["name"]).strip().casefold()
                 for i, row in validator.rows.items()}
        # Bounded first contact, not a 300-second optimization claim.
        for _ in range(12):
            if paid >= 3:
                break
            try:
                candidate = _cold_joint(base, pools, rng, joint, validator, names)
                with tempfile.TemporaryDirectory(prefix="forever_p75_live_") as temp:
                    path = Path(temp) / "source-cold-joint.json"
                    path.write_text(json.dumps(candidate, allow_nan=False))
                    native = production.native_source_control(binary, path, 3)
                    live = production.run(
                        binary, path, distance=player["distanceFromTarget"],
                        iterations=3)
                parity = _source_native_world_parity(native, live, 3)
                if parity is not None:
                    raise ValueError("P7_5_" + parity)
                score = float(live["world_mean_dps"])
                if not 0 <= score < float("inf"):
                    raise ValueError("P7_5_INVALID_COUPLED_DPS")
                paid += 1
                identity = hashlib.sha256(json.dumps(
                    candidate, sort_keys=True, allow_nan=False).encode()).hexdigest()
                if best is None or score > best[0]:
                    best = (score, live, identity)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError,
                    AssertionError, subprocess.SubprocessError) as exc:
                failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    finally:
        validator.close()

    if best is None:
        return {
            "status": "FAIL",
            "reasons": ["P7_5_NO_SOURCE_LEGAL_NATIVE_WORLD_JOINT_CANDIDATE_EXECUTED"],
            "production_engine": "pinned_mythicsim_rust_gsim_2d",
            "cold_candidate_failures": failures[:6],
        }

    score, live, winner_sha = best
    reference = float(meta["reference_dps"])
    external_floor = p7_required_dps("P7.4", reference)
    return {
        "status": "FAIL",
        "reasons": [
            "P7_5_FULL_INDEPENDENT_300S_BALANCED_SEARCH_NOT_EXECUTED",
            "P7_5_FROZEN_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED",
            "P7_5_STRONGEST_ACCEPTED_COMPATIBLE_PRIOR_NOT_AVAILABLE",
            "P7_5_SOURCE_GEAR_ENCHANT_AND_APL_UNIVERSE_NOT_CERTIFIED",
        ],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": PINNED_RUST,
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": reference,
        "source_report_url": "https://api.mythicsim.com/api/forever/ranking-sims/d9d85974-a1f7-4700-ab22-2335d767a944/report",
        "winner_live_dps": score,
        "external_only_floor_dps": external_floor,
        "external_only_dps_proximity_percent": round(
            100 * min(1.0, score / external_floor), 2),
        "external_only_not_p7_5_accepted_prior_comparison": True,
        "cold_winner_request_sha256": winner_sha,
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "source_legal_cold_candidates_paid": paid,
        "cold_candidate_failures": failures[:6],
        "source_gear_talents_apl_all_free": True,
        "source_gear_native_legality_checked": True,
        "selected_validation": "3_source_native_world_fights_per_cold_joint_candidate",
        "coverage_scope_complete": False,
        "scope_provisional": True,
    }
