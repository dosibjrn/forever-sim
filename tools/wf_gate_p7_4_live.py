"""P7.4 first live gear discovery using real source+Rust item legality.

Only actual independently chosen, source/Rust-compatible gear loadouts scored
by the selected pinned native↔gsim 2D engine can produce a numeric PARTIAL.
This is not the 300s search or frozen 1000-fight P7.4 acceptance.
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
from tools.wf_gate_p7_2_live import _source_module, _pinned_source_runtime


def _source_ranked_item_choice(items, rng: random.Random, *, ranked: bool):
    """Sample *all* admitted source items, while exploiting their stat order.

    candidate_pool sorts the complete pinned source/Rust-admitted item list by
    spellpower/intellect/hit/crit/spirit. The top-32 preference is a proposal
    distribution only: every item still has nonzero probability of selection,
    and periodic wholly-uniform cold restarts keep full-pool exploration.
    Neither the saved reference loadout nor another gate's winner is a seed.
    """
    if ranked and rng.random() < 0.90:
        return rng.choice(items[:min(32, len(items))])
    return rng.choice(items)


def _cold_gear(base: dict, validator, gear_search, rng: random.Random, *,
               pool=None, enchant_pools=None, elite=None,
               source_ranked=False, neighbor_mode="mixed",
               native_authoritative=False):
    """Independent cold discovery or local edits of this run's paid winner.

    The saved loadout is never a search seed. An elite is only supplied after
    its native+2D candidate has been legally executed and scored.
    """
    if pool is None:
        pool, _ = gear_search.candidate_pool(validator, limit=15)
    original_items = base["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    reference = [item["id"] for item in original_items]
    original_enchants = [item.get("enchant") for item in original_items]
    paid_items = None
    if elite is not None:
        fixed = base["raid"]["parties"][0]["players"][0]
        paid = elite["raid"]["parties"][0]["players"][0]
        if (paid.get("talentsString") != fixed.get("talentsString")
                or paid.get("rotation") != fixed.get("rotation")):
            raise ValueError("P74_PAID_ELITE_CHANGED_FIXED_AXES")
        paid_items = paid["equipment"]["items"]
        if len(paid_items) != len(reference):
            raise ValueError("P74_PAID_ELITE_CHANGED_GEAR_SLOTS")
    if neighbor_mode not in ("mixed", "single", "enchant"):
        raise ValueError("P74_INVALID_PAID_NEIGHBOR_MODE")
    for _ in range(60):
        if paid_items is None:
            ids = [_source_ranked_item_choice(pool[i], rng, ranked=source_ranked)
                   for i in range(len(reference))]
            enchants = ([rng.choice(enchant_pools[i]) for i in range(len(reference))]
                        if enchant_pools is not None else list(original_enchants))
        else:
            # Reuse the old source-native P7.4 search's 1–5-slot neighborhood
            # idea, but score each candidate with the actual live native+2D
            # engine. Keep the elite immutable; sample only source pools.
            ids = [int(item["id"]) for item in paid_items]
            enchants = [item.get("enchant") for item in paid_items]
            if neighbor_mode == "enchant":
                # Keep this genuinely paid item's gear fixed while testing a
                # separate source-legal enchant choice. The previous search
                # changed enchants only as a side effect of swapping gear.
                if enchant_pools is None:
                    raise ValueError("P74_ENCHANT_NEIGHBOR_REQUIRES_SOURCE_POOLS")
                # A random slot may have no alternative enchant at all.
                # Choosing it repeatedly wastes the entire 60-attempt
                # proposal even when another legal slot can be changed.
                mutable = [
                    slot for slot in range(len(reference))
                    if any(value != enchants[slot]
                           for value in enchant_pools[slot])
                ]
                if not mutable:
                    raise ValueError("P74_NO_SOURCE_ENCHANT_ALTERNATIVE")
                slot = rng.choice(mutable)
                alternatives = [
                    value for value in enchant_pools[slot]
                    if value != enchants[slot]
                ]
                enchants[slot] = rng.choice(alternatives)
            else:
                # One-slot refinement must select a slot that can actually
                # change, not retry an immutable slot 60 times while another
                # source-admitted slot contains alternatives.
                if neighbor_mode == "single":
                    moves = []
                    for slot in range(len(reference)):
                        if any(item_id != ids[slot] for item_id in pool[slot]):
                            moves.append(("item", slot))
                        if (enchant_pools is not None and
                                any(value != enchants[slot]
                                    for value in enchant_pools[slot])):
                            moves.append(("enchant", slot))
                    if not moves:
                        raise ValueError("P74_NO_SOURCE_SINGLE_SLOT_ALTERNATIVE")
                    kind, slot = rng.choice(moves)
                    if kind == "item":
                        alternatives = [item_id for item_id in pool[slot]
                                        if item_id != ids[slot]]
                        ids[slot] = _source_ranked_item_choice(
                            alternatives, rng, ranked=source_ranked)
                        if enchant_pools is not None:
                            enchants[slot] = rng.choice(enchant_pools[slot])
                    else:
                        alternatives = [value for value in enchant_pools[slot]
                                        if value != enchants[slot]]
                        enchants[slot] = rng.choice(alternatives)
                else:
                    # Retain the independent mixed 1-5-slot exploration.
                    for _step in range(rng.randint(1, min(5, len(reference)))):
                        slot = rng.randrange(len(reference))
                        ids[slot] = _source_ranked_item_choice(
                            pool[slot], rng, ranked=source_ranked)
                        if enchant_pools is not None:
                            enchants[slot] = rng.choice(enchant_pools[slot])
            if (ids == [int(item["id"]) for item in paid_items]
                    and enchants == [item.get("enchant") for item in paid_items]):
                continue  # unchanged paid elite is not a new discovery
        # This candidate was drawn independently from source-admitted pools.
        # Matching the saved reference by chance is legal discovery, never
        # evidence that the reference was used to seed the search.
        if not native_authoritative:
            try:
                if enchant_pools is None:
                    validator.validate(ids)
                else:
                    validator.validate(ids, enchants)
            except gear_search.RejectedGear:
                continue  # legacy callers retain their Python admission path
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


def _paid_gear_elite_choice(elites, rng, proposal_index, balanced_finalists=()):
    """Choose parents from this run's actually paid Balanced gear candidates.

    One in five proposals remains an independent cold draw. Once the search
    has paid for multi-seed native+2D finalist screens, alternate exploitation
    between their top four and the original top-15 single-screen archive.
    Otherwise finalist reranking changes only the frozen winner, while all
    remaining gear mutations still follow noisy three-fight parents.
    Neither the saved reference nor the stochastic holdout seeds the search.
    """
    if proposal_index % 5 == 0:
        return None
    if balanced_finalists and proposal_index % 2 == 0:
        ranked = sorted(balanced_finalists, key=lambda row: row[0],
                        reverse=True)
        return rng.choice(ranked[:min(4, len(ranked))])[3]
    if not elites:
        return None
    return rng.choice(elites[:min(15, len(elites))])[1]


def _paid_step_has_budget(search_start: float, observed_max_s: float) -> bool:
    """Do not launch an indivisible native+2D paid call too near 300s.

    A paid finalist includes two independent native+2D Balanced seed pairs.
    Reserve 1.5x the slowest observed same-kind step plus 250ms, so a finalist
    cannot overrun the measured 300s cold-search window.
    """
    reserve_s = max(0.25, observed_max_s * 1.5 + 0.25)
    return time.monotonic() + reserve_s < search_start + 300.0


def _p74_early_rerank_due(elapsed_s, reranked_count):
    """Schedule bounded balanced finalist screens; shared with P7.5.

    One opportunity per 20 seconds from 120s through 220s. These scores
    are deterministic balanced-RNG search evidence, never stochastic holdout.
    """
    return (120.0 <= elapsed_s < 240.0 and reranked_count < 6
            and elapsed_s >= 120.0 + 20.0 * reranked_count)


def _next_p74_confirmation(reranked, attempted, elapsed_s):
    """Choose the best unconfirmed paid balanced finalist in the bounded window."""
    if len(reranked) < 3 or not 260.0 <= elapsed_s < 295.0:
        return None
    return next((
        (index, row)
        for index, row in sorted(enumerate(reranked),
                                 key=lambda item: item[1][0], reverse=True)
        if row[2] not in attempted
    ), None)


def _next_p74_deep_confirmation(reranked, confirmed, attempted, elapsed_s):
    """Recheck strongest balanced paid leaders before the frozen holdout."""
    if (not 260.0 <= elapsed_s < 295.0 or len(reranked) < 8
            or len(confirmed) < 5 or len(attempted) >= 2):
        return None
    return next(((index, row)
                 for index, row in sorted(
                     enumerate(reranked),
                     key=lambda item: item[1][0], reverse=True)
                 if row[2] in confirmed and row[2] not in attempted), None)


def _paid_p74_balanced_finalist(production, binary, request: dict, distance: float, *,
                                seeds=("1955004", "1955047")):
    """Rank a paid P7.4 gear finalist with independent deterministic Balanced screens.

    Each seed pays three real native+2D fights. These low-repeat scores are
    search evidence only; the frozen 1,000-fight Stochastic holdout remains
    separate and is never used to select or mutate the winner.
    """
    scores = []
    latest_live = None
    for seed in seeds:
        candidate = copy.deepcopy(request)
        candidate["simOptions"]["randomSeed"] = str(seed)
        with tempfile.TemporaryDirectory(prefix="forever_p74_balanced_") as tmp:
            path = Path(tmp) / "paid-balanced-finalist.json"
            path.write_text(json.dumps(candidate))
            native = production.native_source_control(
                binary, path, 3, rng_mode="balanced")
            live = production.run(
                binary, path, distance=distance, iterations=3,
                rng_mode="balanced")
            mismatch = _source_native_world_parity(native, live, 3)
            if mismatch is not None:
                raise ValueError("P7_4_BALANCED_FINALIST_NATIVE_WORLD_PARITY:" + mismatch)
        if (live.get("iterations_done") != 3
                or live.get("native_damage_events", 0) <= 0
                or live.get("native_world_ticks", 0) <= 0):
            raise ValueError("P7_4_BALANCED_FINALIST_WORLD_INCOMPLETE")
        score = float(live["world_mean_dps"])
        if not 0 <= score < float("inf"):
            raise ValueError("P7_4_BALANCED_FINALIST_DPS_INVALID")
        scores.append(score)
        latest_live = live
    return sum(scores) / len(scores), latest_live


def _freeze_paid_p74_balanced_winner(screen_best, reranked, confirmed=(),
                                     deep_confirmed=()):
    """Freeze the best paid Balanced finalist; never use the stochastic holdout to rank."""
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
    elites = []  # top 24 source-legal loadouts scored with balanced RNG
    balanced_finalists = []  # paid two-seed, three-fight native+2D Balanced screens
    rerank_seen = set()
    confirmed = set()
    confirmation_attempted = set()
    deep_confirmation_attempted = set()
    deep_confirmed = set()
    rerank_failures = []
    failures = []
    seen = set()
    proposals = 0
    validator = gear_search.GearValidator(catalogue, items, enchants, base)
    search_start = time.monotonic()
    search_deadline = search_start + 300.0
    worst_screen_s = 0.0
    worst_finalist_s = 0.0
    worst_confirmation_s = 0.0
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
            validator, limit=None if full_search else 15,
            native_authoritative=True,
            **({"independent_enchants": True} if full_search else {}))
        enchant_pools = (gear_search.source_enchant_pools(validator, pool)
                         if full_search else None)
        while True:
            elapsed = time.monotonic() - search_start if full_search else 0.0
            if (full_search and elapsed >= 300.0
                    or not full_search and proposals >= 3):
                break
            # Spend part of the SAME cold-search budget on independent,
            # deterministic Balanced finalist scores. The final Stochastic
            # holdout remains frozen and cannot influence candidate selection.
            if full_search and (elapsed >= 240.0 or
                                _p74_early_rerank_due(
                                    elapsed, len(balanced_finalists))):
                next_deep = _next_p74_deep_confirmation(
                    balanced_finalists, confirmed,
                    deep_confirmation_attempted, elapsed)
                confirmation = next_deep or _next_p74_confirmation(
                    balanced_finalists, confirmation_attempted, elapsed)
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
                        second_score, second_live = _paid_p74_balanced_finalist(
                            production, binary, row[3],
                            player["distanceFromTarget"],
                            seeds=(("1955181", "1955207") if is_deep
                                   else ("1955113", "1955139")))
                        # Initial 6, confirmed 12, deep-confirmed 18 genuinely
                        # paid Balanced fights: weight the prior mean twice
                        # when adding the final six independent observations.
                        new_score = ((2 * row[0] + second_score) / 3
                                     if is_deep else
                                     (row[0] + second_score) / 2)
                        balanced_finalists[index] = (
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
                pending = None
                for screen_score, candidate in elites:
                    candidate_sha = hashlib.sha256(
                        json.dumps(candidate, sort_keys=True).encode()).hexdigest()
                    if candidate_sha not in rerank_seen:
                        pending = (screen_score, candidate, candidate_sha)
                        break
                if pending is not None and _paid_step_has_budget(
                        search_start, worst_finalist_s):
                    screen_score, candidate, candidate_sha = pending
                    rerank_seen.add(candidate_sha)
                    started = time.perf_counter()
                    try:
                        balanced_score, balanced_live = _paid_p74_balanced_finalist(
                            production, binary, candidate,
                            player["distanceFromTarget"],
                            seeds=("1955004", "1955047"))
                        balanced_finalists.append((
                            balanced_score, balanced_live, candidate_sha,
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
            if full_search and not _paid_step_has_budget(
                    search_start, worst_screen_s):
                break  # preserve the measured 300s search window
            paid_start = time.perf_counter()
            proposals += 1
            try:
                # Local exploitation uses only a winner already paid in THIS
                # cold run; every fifth draw is independently cold. The saved
                # gear and other gates' winners are never injected as elites.
                # Only the balanced-scored paid archive may guide local edits.
                elite = (_paid_gear_elite_choice(
                    elites, rng, proposals, balanced_finalists)
                    if full_search else None)
                candidate = _cold_gear(
                    base, validator, gear_search, rng, pool=pool,
                    enchant_pools=enchant_pools, elite=elite,
                    # Four of five proposals exploit legal stat-ranked source
                    # candidates; every fifth samples the entire source
                    # universe uniformly. This is not a top-N legality filter.
                    source_ranked=full_search and proposals % 5 != 0,
                    # Within the 4/5 paid-elite proposals, use one-slot
                    # coordinate edits or enchant-only corrections alongside
                    # the existing 1-5-slot neighborhood. Every fifth draw
                    # remains a fully independent cold source-pool candidate.
                    neighbor_mode=(
                        "enchant" if full_search and elite is not None
                        and proposals % 4 == 0 else
                        "single" if full_search and elite is not None
                        and proposals % 4 in (1, 3) else "mixed"),
                    native_authoritative=True)
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
                elites.append((score, candidate))
                elites.sort(key=lambda item: item[0], reverse=True)
                del elites[24:]
                if best is None or score > best[0]:
                    best = (score, live, candidate_sha, candidate)
            except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
                    TypeError, AssertionError, subprocess.SubprocessError) as exc:
                failures.append(type(exc).__name__ + ":" + str(exc)[:180])
            finally:
                worst_screen_s = max(
                    worst_screen_s, time.perf_counter() - paid_start)
    finally:
        validator.close()
    if full_search:
        # Unused tail time is too short for an observed paid native+2D step.
        # Complete the actual 300s independent wall-time window rather than
        # starting a long blocking call that can overrun it.
        time.sleep(max(0.0, search_deadline - time.monotonic()))
    search_observed_at = time.monotonic()
    search_wall_s = search_observed_at - search_start
    search_window_met = p7_search_window_completed(
        full_search=full_search, elapsed_seconds=search_wall_s,
    )
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_4_NO_SOURCE_LEGAL_NATIVE_WORLD_GEAR_CANDIDATE_EXECUTED"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "search_wall_s": search_wall_s,
                "source_candidate_failures": failures[:4]}

    # Freeze the best paid Balanced finalist before the independent
    # stochastic acceptance holdout. No stochastic score feeds search ranking.
    (score, live, candidate_sha, frozen_winner,
     winner_screen_dps, winner_selection) = _freeze_paid_p74_balanced_winner(
         best, balanced_finalists, confirmed, deep_confirmed)
    complete_search = search_window_met
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

    # The original saved report source is pinned by shared preflight; the
    # gate requires executable source-legal candidates, not an exhaustive
    # enumeration or a second interactive UI capture.
    reasons = []
    if not full_search:
        reasons.append("P7_4_FULL_INDEPENDENT_300S_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED")
    elif not search_window_met:
        reasons.append("P7_4_300S_SEARCH_WINDOW_NOT_COMPLETED")
    if "frozen_stochastic_iterations" not in final:
        reasons.append("P7_4_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED")
    elif not final["frozen_stochastic_reference_floor_met"]:
        reasons.append("P7_4_FROZEN_STOCHASTIC_DPS_BELOW_REFERENCE_FLOOR")
    return {
        "status": "PASS" if not reasons else "FAIL",
        **(_executed_p7_runtime_proof(
               "P7.4", final["frozen_request_raw_sha256"],
               engine_revision=meta.get("selected_engine_revision", PINNED_RUST))
           if not reasons else {}),
        "reasons": reasons,
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "required_reference_dps": p7_required_dps(
            "P7.4", float(meta["reference_dps"])),
        "cold_winner_request_sha256": hashlib.sha256(
            json.dumps(frozen_winner, sort_keys=True).encode()).hexdigest(),
        # Publish the full frozen paid loadout, not merely its hash, so the
        # actual P7.4 winner is inspectable and can be reproduced/debugged.
        "cold_winner_gear": [
            {"slot": slot, "item_id": int(item["id"]),
             "enchant_id": item.get("enchant")}
            for slot, item in enumerate(frozen_winner["raid"]["parties"][0]
                                        ["players"][0]["equipment"]["items"])
        ],
        "winner_live_dps": score,
        "winner_screen_dps": winner_screen_dps,
        "winner_selection": winner_selection,
        "paid_stochastic_finalists": 0,
        "paid_stochastic_confirmed_finalists": 0,
        "paid_stochastic_deep_confirmed_finalists": 0,
        "early_stochastic_finalists_paid": 0,
        "stochastic_parent_proposals": 0,
        "paid_stochastic_finalist_failures": [],
        "paid_balanced_finalists": len(balanced_finalists),
        "paid_balanced_confirmed_finalists": len(confirmed),
        "paid_balanced_deep_confirmed_finalists": len(deep_confirmed),
        "balanced_finalist_failure_count": len(rerank_failures),
        "balanced_finalist_failures": rerank_failures[:4],
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
        "source_candidate_failures": failures[:4],
        "source_gear_and_native_item_legality_applied": True,
        "item_candidate_admission": "source_catalogue_proposals_native_authoritative",
        "python_item_candidate_pre_veto": False,
        "source_fixed_rotation_and_talents": True,
        "selected_validation": "3_native_world_fights_per_cold_gear_candidate",
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
