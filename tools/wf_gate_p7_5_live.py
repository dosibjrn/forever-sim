"""P7.5 real cold joint source gear/talents/APL first contact with native+2D.

The same production engine and source legality generator as P7.2–P7.4 are
used. No M1 DPS-proximity claim is made before a compatible ACCEPTED prior
P7.1–P7.4 winner exists; nor is a bounded 3-fight probe a frozen holdout.
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
                                    p7_required_dps)
from tools.wf_gate_p7_5_prior import strongest_accepted_prior
# Same native+2D paid stochastic scorer and budget guard as accepted P7.4.
from tools.wf_gate_p7_4_live import (
    _paid_gear_stochastic_finalist, _paid_step_has_budget,
    _p74_early_rerank_due, _next_p74_confirmation,
    _next_p74_deep_confirmation, _freeze_paid_p74_winner)
from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _executed_p7_runtime_proof,
                                     _source_native_world_parity)
from tools.wf_gate_p7_2_live import _source_module, _pinned_source_runtime


def _cold_joint(base, source, validator, pools, rng, *, elite=None, enchant_pools=None, repair_axes=None):
    """Legal source build: cold discovery or mutation of this search's paid winner.

    The seed for a fresh search is always independent of the reference and of
    P7.1-P7.4 winners. Later elite mutations derive only from candidates that
    this same P7.5 native/world run has actually executed and scored.
    """
    # A cold generator must not be SEEDED with the saved reference or a prior
    # winner. Independently rediscovering any reference gear, talent or APL
    # dimension is legal: excluding matching axes silently removes valid
    # candidates from the joint search space (including the true optimum).
    for _ in range(80):
        try:
            kwargs = ({"enchant_pools": enchant_pools}
                      if enchant_pools is not None else {})
            if elite is None:
                candidate = source.make_candidate(base, pools, rng, **kwargs)
            elif repair_axes is None:
                candidate = source.make_candidate(
                    base, pools, rng, elite=elite, **kwargs)
            else:
                candidate = source.make_candidate(
                    base, pools, rng, elite=elite, repair_axes=repair_axes,
                    **kwargs)
            p = source.player(candidate)
            items = p["equipment"]["items"]
            ids = [int(x["id"]) for x in items]
            enchants = [int(x.get("enchant") or 0) for x in items]
            validator.validate(ids, enchants)  # real source+Rust item legality
            # In cold mode this was independently sampled. With elite it is
            # descended only from this search's genuinely paid candidate.
            # Equality with a reference axis is never evidence of seeding.
            return candidate
        except (source.RejectedGear, ValueError, KeyError, TypeError):
            continue
    raise ValueError("NO_SOURCE_LEGAL_INDEPENDENT_COLD_JOINT_ALTERNATIVE")


def _paid_p75_parent(best, finalists, proposal_index, rng, *,
                     balanced_elites=()):
    """Mutate paid builds, not one noisy three-fight leader indefinitely.

    Full P7.5 searches previously used the single highest balanced-screen
    build for every pre-finalist non-restart mutation. In a joint gear/talent/
    rotation search this collapses exploration onto one stochastic outlier.
    Keep the 1/5 independent cold restarts; on every third local proposal,
    draw from the six highest *actually executed* balanced candidates.
    Other local proposals prefer the strongest separately paid stochastic
    finalists once available. Never draw from saved or prior gate winners.
    """
    if best is None or proposal_index % 5 == 0:
        return None
    if balanced_elites and proposal_index % 3 == 0:
        return rng.choice(sorted(
            balanced_elites, key=lambda row: row[0], reverse=True
        )[:6])[2]
    if finalists and proposal_index % 3 != 0:
        return rng.choice(sorted(
            finalists, key=lambda row: row[0], reverse=True
        )[:3])[3]
    return best[3]


def _p75_paid_joint_axes(proposal_index: int):
    """Occasionally repair interacting axes from THIS search's paid parent.

    The previous P7.5 local operator mutated only one of gear, talents, APL
    or enchants per proposal. The genuine full paid run #41577577552 fell
    16.90 DPS below its accepted-compatible prior; retain the independent
    1/5 cold restarts and existing one-axis exploitation, but let every
    seventh paid-parent proposal explore a two-axis neighborhood. Never use
    the saved reference or earlier gates' winning builds as parents.
    """
    if proposal_index % 7:
        return None
    pairs = (("gear", "talents"), ("gear", "rotation"),
             ("talents", "rotation"))
    return pairs[(proposal_index // 7 - 1) % len(pairs)]


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.5")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    search_mode = os.environ.get("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    if search_mode not in ("0", "1"):
        return {"status": "BLOCKED",
                "reasons": ["P7_5_INVALID_FULL_SOURCE_SEARCH_MODE"]}
    full_search = search_mode == "1"
    strategy = os.environ.get("FOREVER_P7_SEARCH_STRATEGY", "default")
    if strategy not in ("default", "wf613"):
        return {"status": "BLOCKED",
                "reasons": ["P7_5_INVALID_SEARCH_STRATEGY"]}
    integration = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(integration))
    try:
        source = _source_module(integration / "p75_joint_search.py",
                                "p75_existing_source_native_joint_search")
    finally:
        sys.path.remove(str(integration))
    production = _source_module(integration / "live_world_probe.py",
                                "p75_production_native_world")
    # WF613 is a selectable producer policy, not a second simulator/gate.
    # Leave the default production search untouched for A/B comparison.
    wf613 = (_source_module(integration / "wf613_strategy.py",
                            "p75_wf613_paid_archive").WF613Controller()
             if strategy == "wf613" else None)
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
    best = None  # three-fight balanced top result, only a diagnostic
    balanced_elites = []  # 24 distinct source-legal paid joint candidates
    stochastic_finalists = []  # 2x24 independent paid native+2D screens
    rerank_seen = set()
    confirmed = set()
    confirmation_attempted = set()
    deep_confirmation_attempted = set()
    deep_confirmed = set()
    rerank_failures = []
    stochastic_parent_proposals = 0
    worst_finalist_s = 0.0
    worst_confirmation_s = 0.0
    executed = 0
    proposals = 0
    seen = set()
    failures = []
    search_start = time.monotonic()
    try:
        # Full search uses every source/Rust-admitted catalogue item per slot,
        # not just the 80 highest heuristic scores. Cold generator explores
        # this pool without seeding the saved build. After the first actually
        # paid winner, use its existing source mutation operator for 4/5 of
        # later proposals and fresh independent cold discovery for 1/5.
        # Enchants and effects remain subject to source verification.
        pools, _ = source.candidate_pool(
            validator, limit=None if full_search else 15,
            **({"independent_enchants": True} if full_search else {}))
        enchant_pools = (source.source_enchant_pools(validator, pools)
                         if full_search else None)
        distance = source.player(base)["distanceFromTarget"]
        while True:
            elapsed = time.monotonic() - search_start if full_search else 0.0
            if (full_search and elapsed >= 300.0
                    or not full_search and proposals >= 3):
                break
            # Real P7.5 #41565060685 screened 820.66 balanced DPS but
            # froze only 697.32 stochastic DPS. Spend part of the SAME
            # 300s budget on independent genuine native+2D finalist scores.
            if full_search and (elapsed >= 240.0 or
                                _p74_early_rerank_due(
                                    elapsed, len(stochastic_finalists))):
                # P7.4 already confirms the strongest paid stochastic finalist
                # with 144 independent non-holdout fights. P7.5 formerly
                # stopped at 96, even after a measured 716.30 paid finalist
                # fell to 702.79 in its 1,000-fight frozen holdout.
                # Reuse the same bounded two-deep-confirmation policy, never
                # selecting with the separate frozen holdout.
                next_deep = _next_p74_deep_confirmation(
                    stochastic_finalists, confirmed,
                    deep_confirmation_attempted, elapsed)
                confirmation = next_deep or _next_p74_confirmation(
                    stochastic_finalists, confirmation_attempted, elapsed)
                if confirmation is not None and _paid_step_has_budget(
                        search_start, max(worst_finalist_s,
                                          worst_confirmation_s)):
                    index, row = confirmation
                    is_deep = next_deep is not None
                    if is_deep:
                        deep_confirmation_attempted.add(row[2])
                    else:
                        confirmation_attempted.add(row[2])
                    started = time.perf_counter()
                    try:
                        second_score, second_live = _paid_gear_stochastic_finalist(
                            production, binary, row[3], distance,
                            seeds=(("1955181", "1955207") if is_deep
                                   else ("1955113", "1955139")))
                        # Initial 48, confirmed 96, deep-confirmed 144
                        # genuine paid stochastic fights: weight old 96-fight
                        # mean twice when incorporating the last 48.
                        new_score = ((2 * row[0] + second_score) / 3
                                     if is_deep else
                                     (row[0] + second_score) / 2)
                        stochastic_finalists[index] = (
                            new_score, second_live, *row[2:])
                        if is_deep:
                            deep_confirmed.add(row[2])
                        else:
                            confirmed.add(row[2])
                    except (ValueError, RuntimeError, OSError, KeyError,
                            TimeoutError, TypeError, AssertionError,
                            subprocess.SubprocessError) as exc:
                        rerank_failures.append(
                            "CONFIRM:" + type(exc).__name__ + ":" + str(exc)[:160])
                    finally:
                        worst_confirmation_s = max(
                            worst_confirmation_s, time.perf_counter() - started)
                    continue
                pending = next((
                    row for row in balanced_elites
                    if row[1] not in rerank_seen), None)
                if pending is not None and _paid_step_has_budget(
                        search_start, worst_finalist_s):
                    screen_score, candidate_sha, candidate = pending
                    rerank_seen.add(candidate_sha)
                    started = time.perf_counter()
                    try:
                        stochastic_score, stochastic_live = _paid_gear_stochastic_finalist(
                            production, binary, candidate, distance,
                            seeds=("1955004", "1955047"))
                        stochastic_finalists.append((
                            stochastic_score, stochastic_live, candidate_sha,
                            candidate, screen_score))
                    except (ValueError, RuntimeError, OSError, KeyError,
                            TimeoutError, TypeError, AssertionError,
                            subprocess.SubprocessError) as exc:
                        rerank_failures.append(
                            type(exc).__name__ + ":" + str(exc)[:160])
                    finally:
                        worst_finalist_s = max(
                            worst_finalist_s, time.perf_counter() - started)
                    continue
            # Do not start an indivisible native+2D paid call in the tail
            # when measured subprocess cost would overrun the 300s search.
            if full_search and elapsed >= 290.0 and not _paid_step_has_budget(
                    search_start, worst_finalist_s):
                break
            proposals += 1
            try:
                # Only a winner already evaluated in THIS live 2D cold search
                # can be an elite. Never seed the saved report or P7.1-P7.4.
                if wf613 is not None:
                    elite, axes, family = wf613.propose(rng)
                    candidate = _cold_joint(
                        base, source, validator, pools, rng,
                        elite=elite, repair_axes=axes,
                        enchant_pools=enchant_pools)
                else:
                    elite = (_paid_p75_parent(
                        best, stochastic_finalists, proposals, rng,
                        balanced_elites=balanced_elites)
                        if full_search else None)
                    if elite is not None and stochastic_finalists and proposals % 3 != 0:
                        stochastic_parent_proposals += 1
                    # A real paid elite may need coordinated gear/talent/APL
                    # edits to escape a single-axis local basin. Do not pass
                    # repair axes to independent cold restarts.
                    joint_axes = (_p75_paid_joint_axes(proposals)
                                  if elite is not None and full_search else None)
                    candidate = _cold_joint(
                        base, source, validator, pools, rng,
                        elite=elite, enchant_pools=enchant_pools,
                        repair_axes=joint_axes)
                candidate_sha = hashlib.sha256(json.dumps(
                    candidate, sort_keys=True).encode()).hexdigest()
                if candidate_sha in seen:
                    continue  # no repeated balanced-RNG paid score
                seen.add(candidate_sha)
                with tempfile.TemporaryDirectory(prefix="forever_p75_live_") as tmp:
                    path = Path(tmp) / "cold-full-source-build.json"
                    path.write_text(json.dumps(candidate))
                    native = production.native_source_control(
                        binary, path, 3, rng_mode="balanced")
                    live = production.run(
                        binary, path, distance=distance, iterations=3,
                        rng_mode="balanced")
                    mismatch = _source_native_world_parity(native, live, 3)
                    if mismatch is not None:
                        raise ValueError("P7_5_" + mismatch)
                if (live.get("iterations_done") != 3
                        or live.get("native_damage_events", 0) <= 0
                        or live.get("native_world_ticks", 0) <= 0):
                    raise ValueError("SOURCE_JOINT_NATIVE_WORLD_EXECUTION_INCOMPLETE")
                score = float(live["world_mean_dps"])
                if not 0 <= score < float("inf"):
                    raise ValueError("SOURCE_JOINT_NATIVE_WORLD_DPS_INVALID")
                executed += 1
                balanced_elites.append((score, candidate_sha, candidate))
                balanced_elites.sort(key=lambda row: row[0], reverse=True)
                del balanced_elites[24:]
                if wf613 is not None:
                    wf613.observe(candidate, score, family)
                if best is None or score > best[0]:
                    best = (score, live, candidate_sha, candidate)
            except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
                    TypeError, AssertionError, subprocess.SubprocessError) as exc:
                failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    finally:
        validator.close()
    if full_search and elapsed < 300.0:
        # If a measured paid step cannot fit, complete the original window.
        # No extra clock read when the loop already reached its deadline.
        time.sleep(max(0.0, search_start + 300.0 - time.monotonic()))
    search_wall_s = time.monotonic() - search_start
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_5_NO_SOURCE_LEGAL_JOINT_CANDIDATE_REACHED_NATIVE_WORLD"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "search_wall_s": search_wall_s,
                "cold_candidate_failures": failures[:4]}

    (score, live, candidate_sha, frozen_winner,
     selected_balanced_score, selected_validation) = _freeze_paid_p74_winner(
        best, stochastic_finalists, confirmed, deep_confirmed)
    complete_search = full_search and 300.0 <= search_wall_s <= 301.0
    final = {}
    if complete_search:
        # Freeze the winning legal request BEFORE independent stochastic
        # native and 2D evaluation, never use holdout to select a winner.
        try:
            with tempfile.TemporaryDirectory(prefix="forever_p75_frozen_") as tmp:
                frozen_path = Path(tmp) / "frozen-joint-winner.json"
                frozen_path.write_text(json.dumps(frozen_winner))
                frozen_sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
                n = P7_FINAL_STOCHASTIC_ITERATIONS
                native = production.native_source_control(
                    binary, frozen_path, n, rng_mode="stochastic")
                world = production.run(
                    binary, frozen_path, distance=distance, iterations=n,
                    rng_mode="stochastic")
                mismatch = _source_native_world_parity(
                    native, world, n, expected_raw_sha=frozen_sha)
                if mismatch is not None:
                    raise ValueError("FROZEN_STOCHASTIC_NATIVE_WORLD_PARITY:" + mismatch)
                native_dps = float(native["native_dps"])
                world_dps = float(world["world_mean_dps"])
                if not (0 <= native_dps < float("inf")
                        and 0 <= world_dps < float("inf")
                        and int(world["native_damage_events"]) > 0
                        and int(world["native_world_ticks"]) > 0):
                    raise ValueError("P7_5_FROZEN_STOCHASTIC_WORLD_INVALID")
                reference_only_floor = p7_required_dps(
                    "P7.4", float(meta["reference_dps"]))
                final = {
                    "frozen_request_raw_sha256": frozen_sha,
                    "frozen_stochastic_iterations": n,
                    "frozen_stochastic_native_dps": native_dps,
                    "frozen_stochastic_world_dps": world_dps,
                    "frozen_stochastic_world_damage_events": int(world["native_damage_events"]),
                    "frozen_stochastic_world_boundaries": int(world["native_world_ticks"]),
                    "frozen_stochastic_external_only_floor_met": (
                        native_dps >= reference_only_floor
                        and world_dps >= reference_only_floor),
                }
        except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
                TypeError, AssertionError, subprocess.SubprocessError) as exc:
            final = {"frozen_stochastic_failure":
                     type(exc).__name__ + ":" + str(exc)[:180]}

    # Compare the independent frozen P7.5 holdout against genuine compatible
    # previously accepted results, never against search-screen estimates.
    # Missing numeric receipts preserve the existing fail-closed BLOCKED state.
    prior = (strongest_accepted_prior(
        root, class_key, level, spec,
        engine_revision=meta.get("selected_engine_revision", PINNED_RUST),
        source_sha256=SAVED_BALANCE_RAW_SHA,
        reference_dps=float(meta["reference_dps"]))
        if complete_search else None)
    prior_dps = prior["dps"] if prior is not None else None
    required = (p7_required_dps(
        "P7.5", float(meta["reference_dps"]),
        strongest_accepted_compatible_prior=prior_dps)
        if prior_dps is not None else None)
    reasons = ([] if prior is not None else [
        "P7_5_ACCEPTED_COMPATIBLE_PRIOR_REQUIRED_FOR_FINAL_DPS_FLOOR"])
    if not full_search:
        reasons.append("P7_5_FULL_300S_COLD_SEARCH_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED")
    elif search_wall_s < 300.0:
        reasons.append("P7_5_300S_SEARCH_NOT_COMPLETED")
    elif search_wall_s > 301.0:
        reasons.append("P7_5_SEARCH_BUDGET_OVERRUN")
    if "frozen_stochastic_iterations" not in final:
        reasons.append("P7_5_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED")
    elif not final["frozen_stochastic_external_only_floor_met"]:
        reasons.append("P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR")
    elif required is not None and (
            final["frozen_stochastic_native_dps"] < required
            or final["frozen_stochastic_world_dps"] < required):
        reasons.append("P7_5_FROZEN_STOCHASTIC_DPS_BELOW_ACCEPTED_PRIOR_FLOOR")
    # An unestablished accepted-compatible prior is a missing *comparison*,
    # not evidence that combat/search failed. Label a genuine full-run budget,
    # final-holdout or external-DPS failure as FAIL; otherwise remain BLOCKED.
    # This does not confer PASS without the required approved prior.
    failed_execution = full_search and any(reason in {
        "P7_5_300S_SEARCH_NOT_COMPLETED",
        "P7_5_SEARCH_BUDGET_OVERRUN",
        "P7_5_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED",
        "P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR",
        "P7_5_FROZEN_STOCHASTIC_DPS_BELOW_ACCEPTED_PRIOR_FLOOR",
    } for reason in reasons)
    return {
        "status": ("FAIL" if failed_execution else
                   "BLOCKED" if reasons else "PASS"),
        "reasons": reasons,
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "joint_cold_world_dps": score,
        "cold_balanced_screen_best_dps": best[0],
        "selected_balanced_screen_dps": selected_balanced_score,
        "paid_joint_stochastic_finalists": len(stochastic_finalists),
        "paid_joint_stochastic_confirmed": len(confirmed),
        "paid_joint_stochastic_deep_confirmed": len(deep_confirmed),
        "stochastic_parent_proposals": stochastic_parent_proposals,
        "stochastic_finalist_failures": rerank_failures[:4],
        "external_reference_only_floor": p7_required_dps(
            "P7.4", float(meta["reference_dps"])),
        "final_required_dps": required,
        "strongest_accepted_compatible_prior_dps": prior_dps,
        "accepted_compatible_prior_gates": (
            prior["compatible_gates"] if prior is not None else []),
        "accepted_compatible_prior_run_urls": (
            prior["run_urls"] if prior is not None else []),
        "cold_winner_request_sha256": candidate_sha,
        "search_wall_s": search_wall_s,
        "independent_300s_search_requested": full_search,
        "independent_300s_search_completed": complete_search,
        "cold_unique_source_requests": len(seen),
        **final,
        **(_executed_p7_runtime_proof(
            "P7.5", final["frozen_request_raw_sha256"],
            engine_revision=meta.get("selected_engine_revision", PINNED_RUST))
           if complete_search and not reasons and "frozen_request_raw_sha256" in final else {}),
        "world_damage_events": int(live["native_damage_events"]),
        "world_boundaries": int(live["native_world_ticks"]),
        "source_legal_joint_candidates_paid": executed,
        "search_strategy": strategy,
        **(wf613.diagnostics() if wf613 is not None else {}),
        "cold_candidate_failures": failures[:4],
        "selected_validation": selected_validation,
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
