"""P7.3 live talent discovery through the selected native engine and gsim 2D.

Forever proposes talent-string candidates without local rank, tree, or
prerequisite rules. MythicSim native VALID/INVALID/UNSUPPORTED/ERROR outcomes
are authoritative. Fixed gear and APL are never altered. Bounded probes remain
a default FAIL; explicit full search runs an independent 300-second
balanced-RNG search, then a frozen 1,000-stochastic-fight native and 2D holdout.
Saved report UI/source coverage still needs verification.
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

from src.engine_client import native_talent_proposals

from tools.wf_gate_coverage import (P7_FINAL_STOCHASTIC_ITERATIONS,
                                    p7_final_stochastic_mean_passes,
                                    p7_required_dps,
                                    p7_search_window_completed)
from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity, _executed_p7_runtime_proof)
from tools.wf_gate_p7_2_live import (_source_module, _pinned_source_runtime)


def _cold_talents(base: dict, rng: random.Random, proposals, *, elite=None):
    """Propose a cold or paid-parent talent string; native owns legality.

    The saved request supplies only the string shape/search budget. A paid
    elite is admissible only after this run measured it through native+2D.
    No Python talent schema, rank cap, tree budget, or prerequisite check runs.
    """
    candidate = copy.deepcopy(base)
    old = base["raid"]["parties"][0]["players"][0]
    player = candidate["raid"]["parties"][0]["players"][0]
    if elite is None:
        selected = proposals.cold_talent_string(old["talentsString"], rng)
    else:
        paid = elite["raid"]["parties"][0]["players"][0]
        if (paid["equipment"] != old["equipment"]
                or paid["rotation"] != old["rotation"]):
            raise ValueError("P73_PAID_ELITE_CHANGED_FIXED_DIMENSIONS")
        # Local mutations and full restarts are proposals only. MythicSim
        # decides whether the resulting talent string is VALID or refused.
        selected = (proposals.mutate_talent_string(paid["talentsString"], rng)
                    if rng.random() < 0.70
                    else proposals.cold_talent_string(paid["talentsString"], rng))
    if not isinstance(selected, str) or not selected:
        raise ValueError("P73_NATIVE_TALENT_PROPOSAL_NOT_STRING")
    player["talentsString"] = selected
    if (player["equipment"] != old["equipment"]
            or player["rotation"] != old["rotation"]):
        raise ValueError("TALENT_ONLY_COLD_SEARCH_CHANGED_FIXED_DIMENSIONS")
    return candidate


def _paid_elite_choice(elites, rng, proposal_index):
    """Explore this run's native+2D-paid elites, never the reference."""
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
        production = _source_module(
            search_dir / "live_world_probe.py", "p73_production_native_world")
    finally:
        sys.path.remove(str(search_dir))
    player = base["raid"]["parties"][0]["players"][0]
    original = player.get("talentsString")
    rng = random.Random(647003)
    best = None
    elites = []  # top native+2D-paid requests scored with balanced RNG
    executed = 0
    proposals = 0
    seen = set()
    failures = []
    native_invalid_candidates = 0
    native_unsupported_candidates = 0
    native_unscored_candidates = 0
    native_execution_errors = 0
    world_execution_errors = 0
    native_refusal_samples = []
    native_unscored_samples = []
    search_start = time.monotonic()
    search_deadline = search_start + 300.0
    # Default: three real source/native/world bounded candidates. Heavy:
    # independent 300s cold search with the identical genuine evaluator.
    while (time.monotonic() < search_deadline
           if full_search else proposals < 3):
        proposals += 1
        try:
            # Four of five proposals exploit this run's top native+2D-paid
            # candidates; every fifth proposal remains an independent cold draw.
            elite = (_paid_elite_choice(elites, rng, proposals)
                     if full_search else None)
            candidate = _cold_talents(
                base, rng, native_talent_proposals, elite=elite)
            sha = hashlib.sha256(json.dumps(
                candidate, sort_keys=True).encode()).hexdigest()
            if sha in seen:
                continue  # repeated requests are not new paid candidates
            seen.add(sha)
            with tempfile.TemporaryDirectory(prefix="forever_p73_live_") as tmp:
                path = Path(tmp) / "cold-native-talent.json"
                path.write_text(json.dumps(candidate))
                try:
                    native = production.native_source_control(
                        binary, path, 3, rng_mode="balanced")
                except Exception as exc:
                    native_status = str(getattr(exc, "status", "")).upper()
                    sample = (native_status or "ERROR") + ":" + (
                        str(getattr(exc, "reason", exc))[:180])
                    if native_status == "INVALID":
                        native_invalid_candidates += 1
                        native_refusal_samples.append(sample)
                    elif native_status == "UNSUPPORTED":
                        native_unsupported_candidates += 1
                        native_refusal_samples.append(sample)
                    elif native_status == "UNSCORED":
                        native_unscored_candidates += 1
                        native_unscored_samples.append(sample)
                    else:
                        native_execution_errors += 1
                        failures.append("NATIVE_EXECUTION_ERROR:" + sample)
                    # A native refusal is authoritative; do not run a Python
                    # legality fallback or send the refused candidate to 2D.
                    continue
                try:
                    live = production.run(
                        binary, path, distance=player["distanceFromTarget"],
                        iterations=3, rng_mode="balanced")
                    parity_failure = _source_native_world_parity(native, live, 3)
                    if parity_failure is not None:
                        raise ValueError(
                            "SOURCE_NATIVE_WORLD_PARITY_FAILED:" + parity_failure)
                    if (live.get("iterations_done") != 3
                            or live.get("native_damage_events", 0) <= 0
                            or live.get("native_world_ticks", 0) <= 0):
                        raise ValueError(
                            "SOURCE_NATIVE_WORLD_TALENT_EXECUTION_INCOMPLETE")
                    score = float(live["world_mean_dps"])
                    if not 0 <= score < float("inf"):
                        raise ValueError("SOURCE_TALENT_LIVE_DPS_INVALID")
                except Exception as exc:
                    world_execution_errors += 1
                    failures.append(
                        "WORLD_EXECUTION_ERROR:" + type(exc).__name__ + ":" +
                        str(exc)[:180])
                    continue
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
    )
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_3_NO_NATIVE_WORLD_SCORED_COLD_TALENT_CANDIDATE"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "search_wall_s": search_wall_s,
                "cold_unique_source_requests": len(seen),
                "native_world_scored_candidates_paid": executed,
                "native_invalid_candidates": native_invalid_candidates,
                "native_unsupported_candidates": native_unsupported_candidates,
                "native_unscored_candidates": native_unscored_candidates,
                "native_execution_errors": native_execution_errors,
                "world_execution_errors": world_execution_errors,
                "native_refusal_samples": native_refusal_samples[:4],
                "native_unscored_samples": native_unscored_samples[:4],
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
        # Freeze the winning native-scored request before an independent
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
    # gate requires executable native-scored candidates, not an exhaustive
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
        "native_invalid_candidates": native_invalid_candidates,
        "native_unsupported_candidates": native_unsupported_candidates,
        "native_unscored_candidates": native_unscored_candidates,
        "native_execution_errors": native_execution_errors,
        "world_execution_errors": world_execution_errors,
        "native_refusal_samples": native_refusal_samples[:4],
        "native_unscored_samples": native_unscored_samples[:4],
        **final,
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "native_world_scored_candidates_paid": executed,
        "cold_candidate_failures": failures[:4],
        "selected_validation": "3_native_world_fights_per_cold_talent_candidate",
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
