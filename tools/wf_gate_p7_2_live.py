"""P7.2 live first contact: real cold APL mutation -> pinned Rust -> gsim 2D.

Uses the existing source-backed APL mutator and the *selected* native-world
production evaluator. A short cold search is a FAIL with numeric DPS proximity,
NOT the required 300s independent search or 1000 stochastic-fight acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time

from tools.wf_gate_coverage import (P7_FINAL_STOCHASTIC_ITERATIONS,
                                    p7_final_stochastic_mean_passes,
                                    p7_required_dps)

from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity, _executed_p7_runtime_proof,
                                     _selected_rust_submodule)


def _source_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("SOURCE_PRODUCTION_MODULE_UNAVAILABLE:" + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blocked(reason: str):
    return {"status": "BLOCKED", "reasons": [reason]}


def _cold_apl(base: dict, rng: random.Random, mutation, *, elite=None):
    """Cold grammar draw or local improvement of this search's paid best.

    The first candidate is sampled independently of the saved reference.
    The optional elite is this search's already executed native/world winner;
    only its rotation is mutable, while gear and talents remain pinned.
    """
    result = copy.deepcopy(base)
    p = result["raid"]["parties"][0]["players"][0]
    original = base["raid"]["parties"][0]["players"][0]
    grammar = original["rotation"]["priorityList"]
    if elite is None:
        candidate = mutation.mutate_apl(None, grammar, rng, cold=True)
    else:
        winner = elite["raid"]["parties"][0]["players"][0]
        if (winner["equipment"] != original["equipment"]
                or winner.get("talentsString") != original.get("talentsString")):
            raise ValueError("P72_PAID_ELITE_CHANGED_FIXED_DIMENSIONS")
        # Reuse only an actually paid P7.2 winner, never the reference policy
        # or an independently accepted P7.1/P7.3-P7.5 result as a seed.
        candidate = mutation.mutate_apl(
            winner["rotation"]["priorityList"], grammar, rng, cold=False)
    p["rotation"]["priorityList"] = candidate
    original = base["raid"]["parties"][0]["players"][0]
    if p["equipment"] != original["equipment"] or (
            p.get("talentsString") != original.get("talentsString")):
        raise ValueError("ROTATION_ONLY_COLD_SEARCH_CHANGED_FIXED_DIMENSIONS")
    return result


def _paid_p72_parent(best, finalists, proposal_index, rng, *, balanced_elites=()):
    """Choose parents only from this run's genuinely paid Balanced archive.

    Keep independent cold restarts. Local APL edits rotate among the top
    balanced-screen archive and separately confirmed balanced finalists;
    never let one noisy three-fight screen leader monopolize the search.
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


def _paid_p72_balanced_finalist(production, binary, request, distance, *,
                                seeds=("6327201", "6327202"),
                                stage="finalist"):
    """Score one already-paid source candidate on independent Balanced seeds.

    Each seed gets three native and real 2D fights. This is search/rerank
    evidence only; the frozen 1,000-fight Stochastic holdout remains separate.
    """
    scores = []
    latest_live = None
    for seed in seeds:
        candidate = copy.deepcopy(request)
        options = candidate.setdefault("simOptions", {})
        if not isinstance(options, dict):
            raise ValueError("P72_BALANCED_FINALIST_SIM_OPTIONS_INVALID")
        options["randomSeed"] = str(seed)
        with tempfile.TemporaryDirectory(prefix=f"forever_p72_{stage}_") as tmp:
            path = Path(tmp) / f"paid-balanced-{stage}.json"
            path.write_text(json.dumps(candidate))
            native = production.native_source_control(
                binary, path, 3, rng_mode="balanced")
            live = production.run(
                binary, path, distance=distance, iterations=3,
                rng_mode="balanced")
            mismatch = _source_native_world_parity(native, live, 3)
            if mismatch is not None:
                raise ValueError("P72_BALANCED_FINALIST_NATIVE_WORLD_PARITY:" + mismatch)
        if (live.get("iterations_done") != 3
                or live.get("native_damage_events", 0) <= 0
                or live.get("native_world_ticks", 0) <= 0):
            raise ValueError("P72_BALANCED_FINALIST_WORLD_INCOMPLETE")
        score = float(live["world_mean_dps"])
        if not 0 <= score < float("inf"):
            raise ValueError("P72_BALANCED_FINALIST_DPS_INVALID")
        scores.append(score)
        latest_live = live
    return sum(scores) / len(scores), latest_live


def _freeze_paid_p72_balanced_winner(screen_best, reranked, confirmed=(),
                                     deep_confirmed=()):
    """Freeze the strongest most-validated paid Balanced finalist."""
    if reranked:
        deep_rows = [row for row in reranked if row[2] in deep_confirmed]
        confirmed_rows = [row for row in reranked if row[2] in confirmed]
        score, live, sha, request, screen_score = max(
            deep_rows or confirmed_rows or reranked, key=lambda row: row[0])
        label = ("paid_6x3_balanced_live_native_deep_confirmed_finalist"
                 if deep_rows else
                 "paid_4x3_balanced_live_native_confirmed_finalist"
                 if confirmed_rows else
                 "paid_2x3_balanced_live_native_finalist")
        return score, live, sha, request, screen_score, label
    score, live, sha, request = screen_best
    return score, live, sha, request, score, "three_balanced_live_screen_only"


def _pinned_source_runtime(root: Path, class_key: str, level: int,
                           spec: str, gate: str):
    """One exact-source native preflight shared by P7 discovery gates."""
    if (class_key, level, spec) != ("druid", 60, "balance"):
        return _blocked(gate.replace(".", "_") + "_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT")
    request = root / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
    witness = root / "docs/evidence/wf633/WF633_VALIDATION.json"
    if not request.is_file() or not witness.is_file():
        return _blocked(gate.replace(".", "_") + "_PINNED_SOURCE_REQUEST_OR_REFERENCE_MISSING")
    raw = request.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SAVED_BALANCE_RAW_SHA:
        return _blocked(gate.replace(".", "_") + "_PINNED_SOURCE_REQUEST_CHANGED")
    base = json.loads(raw)
    meta = json.loads(witness.read_text())
    if (meta.get("engine_revision") != PINNED_RUST
            or not isinstance(meta.get("reference_dps"), (float, int))
            or meta["reference_dps"] <= 0
            or base["raid"]["parties"][0]["players"][0]["class"] != "ClassDruid"
            or len(base["encounter"]["targets"]) != 1
            or base["encounter"]["targets"][0]["level"] != 63):
        return _blocked(gate.replace(".", "_") + "_PINNED_REFERENCE_SCENARIO_MISMATCH")
    binary = Path(os.environ.get("FOREVER_MYTHICSIM_RUST_BIN", str(
        root.parent / "upstream/target/release/forever-engine"))).resolve()
    if not binary.is_file():
        return _blocked(gate.replace(".", "_") + "_PINNED_RUST_BINARY_MISSING")
    upstream = binary.parents[2]
    selected_rust = _selected_rust_submodule(root, upstream)
    if (selected_rust is None
            or not (upstream / "src/core/fight/world_bridge.rs").is_file()):
        return _blocked(gate.replace(".", "_") + "_PINNED_NATIVE_WORLD_BUILD_NOT_VERIFIED")
    # Keep the saved report's original engine_revision unchanged.
    meta["selected_engine_revision"] = selected_rust
    return (base, meta, binary)


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.2")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    search_mode = os.environ.get("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    if search_mode not in ("0", "1"):
        return _blocked("P7_2_INVALID_FULL_SOURCE_SEARCH_MODE")
    full_search = search_mode == "1"
    mutation = _source_module(root / "integrations/mythicsim-rust/apl_mutation.py",
                              "p72_source_apl_mutator")
    production = _source_module(
        root / "integrations/mythicsim-rust/live_world_probe.py",
        "p72_production_native_world")
    player = base["raid"]["parties"][0]["players"][0]
    rng = random.Random(63272)
    initial_hash = hashlib.sha256(json.dumps(
        player["rotation"]["priorityList"], sort_keys=True).encode()).hexdigest()
    # P7.4 owns the tested 300s paid-step budget and finalist schedule. Import
    # at runtime because P7.4 shares this module's source preflight helpers.
    from tools.wf_gate_p7_4_live import (
        _paid_step_has_budget, _p74_early_rerank_due,
        _next_p74_confirmation, _next_p74_deep_confirmation,
    )
    best = None
    executed = 0
    failures = []
    paid_or_rejected = set()
    proposals = 0
    balanced_elites = []       # top 24 distinct source-legal paid screen candidates
    balanced_finalists = []    # independent 6/12/18-fight Balanced confirmations
    rerank_seen = set()
    confirmed = set()
    confirmation_attempted = set()
    deep_confirmation_attempted = set()
    deep_confirmed = set()
    rerank_failures = []
    balanced_parent_proposals = 0
    worst_screen_s = 0.0
    worst_finalist_s = 0.0
    worst_confirmation_s = 0.0
    search_start = time.monotonic()

    # Every screen, parent, finalist, confirmation and winner decision uses
    # explicit Balanced RNG. The independent frozen 1,000-fight Stochastic
    # holdout below is never allowed to rank or mutate a candidate.
    while True:
        elapsed = time.monotonic() - search_start if full_search else 0.0
        if ((full_search and elapsed >= 300.0)
                or (not full_search and proposals >= 4)):
            break

        # Spend the same 300s search budget on separate paid Balanced
        # finalist scores and confirmations, not only the noisy 3-fight leader.
        if full_search and (
                elapsed >= 240.0
                or _p74_early_rerank_due(elapsed, len(balanced_finalists))):
            next_deep = _next_p74_deep_confirmation(
                balanced_finalists, confirmed,
                deep_confirmation_attempted, elapsed)
            confirmation = next_deep or _next_p74_confirmation(
                balanced_finalists, confirmation_attempted, elapsed)
            if confirmation is not None and _paid_step_has_budget(
                    search_start, max(worst_finalist_s, worst_confirmation_s)):
                index, row = confirmation
                is_deep = next_deep is not None
                if is_deep:
                    deep_confirmation_attempted.add(row[2])
                else:
                    confirmation_attempted.add(row[2])
                started = time.perf_counter()
                try:
                    second_score, second_live = _paid_p72_balanced_finalist(
                        production, binary, row[3], player["distanceFromTarget"],
                        seeds=(("6327221", "6327222") if is_deep else
                               ("6327211", "6327212")),
                        stage=("deep-confirmation" if is_deep else "confirmation"))
                    # Initial 6, confirmed 12, deep-confirmed 18 genuine
                    # Balanced fights. Never use the Stochastic holdout here.
                    new_score = ((2 * row[0] + second_score) / 3
                                 if is_deep else
                                 (row[0] + second_score) / 2)
                    balanced_finalists[index] = (
                        new_score, second_live, *row[2:])
                    if is_deep:
                        deep_confirmed.add(row[2])
                    else:
                        confirmed.add(row[2])
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                        KeyError, TypeError, AssertionError, TimeoutError) as exc:
                    rerank_failures.append(
                        "CONFIRM:" + type(exc).__name__ + ":" + str(exc)[:160])
                finally:
                    worst_confirmation_s = max(
                        worst_confirmation_s, time.perf_counter() - started)
                continue

            pending = next((
                row for row in balanced_elites if row[1] not in rerank_seen
            ), None)
            if pending is not None and len(balanced_finalists) < 24 and (
                    _paid_step_has_budget(search_start, worst_finalist_s)):
                screen_score, candidate_sha, candidate = pending
                rerank_seen.add(candidate_sha)
                started = time.perf_counter()
                try:
                    balanced_score, balanced_live = _paid_p72_balanced_finalist(
                        production, binary, candidate, player["distanceFromTarget"],
                        seeds=("6327201", "6327202"), stage="finalist")
                    balanced_finalists.append((
                        balanced_score, balanced_live, candidate_sha,
                        candidate, screen_score))
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                        KeyError, TypeError, AssertionError, TimeoutError) as exc:
                    rerank_failures.append(
                        type(exc).__name__ + ":" + str(exc)[:180])
                finally:
                    worst_finalist_s = max(
                        worst_finalist_s, time.perf_counter() - started)
                continue

        # Do not launch another indivisible paid step if its observed cost
        # cannot fit before the 300s wall-clock deadline.
        if full_search and elapsed >= 290.0 and not _paid_step_has_budget(
                search_start, max(worst_screen_s, worst_finalist_s,
                                  worst_confirmation_s)):
            break

        paid_start = time.perf_counter()
        proposals += 1
        try:
            # Every fifth proposal is a fresh independent cold draw. Other
            # local edits choose among this run's paid Balanced archive and
            # confirmed finalists instead of repeatedly mutating one noisy
            # three-fight screen winner.
            elite = (_paid_p72_parent(
                best, balanced_finalists, proposals, rng,
                balanced_elites=balanced_elites) if full_search else None)
            if elite is not None:
                balanced_parent_proposals += 1
            candidate = _cold_apl(base, rng, mutation, elite=elite)
            candidate_sha = hashlib.sha256(
                json.dumps(candidate, sort_keys=True).encode()).hexdigest()
            if candidate_sha in paid_or_rejected:
                continue
            paid_or_rejected.add(candidate_sha)
            with tempfile.TemporaryDirectory(prefix="forever_p72_live_") as temp:
                file = Path(temp) / "source-cold-candidate.json"
                file.write_text(json.dumps(candidate))
                native = production.native_source_control(
                    binary, file, 3, rng_mode="balanced")
                result = production.run(
                    binary, file, distance=player["distanceFromTarget"],
                    iterations=3, rng_mode="balanced")
                parity_failure = _source_native_world_parity(native, result, 3)
                if parity_failure is not None:
                    raise ValueError("SOURCE_NATIVE_WORLD_PARITY_FAILED:" + parity_failure)
            if (result.get("iterations_done") != 3
                    or result.get("native_damage_events", 0) <= 0
                    or result.get("native_world_ticks", 0) <= 0):
                raise ValueError("SOURCE_NATIVE_WORLD_INCOMPLETE")
            executed += 1
            score = float(result["world_mean_dps"])
            if not 0 <= score < float("inf"):
                raise ValueError("INVALID_COUPLED_WORLD_DPS")
            balanced_elites.append((score, candidate_sha, candidate))
            balanced_elites.sort(key=lambda row: row[0], reverse=True)
            del balanced_elites[24:]
            if best is None or score > best[0]:
                best = (score, result, candidate_sha, candidate)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                KeyError, TypeError, AssertionError, TimeoutError) as exc:
            failures.append(type(exc).__name__ + ":" + str(exc)[:180])
        finally:
            worst_screen_s = max(
                worst_screen_s, time.perf_counter() - paid_start)

    if full_search and time.monotonic() - search_start < 300.0:
        # If no observed paid step fits in the remaining tail, complete the
        # requested wall-clock window without starting a call that can overrun.
        time.sleep(max(0.0, search_start + 300.0 - time.monotonic()))
    search_wall_s = time.monotonic() - search_start
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_2_NO_EXECUTED_SOURCE_LEGAL_COLD_APL_WORLD_CANDIDATE"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "search_wall_s": search_wall_s,
                "cold_candidate_failures": failures[:4]}

    (score, selected, selected_sha, frozen_winner,
     winner_screen_dps, selected_validation) = _freeze_paid_p72_balanced_winner(
         best, balanced_finalists, confirmed, deep_confirmed)
    final = {}
    if full_search and search_wall_s >= 300.0:
        # Freeze the best source request before any final measurement. This
        # strictly separate stochastic run must never modify or rank winners.
        # Keep a real native control alongside genuine gsim world execution.
        try:
            with tempfile.TemporaryDirectory(prefix="forever_p72_frozen_") as tmp:
                frozen_path = Path(tmp) / "frozen-winner.json"
                frozen_path.write_text(json.dumps(frozen_winner))
                frozen_raw_sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
                n = P7_FINAL_STOCHASTIC_ITERATIONS
                native = production.native_source_control(binary, frozen_path, n,
                                                          rng_mode="stochastic")
                live = production.run(
                    binary, frozen_path, distance=player["distanceFromTarget"],
                    iterations=n, rng_mode="stochastic")
                mismatch = _source_native_world_parity(
                    native, live, n, expected_raw_sha=frozen_raw_sha)
                if mismatch is not None:
                    raise ValueError("FROZEN_STOCHASTIC_NATIVE_WORLD_PARITY:" + mismatch)
                native_dps = float(native["native_dps"])
                world_dps = float(live["world_mean_dps"])
                final = {
                    "frozen_request_raw_sha256": frozen_raw_sha,
                    "frozen_stochastic_iterations": n,
                    "frozen_stochastic_native_dps": native_dps,
                    "frozen_stochastic_world_dps": world_dps,
                    "frozen_stochastic_world_damage_events": int(live["native_damage_events"]),
                    "frozen_stochastic_world_boundaries": int(live["native_world_ticks"]),
                    "frozen_stochastic_reference_floor_met": (
                        p7_final_stochastic_mean_passes(
                            "P7.2", world_dps, float(meta["reference_dps"]),
                            iterations=n, stochastic=True)
                        and p7_final_stochastic_mean_passes(
                            "P7.2", native_dps, float(meta["reference_dps"]),
                            iterations=n, stochastic=True)),
                }
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                KeyError, TypeError, AssertionError) as exc:
            final = {"frozen_stochastic_failure":
                     type(exc).__name__ + ":" + str(exc)[:180]}

    # The original saved report source is pinned by shared preflight; the
    # gate requires executable source-legal candidates, not an exhaustive
    # enumeration or a second interactive UI capture.
    reasons = []
    if not full_search:
        reasons.append("P7_2_FULL_INDEPENDENT_300S_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED")
    elif search_wall_s < 300.0:
        reasons.append("P7_2_300S_SEARCH_NOT_COMPLETED")
    elif search_wall_s > 301.0:
        reasons.append("P7_2_SEARCH_BUDGET_OVERRUN")
    if "frozen_stochastic_iterations" not in final:
        reasons.append("P7_2_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED")
    elif not final["frozen_stochastic_reference_floor_met"]:
        reasons.append("P7_2_FROZEN_STOCHASTIC_DPS_BELOW_REFERENCE_FLOOR")
    return {
        "status": "PASS" if not reasons else "FAIL",
        **(_executed_p7_runtime_proof(
               "P7.2", final["frozen_request_raw_sha256"],
               engine_revision=meta.get("selected_engine_revision", PINNED_RUST))
           if not reasons else {}),
        "reasons": reasons,
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "original_apl_hash": initial_hash,
        "cold_winner_request_sha256": selected_sha,
        "cold_winner_apl": frozen_winner["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"],
        "cold_balanced_screen_best_dps": best[0],
        "winner_screen_dps": winner_screen_dps,
        "winner_live_dps": score,
        "winner_selection": selected_validation,
        "required_reference_dps": p7_required_dps(
            "P7.2", float(meta["reference_dps"])),
        "search_wall_s": search_wall_s,
        "independent_300s_search_requested": full_search,
        "independent_300s_search_completed": full_search and 300.0 <= search_wall_s <= 301.0,
        "cold_unique_source_requests": len(paid_or_rejected),
        **final,
        "world_damage_events": int(selected["native_damage_events"]),
        "world_boundaries": int(selected["native_world_ticks"]),
        "source_legal_cold_candidates_paid": executed,
        "cold_candidate_failures": failures[:4],
        "paid_balanced_finalists": len(balanced_finalists),
        "paid_balanced_confirmed_finalists": len(confirmed),
        "paid_balanced_deep_confirmed_finalists": len(deep_confirmed),
        "balanced_parent_proposals": balanced_parent_proposals,
        "balanced_finalist_failures": rerank_failures[:4],
        "balanced_finalist_receipts": [
            {"request_sha256": row[2], "screen_dps": row[4],
             "balanced_dps": row[0], "confirmed": row[2] in confirmed,
             "deep_confirmed": row[2] in deep_confirmed}
            for row in sorted(balanced_finalists,
                              key=lambda item: item[0], reverse=True)[:8]
        ],
        "selected_validation": selected_validation,
        "search_rng_mode": "balanced",
        "source_fixed_gear_and_talents": True,
        "coverage_scope_complete": False,
    }
