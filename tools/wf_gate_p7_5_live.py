"""P7.5 real cold joint source gear/talents/APL first contact with native+2D.

The same production engine and source legality generator as P7.2–P7.4 are
used. No M1 DPS-proximity claim is made before a compatible ACCEPTED prior
P7.1–P7.4 winner exists; nor is a bounded 3-fight probe a frozen holdout.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile

from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity)
from tools.wf_gate_p7_2_live import _source_module, _pinned_source_runtime


def _cold_joint(base, source, validator, pools, rng):
    """Cold source-generated whole build, never seeded with saved or prior winner."""
    original = source.player(base)
    names = {int(iid): str(row.get("name") or "").casefold()
             for iid, row in validator.engine.items()}
    for _ in range(80):
        try:
            candidate = source.make_candidate(base, pools, rng, item_names=names)
            p = source.player(candidate)
            items = p["equipment"]["items"]
            ids = [int(x["id"]) for x in items]
            enchants = [int(x.get("enchant") or 0) for x in items]
            validator.validate(ids, enchants)  # real source+Rust item legality
            if (p["equipment"] == original["equipment"]
                    or p["talentsString"] == original["talentsString"]
                    or p["rotation"] == original["rotation"]):
                continue
            return candidate
        except (source.RejectedGear, ValueError, KeyError, TypeError):
            continue
    raise ValueError("NO_SOURCE_LEGAL_INDEPENDENT_COLD_JOINT_ALTERNATIVE")


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.5")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    integration = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(integration))
    try:
        source = _source_module(integration / "p75_joint_search.py",
                                "p75_existing_source_native_joint_search")
    finally:
        sys.path.remove(str(integration))
    production = _source_module(integration / "live_world_probe.py",
                                "p75_production_native_world")
    upstream = binary.parents[2]
    catalogue = root / "data/forever/catalogue/items_2026-09-29.sqlite"
    items = upstream / "data/items.jsonl"
    enchants = upstream / "data/enchants.jsonl"
    if any(not x.is_file() for x in (catalogue, items, enchants)):
        return {"status": "BLOCKED",
                "reasons": ["P7_5_SOURCE_OR_PINNED_RUST_ITEM_DATA_MISSING"]}

    try:
        source.GearValidator.require_sqlite_catalogue(catalogue)
    except ValueError as exc:
        return {"status": "BLOCKED", "reasons": ["P7_5_" + str(exc)]}
    validator = source.GearValidator(catalogue, items, enchants, base)
    rng = random.Random(670)
    best = None
    executed = 0
    failures = []
    try:
        pools, _ = source.candidate_pool(validator, limit=15)
        distance = source.player(base)["distanceFromTarget"]
        for _ in range(3):
            try:
                candidate = _cold_joint(base, source, validator, pools, rng)
                with tempfile.TemporaryDirectory(prefix="forever_p75_live_") as tmp:
                    path = Path(tmp) / "cold-full-source-build.json"
                    path.write_text(json.dumps(candidate))
                    native = production.native_source_control(binary, path, 3,
                                                              rng_mode="balanced")
                    live = production.run(binary, path, distance=distance,
                                          iterations=3, rng_mode="balanced")
                # A high DPS number is not evidence of a correct coupled
                # timeline. Reject mismatched native/world durations and
                # damage accounting even when both means are identical.
                parity_failure = _source_native_world_parity(native, live, 3)
                if parity_failure is not None:
                    raise ValueError("P7_5_" + parity_failure)
                if (live.get("iterations_done") != 3
                        or live.get("native_damage_events", 0) <= 0
                        or live.get("native_world_ticks", 0) <= 0):
                    raise ValueError("SOURCE_JOINT_NATIVE_WORLD_EXECUTION_INCOMPLETE")
                score = float(live["world_mean_dps"])
                if not 0 <= score < float("inf"):
                    raise ValueError("SOURCE_JOINT_NATIVE_WORLD_DPS_INVALID")
                executed += 1
                candidate_sha = hashlib.sha256(json.dumps(
                    candidate, sort_keys=True).encode()).hexdigest()
                if best is None or score > best[0]:
                    best = (score, live, candidate_sha)
            except (ValueError, RuntimeError, OSError, KeyError,
                    TypeError, AssertionError, subprocess.SubprocessError) as exc:
                failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    finally:
        validator.close()
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_5_NO_SOURCE_LEGAL_JOINT_CANDIDATE_REACHED_NATIVE_WORLD"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "cold_candidate_failures": failures[:3]}

    score, live, candidate_sha = best
    external_floor = 0.99 * float(meta["reference_dps"])
    return {
        "status": "FAIL",
        "reasons": ["P7_5_FULL_300S_COLD_SEARCH_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED",
                    "P7_5_ACCEPTED_COMPATIBLE_PRIOR_REQUIRED_FOR_FINAL_DPS_FLOOR",
                    "P7_5_COMPLETE_SOURCE_GEAR_TALENTS_ROTATION_UNIVERSE_UNVERIFIED"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": PINNED_RUST,
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        # Observed DPS is real; a provisional P7.5 percent is NOT computable
        # without strongest *accepted compatible* P7.1–P7.4 prior.
        "joint_cold_world_dps": score,
        "external_reference_only_floor": external_floor,
        "final_required_dps": None,
        "cold_winner_request_sha256": candidate_sha,
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "source_legal_joint_candidates_paid": executed,
        "cold_candidate_failures": failures[:3],
        "selected_validation": "3_native_world_fights_per_cold_full_build",
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
