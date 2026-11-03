"""P7.3 first live source talent discovery through real pinned Rust↔gsim 2D.

Uses the existing native source talent-legal cold allocation generator, not a
second talent optimizer or DPS model. Fixed gear and APL are never altered.
Bounded probes remain a default FAIL; explicit full search runs an independent
300-second balanced-RNG cold talent search, then a frozen 1,000-stochastic-fight
native and 2D holdout. Saved report UI/source coverage still needs verification.
"""
from __future__ import annotations

import copy
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
                                    p7_required_dps,
                                    p7_search_window_completed)
from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity, _executed_p7_runtime_proof)
from tools.wf_gate_p7_2_live import (_source_module, _pinned_source_runtime)


def _cold_talents(base: dict, rng: random.Random, source, *, elite=None):
    """Cold source draw or mutation of this run's already paid legal winner.

    Never use the saved reference allocation as a search seed. A paid elite
    is admissible only after the caller has measured it in native+2D.
    """
    candidate = copy.deepcopy(base)
    old = base["raid"]["parties"][0]["players"][0]
    player = candidate["raid"]["parties"][0]["players"][0]
    if elite is None:
        allocation = source.random_build(rng)
    else:
        paid = elite["raid"]["parties"][0]["players"][0]
        if (paid["equipment"] != old["equipment"]
                or paid["rotation"] != old["rotation"]):
            raise ValueError("P73_PAID_ELITE_CHANGED_FIXED_DIMENSIONS")
        paid_ranks = source.parse(paid["talentsString"])
        if not source.validate(paid_ranks):
            raise ValueError("P73_PAID_ELITE_SOURCE_TALENTS_ILLEGAL")
        # Source's own legal neighbor move or locally biased full draw.
        # Keep a separate cold draw every fifth proposal in the caller.
        allocation = (source.edit_neighbors(paid_ranks, rng)
                      if rng.random() < 0.70
                      else source.random_build(rng, paid_ranks))
    if not source.validate(allocation):
        raise ValueError("COLD_SOURCE_TALENT_ALLOCATION_ILLEGAL")
    selected = source.encode(allocation)
    # random_build(rng) is independent of the saved allocation. A sampled
    # allocation equal to the reference is still a legal cold discovery; the
    # caller deduplicates source requests before the paid native/world score.
    player["talentsString"] = selected
    if (player["equipment"] != old["equipment"]
            or player["rotation"] != old["rotation"]):
        raise ValueError("TALENT_ONLY_COLD_SEARCH_CHANGED_FIXED_DIMENSIONS")
    return candidate


def _paid_elite_choice(elites, rng, proposal_index):
    """Explore one of this run's source-legal paid elites, never the reference."""
    if proposal_index % 5 == 0 or not elites:
        return None  # independent source-cold restart
    return rng.choice(elites[:min(18, len(elites))])[1]


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.3")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    search_mode = os.environ.get("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    if search_mode not in ("0", "1"):
        return {"status": "BLOCKED",
                "reasons": ["P7_3_INVALID_FULL_SOURCE_SEARCH_MODE"]}
    full_search = search_mode == "1"

    search_dir = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(search_dir))
    try:
        # Reuse the original native talent schema's tiers and prerequisites.
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
    elites = []  # top source-legal requests scored with balanced RNG
    executed = 0
    proposals = 0
    seen = set()
    failures = []
    search_start = time.monotonic()
    search_deadline = search_start + 300.0
    # Default: three real source/native/world bounded candidates. Heavy:
    # independent 300s cold search with the identical genuine evaluator.
    while (time.monotonic() < search_deadline
           if full_search else proposals < 3):
        proposals += 1
        try:
            # Four of five proposals exploit one of this run's top paid
            # legal candidates, not exclusively its current global best.
            # This restores the existing native source P7.3 optimizer's
            # diverse paid-elite population (top 18 of 22); every fifth
            # proposal remains independent from the reference/source grammar.
            # Only the balanced-scored paid elite archive may guide proposals.
            elite = (_paid_elite_choice(elites, rng, proposals)
                     if full_search else None)
            candidate = _cold_talents(base, rng, source, elite=elite)
            sha = hashlib.sha256(json.dumps(
                candidate, sort_keys=True).encode()).hexdigest()
            if sha in seen:
                continue  # repeated allocations are not new paid candidates
            seen.add(sha)
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
            elites.append((score, candidate))
            elites.sort(key=lambda item: item[0], reverse=True)
            del elites[22:]
            if best is None or score > best[0]:
                best = (score, live, sha, candidate)
        except (ValueError, RuntimeError, OSError, TypeError,
                KeyError, subprocess.SubprocessError, AssertionError) as exc:
            failures.append(type(exc).__name__ + ":" + str(exc)[:180])

    search_observed_at = time.monotonic()
    search_wall_s = search_observed_at - search_start
    search_window_met = p7_search_window_completed(
        full_search=full_search, elapsed_seconds=search_wall_s,
    )    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_3_NO_EXECUTED_SOURCE_LEGAL_COLD_TALENT_WORLD_CANDIDATE"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "search_wall_s": search_wall_s,
                "independent_300s_search_requested": full_search,
                "independent_300s_search_completed": search_window_met,
                "search_window_met": search_window_met,
                "search_deadline_observed_elapsed_s": round(search_wall_s, 6),
                "cold_candidate_failures": failures[:4]}

    # Freeze the best balanced-scored candidate BEFORE the independent
    # stochastic acceptance holdout. Stochastic results never rank candidates.
    score, live, candidate_sha, frozen_winner = best
    screen_score = score
    winner_selection = "best_balanced_live_screen"
    complete_search = search_window_met
    final = {}
    if complete_search:
        # Freeze the winning source-legal request before an independent
        # stochastic final. The holdout cannot rank or mutate candidates.
        try:
            with tempfile.TemporaryDirectory(prefix="forever_p73_frozen_") as tmp:
                frozen_path = Path(tmp) / "frozen-talent-winner.json"
                frozen_path.write_text(json.dumps(frozen_winner))
                frozen_sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
                n = P7_FINAL_STOCHASTIC_ITERATIONS
                native = production.native_source_control(
                    binary, frozen_path, n, rng_mode="stochastic")
                world = production.run(
                    binary, frozen_path, distance=player["distanceFromTarget"],
                    iterations=n, rng_mode="stochastic")
                parity_failure = _source_native_world_parity(
                    native, world, n, expected_raw_sha=frozen_sha)
                if parity_failure is not None:
                    raise ValueError("FROZEN_STOCHASTIC_NATIVE_WORLD_PARITY:" + parity_failure)
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
                            "P7.3", world_dps, float(meta["reference_dps"]),
                            iterations=n, stochastic=True)
                        and p7_final_stochastic_mean_passes(
                            "P7.3", native_dps, float(meta["reference_dps"]),
                            iterations=n, stochastic=True)),
                }
        except (ValueError, RuntimeError, OSError, TypeError,
                KeyError, subprocess.SubprocessError, AssertionError) as exc:
            final = {"frozen_stochastic_failure":
                     type(exc).__name__ + ":" + str(exc)[:180]}

    # The original saved report source is pinned by shared preflight; the
    # gate requires executable source-legal candidates, not an exhaustive
    # enumeration or a second interactive UI capture.
    reasons = []
    if not full_search:
        reasons.append("P7_3_FULL_INDEPENDENT_300S_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED")
    elif not search_window_met:
        reasons.append("P7_3_300S_SEARCH_WINDOW_NOT_COMPLETED")
    if "frozen_stochastic_iterations" not in final:
        reasons.append("P7_3_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED")
    elif not final["frozen_stochastic_reference_floor_met"]:
        reasons.append("P7_3_FROZEN_STOCHASTIC_DPS_BELOW_REFERENCE_FLOOR")
    return {
        "status": "PASS" if not reasons else "FAIL",
        **(_executed_p7_runtime_proof(
               "P7.3", final["frozen_request_raw_sha256"],
               engine_revision=meta.get("selected_engine_revision", PINNED_RUST))
           if not reasons else {}),
        "reasons": reasons,
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "required_reference_dps": p7_required_dps(
            "P7.3", float(meta["reference_dps"])),
        "fixed_rotation_and_gear": True,
        "source_original_talents": original,
        # Preserve the *actual* paid winner allocation, not just the hash.
        # Distinct SHA + identical frozen DPS is otherwise impossible to
        # triage as unchanged effective talents versus ignored runtime ranks.
        "cold_winner_talents": frozen_winner["raid"]["parties"][0]["players"][0]["talentsString"],
        "cold_winner_request_sha256": candidate_sha,
        "winner_live_dps": score,
        "winner_screen_dps": screen_score,
        "winner_selection": winner_selection,
        "paid_stochastic_finalists": 0,
        "early_stochastic_finalists_paid": 0,
        "stochastic_parent_proposals": 0,
        "paid_stochastic_finalist_failures": [],
        "search_wall_s": search_wall_s,
        "independent_300s_search_requested": full_search,
        "independent_300s_search_completed": complete_search,
        "search_window_met": search_window_met,
        "search_deadline_observed_elapsed_s": round(search_wall_s, 6),
        "cold_unique_source_requests": len(seen),
        **final,
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "source_legal_cold_candidates_paid": executed,
        "cold_candidate_failures": failures[:4],
        "selected_validation": "3_native_world_fights_per_cold_talent_candidate",
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
