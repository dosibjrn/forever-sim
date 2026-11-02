"""P7.4 first live gear discovery using real source+Rust item legality.

Only actual independently chosen, source/Rust-compatible gear loadouts scored
by the selected pinned native↔gsim 2D engine can produce a numeric PARTIAL.
This is not the 300s search or frozen 1000-fight P7.4 acceptance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile

from tools.wf_gate_p7_1_live import PINNED_RUST, SAVED_BALANCE_RAW_SHA
from tools.wf_gate_p7_2_live import (_source_module, _pinned_source_runtime,
                                     _run_source_coupled_candidate)


def _cold_gear(base: dict, validator, gear_search, rng: random.Random):
    """Select an independently sourced full loadout; never seed saved winner."""
    pool, _ = gear_search.candidate_pool(validator, limit=15)
    reference = [x["id"] for x in base["raid"]["parties"][0]["players"][0]["equipment"]["items"]]
    for _ in range(60):
        ids = [rng.choice(pool[i]) for i in range(len(reference))]
        if ids == reference:
            continue
        try:
            validator.validate(ids)  # actual source+Rust item rules
        except gear_search.RejectedGear:
            continue
        candidate = gear_search._swap(base, ids)  # fixed-dimension source preflight
        return candidate
    raise ValueError("NO_SOURCE_LEGAL_COLD_GEAR_ALTERNATIVE")


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.4")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    source_dir = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(source_dir))
    try:
        gear_search = _source_module(source_dir / "p74_gear_search.py",
                                     "p74_existing_source_native_gear_search")
    finally:
        sys.path.remove(str(source_dir))
    production = _source_module(source_dir / "live_world_probe.py",
                                "p74_production_native_world")
    upstream = binary.parents[2]
    catalogue = root / "data/forever/catalogue/items_2026-09-29.sqlite"
    items = upstream / "data/items.jsonl"
    enchants = upstream / "data/enchants.jsonl"
    if any(not path.is_file() for path in (catalogue, items, enchants)):
        return {"status": "BLOCKED",
                "reasons": ["P7_4_PINNED_SOURCE_OR_NATIVE_ITEM_DATABASE_MISSING"]}
    rng = random.Random(667)
    player = base["raid"]["parties"][0]["players"][0]
    executed = 0
    best = None
    failures = []
    validator = gear_search.GearValidator(catalogue, items, enchants, base)
    try:
        # No item ID is invented. A candidate is generated cold, checked
        # against the real source catalogue AND pinned native item schema.
        for _ in range(3):
            try:
                candidate = _cold_gear(base, validator, gear_search, rng)
                with tempfile.TemporaryDirectory(prefix="forever_p74_live_") as tmp:
                    path = Path(tmp) / "cold-source-gear.json"
                    path.write_text(json.dumps(candidate))
                    live = _run_source_coupled_candidate(
                        production, binary, path,
                        distance=player["distanceFromTarget"], iterations=3)
                score = float(live["world_mean_dps"])
                if not 0 <= score < float("inf"):
                    raise ValueError("SOURCE_GEAR_INVALID_WORLD_DPS")
                executed += 1
                sha = hashlib.sha256(json.dumps(
                    candidate, sort_keys=True).encode()).hexdigest()
                if best is None or score > best[0]:
                    best = (score, live, sha)
            except (ValueError, RuntimeError, OSError, KeyError,
                    TypeError, AssertionError, subprocess.SubprocessError) as exc:
                failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    finally:
        validator.close()
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_4_NO_SOURCE_LEGAL_NATIVE_WORLD_GEAR_CANDIDATE_EXECUTED"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "source_candidate_failures": failures[:3]}
    score, live, candidate_sha = best
    return {
        "status": "FAIL",
        "reasons": ["P7_4_FULL_INDEPENDENT_300S_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED",
                    "P7_4_COMPLETE_SOURCE_GEAR_UNIVERSE_AND_EFFECTS_NOT_VERIFIED"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": PINNED_RUST,
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "cold_winner_request_sha256": candidate_sha,
        "winner_live_dps": score,
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "source_legal_cold_candidates_paid": executed,
        "source_candidate_failures": failures[:3],
        "source_gear_and_native_item_legality_applied": True,
        "source_fixed_rotation_and_talents": True,
        "selected_validation": "3_native_world_fights_per_cold_gear_candidate",
        "coverage_scope_complete": False,
    }
