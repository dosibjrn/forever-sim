"""P7.3 first live source talent discovery through real pinned Rust↔gsim 2D.

Uses the existing native source talent-legal cold allocation generator, not a
second talent optimizer or DPS model. Fixed gear and APL are never altered.
Short native-world probes yield only a provisional numeric DPS PARTIAL/FAIL;
full 300-second search and 1,000-fight frozen holdout remain unexecuted.
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

from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity)
from tools.wf_gate_p7_2_live import (_source_module, _pinned_source_runtime)


def _cold_talents(base: dict, rng: random.Random, source):
    candidate = copy.deepcopy(base)
    old = base["raid"]["parties"][0]["players"][0]
    player = candidate["raid"]["parties"][0]["players"][0]
    allocation = source.random_build(rng)  # original source-legal native generator
    if not source.validate(allocation):
        raise ValueError("COLD_SOURCE_TALENT_ALLOCATION_ILLEGAL")
    selected = source.encode(allocation)
    if selected == old.get("talentsString"):
        raise ValueError("COLD_SOURCE_TALENTS_IDENTICAL_TO_REFERENCE")
    player["talentsString"] = selected
    if (player["equipment"] != old["equipment"]
            or player["rotation"] != old["rotation"]):
        raise ValueError("TALENT_ONLY_COLD_SEARCH_CHANGED_FIXED_DIMENSIONS")
    return candidate


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.3")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    search_dir = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(search_dir))
    try:
        # p73_talent_search_v2 itself calls the original talent_schema_druid
        # source constraints (tier caps/prerequisites), no invented point tree.
        source = _source_module(search_dir / "p73_talent_search_v2.py",
                                "p73_existing_native_talent_generator")
    finally:
        sys.path.remove(str(search_dir))
    production = _source_module(
        search_dir / "live_world_probe.py", "p73_production_native_world")
    player = base["raid"]["parties"][0]["players"][0]
    original = player.get("talentsString")
    rng = random.Random(647003)
    best = None
    executed = 0
    failures = []
    for _ in range(3):
        try:
            candidate = _cold_talents(base, rng, source)
            with tempfile.TemporaryDirectory(prefix="forever_p73_live_") as tmp:
                path = Path(tmp) / "cold-source-talent.json"
                path.write_text(json.dumps(candidate))
                native = production.native_source_control(binary, path, 3,
                                                          rng_mode="balanced")
                live = production.run(
                    binary, path, distance=player["distanceFromTarget"],
                    iterations=3, rng_mode="balanced")
                parity_failure = _source_native_world_parity(native, live, 3)
                if parity_failure is not None:
                    raise ValueError("SOURCE_NATIVE_WORLD_PARITY_FAILED:" + parity_failure)
            if (live.get("iterations_done") != 3
                    or live.get("native_damage_events", 0) <= 0
                    or live.get("native_world_ticks", 0) <= 0):
                raise ValueError("SOURCE_NATIVE_WORLD_TALENT_EXECUTION_INCOMPLETE")
            score = float(live["world_mean_dps"])
            if not 0 <= score < float("inf"):
                raise ValueError("SOURCE_TALENT_LIVE_DPS_INVALID")
            executed += 1
            sha = hashlib.sha256(json.dumps(
                candidate, sort_keys=True).encode()).hexdigest()
            if best is None or score > best[0]:
                best = (score, live, sha)
        except (ValueError, RuntimeError, OSError, TypeError,
                KeyError, subprocess.SubprocessError, AssertionError) as exc:
            failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_3_NO_EXECUTED_SOURCE_LEGAL_COLD_TALENT_WORLD_CANDIDATE"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "cold_candidate_failures": failures[:3]}

    score, live, candidate_sha = best
    return {
        "status": "FAIL",
        "reasons": ["P7_3_FULL_INDEPENDENT_300S_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED",
                    "P7_3_SOURCE_TALENT_PROFILE_COVERAGE_NOT_VERIFIED"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": PINNED_RUST,
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "fixed_rotation_and_gear": True,
        "source_original_talents": original,
        "cold_winner_request_sha256": candidate_sha,
        "winner_live_dps": score,
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "source_legal_cold_candidates_paid": executed,
        "cold_candidate_failures": failures[:3],
        "selected_validation": "3_native_world_fights_per_cold_talent_candidate",
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
