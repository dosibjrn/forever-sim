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
                                    p7_required_dps)
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


def _p73_paid_parent_pool(balanced_elites, stochastic_finalists, proposal_index):
    """Use paid native+2D stochastic feedback for most local talent proposals.

    Three balanced fights can misrank a talent allocation against stochastic
    DPS. Only this run's independently executed source-legal contenders enter
    the stochastic parent pool. Every third exploitation retains the balanced
    elite diversity; every fifth proposal is still a wholly cold source draw.
    """
    if not stochastic_finalists or proposal_index % 3 == 0:
        return balanced_elites
    return sorted(
        ((row[0], row[3]) for row in stochastic_finalists),
        key=lambda item: item[0], reverse=True)


def _p73_early_rerank_due(elapsed_s, attempted_count):
    """Pay for at most six early native+2D stochastic finalists, 120–240 s.

    Reranks are charged to the existing 300-second search, not the separate
    frozen 1,000-fight stochastic holdout. Failed attempts consume a slot.
    """
    return (120.0 <= elapsed_s < 240.0 and attempted_count < 6
            and elapsed_s >= 120.0 + 20.0 * attempted_count)


def _paid_stochastic_finalist(production, binary, request: dict, distance: float):
    """Re-rank a paid live elite on separate stochastic seeds, not acceptance.

    The 3-balanced-fight screen is only an exploration heuristic. This uses
    the same genuine Rust/native and 2D pair as the final holdout; a different
    seed avoids ranking directly on the final holdout's stochastic sample.
    """
    rerank_request = copy.deepcopy(request)
    rerank_request["simOptions"]["randomSeed"] = "1947003"
    with tempfile.TemporaryDirectory(prefix="forever_p73_rerank_") as tmp:
        path = Path(tmp) / "source-legal-talent-finalist.json"
        path.write_text(json.dumps(rerank_request))
        native = production.native_source_control(
            binary, path, 24, rng_mode="balanced")
        live = production.run(binary, path, distance=distance, iterations=24,
                              rng_mode="balanced")
        failure = _source_native_world_parity(native, live, 24)
        if failure is not None:
            raise ValueError("P73_FINALIST_NATIVE_WORLD_PARITY:" + failure)
    if (live.get("iterations_done") != 24
            or live.get("native_damage_events", 0) <= 0
            or live.get("native_world_ticks", 0) <= 0):
        raise ValueError("P73_FINALIST_LIVE_PAIR_INCOMPLETE")
    score = float(live["world_mean_dps"])
    if not 0 <= score < float("inf"):
        raise ValueError("P73_FINALIST_LIVE_DPS_INVALID")
    return score, live


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
    elites = []  # top source-legal requests already paid in native+2D
    reranked = []  # independently paid stochastic native+world finalists
    rerank_seen = set()
    rerank_failures = []
    early_stochastic_finalists_paid = 0
    stochastic_parent_proposals = 0
    executed = 0
    proposals = 0
    seen = set()
    failures = []
    search_start = time.monotonic()
    # Default: three real source/native/world bounded candidates. Heavy:
    # independent 300s cold search with the identical genuine evaluator.
    while (time.monotonic() - search_start < 300.0
           if full_search else proposals < 3):
        # Restore the native optimizer's paid finalist rerank inside the
        # SAME 300-second cold search, without seeding the saved reference.
        rerank_elapsed = (time.monotonic() - search_start
                          if full_search else 0.0)
        early_rerank = (_p73_early_rerank_due(
            rerank_elapsed, len(rerank_seen)) if full_search else False)
        if (full_search and
                (240.0 <= rerank_elapsed < 295.0 or early_rerank)):
            pending = next(
                ((sc, req, hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest())
                 for sc, req in elites
                 if hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
                 not in rerank_seen), None)
            if pending is not None:
                screen_dps, contender, contender_sha = pending
                rerank_seen.add(contender_sha)
                try:
                    rerank_dps, rerank_live = _paid_stochastic_finalist(
                        production, binary, contender,
                        player["distanceFromTarget"])
                    reranked.append((rerank_dps, rerank_live, contender_sha,
                                     contender, screen_dps))
                    if early_rerank:
                        early_stochastic_finalists_paid += 1
                except (ValueError, RuntimeError, OSError, TypeError,
                        KeyError, subprocess.SubprocessError, AssertionError) as exc:
                    rerank_failures.append(type(exc).__name__ + ":" + str(exc)[:180])
                continue
        proposals += 1
        try:
            # Four of five proposals exploit one of this run's top paid
            # legal candidates, not exclusively its current global best.
            # This restores the existing native source P7.3 optimizer's
            # diverse paid-elite population (top 18 of 22); every fifth
            # proposal remains independent from the reference/source grammar.
            parent_pool = (_p73_paid_parent_pool(elites, reranked, proposals)
                           if full_search else elites)
            if (full_search and parent_pool is not elites
                    and proposals % 5 != 0):
                stochastic_parent_proposals += 1
            elite = (_paid_elite_choice(parent_pool, rng, proposals)
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

    search_wall_s = time.monotonic() - search_start
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_3_NO_EXECUTED_SOURCE_LEGAL_COLD_TALENT_WORLD_CANDIDATE"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "search_wall_s": search_wall_s,
                "cold_candidate_failures": failures[:4]}

    # Freeze the best independently paid stochastic finalist, not merely
    # the best 3-balanced-fight screen. The 1,000-fight holdout never ranks.
    if reranked:
        score, live, candidate_sha, frozen_winner, screen_score = max(
            reranked, key=lambda item: item[0])
        winner_selection = "paid_24_balanced_live_native_finalist"
    else:
        score, live, candidate_sha, frozen_winner = best
        screen_score = score
        winner_selection = "three_balanced_live_screen_only"
    complete_search = full_search and 300.0 <= search_wall_s <= 301.0
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
    elif search_wall_s < 300.0:
        reasons.append("P7_3_300S_SEARCH_NOT_COMPLETED")
    elif search_wall_s > 301.0:
        reasons.append("P7_3_SEARCH_BUDGET_OVERRUN")
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
        "paid_stochastic_finalists": len(reranked),
        "early_stochastic_finalists_paid": early_stochastic_finalists_paid,
        "stochastic_parent_proposals": stochastic_parent_proposals,
        "paid_stochastic_finalist_failures": rerank_failures[:4],
        "search_wall_s": search_wall_s,
        "independent_300s_search_requested": full_search,
        "independent_300s_search_completed": complete_search,
        "cold_unique_source_requests": len(seen),
        **final,
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "source_legal_cold_candidates_paid": executed,
        "cold_candidate_failures": failures[:4],
        "selected_validation": "3_native_world_fights_per_cold_talent_candidate",
        "search_rng_mode": "balanced",
        "finalist_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
