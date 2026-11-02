"""P7.4 first live gear discovery using real source+Rust item legality.

Only actual independently chosen, source/Rust-compatible gear loadouts scored
by the selected pinned native↔gsim 2D engine can produce a numeric PARTIAL.
This is not the 300s search or frozen 1000-fight P7.4 acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time

from tools.wf_gate_coverage import (P7_FINAL_STOCHASTIC_ITERATIONS,
                                    p7_final_stochastic_mean_passes,
                                    p7_required_dps)

from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity)
from tools.wf_gate_p7_2_live import _source_module, _pinned_source_runtime


def _cold_gear(base: dict, validator, gear_search, rng: random.Random, *,
               pool=None, enchant_pools=None):
    """Cold source-legal gear+enchant discovery; all non-equipment fields fixed."""
    if pool is None:
        pool, _ = gear_search.candidate_pool(validator, limit=15)
    original_items = base["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    reference = [item["id"] for item in original_items]
    original_enchants = [item.get("enchant") for item in original_items]
    for _ in range(60):
        ids = [rng.choice(pool[i]) for i in range(len(reference))]
        enchants = ([rng.choice(enchant_pools[i]) for i in range(len(reference))]
                    if enchant_pools is not None else original_enchants)
        # Reference-equivalent builds may be independently rediscovered, but
        # they are never used to initialize this cold search.
        if ids == reference and enchants == original_enchants:
            continue
        try:
            if enchant_pools is None:
                validator.validate(ids)
            else:
                validator.validate(ids, enchants)
        except gear_search.RejectedGear:
            continue
        candidate = gear_search._swap(base, ids)
        if enchant_pools is not None:
            actual_items = candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"]
            for item, enchant_id in zip(actual_items, enchants):
                item.pop("enchant", None)
                if enchant_id is not None:
                    item["enchant"] = int(enchant_id)
            gear_search.preflight(base, candidate)
        return candidate
    raise ValueError("NO_SOURCE_LEGAL_COLD_GEAR_OR_ENCHANT_ALTERNATIVE")


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.4")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    search_mode = os.environ.get("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    if search_mode not in ("0", "1"):
        return {"status": "BLOCKED",
                "reasons": ["P7_4_INVALID_FULL_SOURCE_SEARCH_MODE"]}
    full_search = search_mode == "1"
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
    try:
        gear_search.GearValidator.require_sqlite_catalogue(catalogue)
    except ValueError as exc:
        return {"status": "BLOCKED", "reasons": ["P7_4_" + str(exc)]}
    rng = random.Random(667)
    player = base["raid"]["parties"][0]["players"][0]
    executed = 0
    best = None
    failures = []
    seen = set()
    proposals = 0
    validator = gear_search.GearValidator(catalogue, items, enchants, base)
    search_start = time.monotonic()
    try:
        # The existing source+Rust item validator enumerates the pool once;
        # re-querying SQLite for every candidate would waste the 300s budget.
        # Full cold search must not discard source/Rust-admitted items merely
        # because their heuristic static score falls below a top-80 cutoff.
        # candidate_pool already validates all catalogue item IDs, and
        # list[:None] preserves the entire per-slot admitted pool. Enchant
        # choices are also selected from the pinned source/Rust validator;
        # unrecorded item-effect semantics are not inferred.
        pool, _ = gear_search.candidate_pool(
            validator, limit=None if full_search else 15)
        enchant_pools = (gear_search.source_enchant_pools(validator, pool)
                         if full_search else None)
        while (time.monotonic() - search_start < 300.0
               if full_search else proposals < 3):
            proposals += 1
            try:
                candidate = _cold_gear(
                    base, validator, gear_search, rng, pool=pool,
                    enchant_pools=enchant_pools)
                candidate_sha = hashlib.sha256(json.dumps(
                    candidate, sort_keys=True).encode()).hexdigest()
                if candidate_sha in seen:
                    continue  # only distinct legal loadouts are paid
                seen.add(candidate_sha)
                with tempfile.TemporaryDirectory(prefix="forever_p74_live_") as tmp:
                    path = Path(tmp) / "cold-source-gear.json"
                    path.write_text(json.dumps(candidate))
                    native = production.native_source_control(
                        binary, path, 3, rng_mode="balanced")
                    live = production.run(
                        binary, path, distance=player["distanceFromTarget"],
                        iterations=3, rng_mode="balanced")
                    parity_failure = _source_native_world_parity(native, live, 3)
                    if parity_failure is not None:
                        raise ValueError("SOURCE_NATIVE_WORLD_PARITY_FAILED:" + parity_failure)
                if (live.get("iterations_done") != 3
                        or live.get("native_damage_events", 0) <= 0
                        or live.get("native_world_ticks", 0) <= 0):
                    raise ValueError("SOURCE_GEAR_NATIVE_WORLD_INCOMPLETE")
                score = float(live["world_mean_dps"])
                if not 0 <= score < float("inf"):
                    raise ValueError("SOURCE_GEAR_INVALID_WORLD_DPS")
                executed += 1
                if best is None or score > best[0]:
                    best = (score, live, candidate_sha, candidate)
            except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
                    TypeError, AssertionError, subprocess.SubprocessError) as exc:
                failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    finally:
        validator.close()
    search_wall_s = time.monotonic() - search_start
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_4_NO_SOURCE_LEGAL_NATIVE_WORLD_GEAR_CANDIDATE_EXECUTED"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "search_wall_s": search_wall_s,
                "source_candidate_failures": failures[:4]}

    score, live, candidate_sha, frozen_winner = best
    complete_search = full_search and 300.0 <= search_wall_s <= 301.0
    final = {}
    if complete_search:
        # Freeze the genuine paid winner BEFORE the independent stochastic
        # final. The final is never used to rerank or mutate cold candidates.
        try:
            with tempfile.TemporaryDirectory(prefix="forever_p74_frozen_") as tmp:
                frozen_path = Path(tmp) / "frozen-gear-winner.json"
                frozen_path.write_text(json.dumps(frozen_winner))
                frozen_sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
                n = P7_FINAL_STOCHASTIC_ITERATIONS
                native = production.native_source_control(
                    binary, frozen_path, n, rng_mode="stochastic")
                world = production.run(
                    binary, frozen_path, distance=player["distanceFromTarget"],
                    iterations=n, rng_mode="stochastic")
                mismatch = _source_native_world_parity(
                    native, world, n, expected_raw_sha=frozen_sha)
                if mismatch is not None:
                    raise ValueError("FROZEN_STOCHASTIC_NATIVE_WORLD_PARITY:" + mismatch)
                native_dps = float(native["native_dps"])
                world_dps = float(world["world_mean_dps"])
                final = {
                    "frozen_request_raw_sha256": frozen_sha,
                    "frozen_stochastic_iterations": n,
                    "frozen_stochastic_native_dps": native_dps,
                    "frozen_stochastic_world_dps": world_dps,
                    "frozen_stochastic_world_damage_events": int(world["native_damage_events"]),
                    "frozen_stochastic_world_boundaries": int(world["native_world_ticks"]),
                    "frozen_stochastic_reference_floor_met": (
                        p7_final_stochastic_mean_passes(
                            "P7.4", world_dps, float(meta["reference_dps"]),
                            iterations=n, stochastic=True)
                        and p7_final_stochastic_mean_passes(
                            "P7.4", native_dps, float(meta["reference_dps"]),
                            iterations=n, stochastic=True)),
                }
        except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
                TypeError, AssertionError, subprocess.SubprocessError) as exc:
            final = {"frozen_stochastic_failure":
                     type(exc).__name__ + ":" + str(exc)[:180]}

    reasons = ["P7_4_COMPLETE_SOURCE_GEAR_UNIVERSE_AND_EFFECTS_NOT_VERIFIED",
               "P7_4_SAVED_REPORT_UI_FIELD_AUDIT_UNVERIFIED"]
    if not full_search:
        reasons.append("P7_4_FULL_INDEPENDENT_300S_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED")
    elif search_wall_s < 300.0:
        reasons.append("P7_4_300S_SEARCH_NOT_COMPLETED")
    elif search_wall_s > 301.0:
        reasons.append("P7_4_SEARCH_BUDGET_OVERRUN")
    if "frozen_stochastic_iterations" not in final:
        reasons.append("P7_4_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED")
    elif not final["frozen_stochastic_reference_floor_met"]:
        reasons.append("P7_4_FROZEN_STOCHASTIC_DPS_BELOW_REFERENCE_FLOOR")
    return {
        "status": "FAIL",
        "reasons": reasons,
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": PINNED_RUST,
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "required_reference_dps": p7_required_dps(
            "P7.4", float(meta["reference_dps"])),
        "cold_winner_request_sha256": candidate_sha,
        "winner_live_dps": score,
        "search_wall_s": search_wall_s,
        "independent_300s_search_requested": full_search,
        "independent_300s_search_completed": complete_search,
        "cold_unique_source_requests": len(seen),
        **final,
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "source_legal_cold_candidates_paid": executed,
        "source_candidate_failures": failures[:4],
        "source_gear_and_native_item_legality_applied": True,
        "source_fixed_rotation_and_talents": True,
        "selected_validation": "3_native_world_fights_per_cold_gear_candidate",
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
