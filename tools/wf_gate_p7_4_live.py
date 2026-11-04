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


def _paid_gear_elite_choice(elites, rng, proposal_index, reranked=()):
    """Use paid multi-seed Balanced finalists for part of local gear search.

    Every fifth proposal stays a fresh cold draw. Once native+2D has paid for
    independent finalist screens, alternating local proposals exploit the top
    four of their more reliable scores instead of continuing exclusively from
    noisy three-fight leaders. Other proposals retain the top-15 paid archive
    for diversity. Neither the reference nor stochastic holdout seeds search.
    """
    if proposal_index % 5 == 0:
        return None
    if reranked and proposal_index % 2 == 0:
        ranked = sorted(reranked, key=lambda row: row[0], reverse=True)
        return rng.choice(ranked[:min(4, len(ranked))])[3]
    if not elites:
        return None
    return rng.choice(elites[:min(15, len(elites))])[1]


def _paid_step_has_budget(search_start: float, observed_max_s: float) -> bool:
    """Do not launch an indivisible native+2D paid call too near 300s.

    A full candidate/rerank includes multiple subprocess calls. The old loop
    only checked time at its head, so a 24-fight finalist started at 299s
    could finish at 302s and prevent the independent 1,000-fight holdout.
    Reserve 1.5x the slowest observed same-kind step plus 250ms, while
    leaving the final 300s deadline and all source-paid results unchanged.
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


def _paid_p74_balanced_finalist(production, binary, request, distance, *,
                                seeds=("1955004", "1955047")):
    """Re-score an already paid gear candidate with independent balanced seeds.

    These are native+2D measurements inside the same 300s search, not a
    stochastic holdout. Keep the original paid request immutable for freezing.
    """
    scores = []
    latest_live = None
    for seed in seeds:
        candidate = copy.deepcopy(request)
        candidate.setdefault("simOptions", {})["randomSeed"] = str(seed)
        with tempfile.TemporaryDirectory(prefix="forever_p74_balanced_") as tmp:
            path = Path(tmp) / "paid-balanced-gear.json"
            path.write_text(json.dumps(candidate))
            native = production.native_source_control(
                binary, path, 3, rng_mode="balanced")
            live = production.run(
                binary, path, distance=distance, iterations=3,
                rng_mode="balanced")
            mismatch = _source_native_world_parity(native, live, 3, allow_world_lethal=True)
            if mismatch is not None:
                raise ValueError("P74_BALANCED_FINALIST_NATIVE_WORLD_PARITY:" + mismatch)
        if (live.get("iterations_done") != 3
                or live.get("native_damage_events", 0) <= 0
                or live.get("native_world_ticks", 0) <= 0):
            raise ValueError("P74_BALANCED_FINALIST_WORLD_INCOMPLETE")
        score = float(live["world_mean_dps"])
        if not 0 <= score < float("inf"):
            raise ValueError("P74_BALANCED_FINALIST_DPS_INVALID")
        scores.append(score)
        latest_live = live
    return sum(scores) / len(scores), latest_live


def _freeze_paid_p74_balanced_winner(screen_best, reranked, confirmed):
    """Pick on independent balanced measurements, never the 1,000 holdout."""
    if reranked:
        confirmed_rows = [row for row in reranked if row[2] in confirmed]
        score, live, sha, request, screen_score = max(
            confirmed_rows or reranked, key=lambda row: row[0])
        label = ("paid_4x3_balanced_native_world_confirmed"
                 if confirmed_rows else "paid_2x3_balanced_native_world_finalist")
        return score, live, sha, request, screen_score, label
    score, live, sha, request = screen_best
    return score, live, sha, request, score, "best_balanced_live_screen"




def _run_native_gear_axis(root: Path, class_key: str, level: int, spec: str) -> dict:
    """Pay a genuinely changed gear/enchant candidate in selected native Rust.

    P7.4 is a single-axis reachability gate, not the P7.5 joint 300-second
    search or stochastic holdout. The pinned native item/enchants source
    provides proposals, and native Rust alone accepts or rejects each build.
    """
    import math
    from uuid import uuid4
    from tools.wf_gate_p7_3_live import _native_refusal

    prepared = _pinned_source_runtime(
        root, class_key, level, spec, "P7.4", require_world=False)
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    source_dir = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(source_dir))
    try:
        gear_search = _source_module(
            source_dir / "p74_gear_search.py", "p74_pinned_native_options")
    finally:
        sys.path.remove(str(source_dir))
    production = _source_module(
        source_dir / "live_world_probe.py", "p74_selected_native_scorer")
    upstream = binary.parents[2]
    items = upstream / "data/items.jsonl"
    enchants = upstream / "data/enchants.jsonl"
    if not items.is_file() or not enchants.is_file():
        return {"status": "BLOCKED",
                "reasons": ["P7_4_PINNED_RUST_ITEM_OR_ENCHANT_DATA_MISSING"]}
    try:
        pool, enchant_pools, options_meta = gear_search.pinned_rust_candidate_pool(
            items, enchants)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError,
            AssertionError, subprocess.SubprocessError) as exc:
        return {"status": "FAIL", "reasons": [
            "P7_4_PINNED_RUST_ITEM_OPTIONS_FAILED:"
            + type(exc).__name__ + ":" + str(exc)[:180]]}

    reference_player = base["raid"]["parties"][0]["players"][0]
    reference_items = reference_player["equipment"]["items"]
    # Enumerate bounded source-admitted one-slot changes instead of replacing
    # all slots at once (which usually makes an otherwise legal request invalid).
    # Nothing here judges equipment restrictions: every change goes to Rust.
    moves = []
    per_slot = []
    for slot, reference in enumerate(reference_items):
        item_ids = []
        for value in pool.get(slot, ()):
            if (type(value) is int and value != reference["id"]
                    and value not in item_ids):
                item_ids.append(value)
            if len(item_ids) >= 8:
                break
        enchant_ids = []
        for value in enchant_pools.get(slot, ()):
            if (value is None or type(value) is int) and (
                    value != reference.get("enchant") and value not in enchant_ids):
                enchant_ids.append(value)
            if len(enchant_ids) >= 4:
                break
        per_slot.append([("item", slot, v) for v in item_ids]
                        + [("enchant", slot, v) for v in enchant_ids])
    # Round robin avoids spending the entire bounded budget on the first slot.
    for index in range(max((len(choices) for choices in per_slot), default=0)):
        for choices in per_slot:
            if index < len(choices):
                moves.append(choices[index])
    seen = set()
    paid = invalid = unsupported = errors = 0
    refusals = []
    failures = []
    best = None
    started = time.monotonic()
    for kind, slot, value in moves[:96]:
        candidate = copy.deepcopy(base)
        player = candidate["raid"]["parties"][0]["players"][0]
        equipped = player["equipment"]["items"][slot]
        if kind == "item":
            equipped["id"] = value
            # A previous item's enchant need not be compatible with this one;
            # a changed item alone is already a P7.4 candidate.
            equipped.pop("enchant", None)
        elif value is None:
            equipped.pop("enchant", None)
        else:
            equipped["enchant"] = value
        if (player.get("rotation") != reference_player.get("rotation")
                or player.get("talentsString") != reference_player.get("talentsString")
                or player["equipment"] == reference_player["equipment"]):
            continue
        candidate_sha = hashlib.sha256(
            json.dumps(candidate, sort_keys=True).encode()).hexdigest()
        if candidate_sha in seen:
            continue
        seen.add(candidate_sha)
        try:
            with tempfile.TemporaryDirectory(prefix="forever_p74_native_") as tmp:
                request = Path(tmp) / "changed-equipment.json"
                request.write_text(json.dumps(candidate))
                try:
                    native = production.native_source_control(
                        binary, request, 3, rng_mode="balanced")
                except Exception as exc:
                    status, reason = _native_refusal(exc)
                    if status == "INVALID":
                        invalid += 1
                        refusals.append(status + ":" + reason[:240])
                    elif status == "UNSUPPORTED":
                        unsupported += 1
                        refusals.append(status + ":" + reason[:240])
                    else:
                        errors += 1
                        failures.append(status + ":" + reason[:240])
                    continue
            if type(native.get("iterations")) is not int or native["iterations"] != 3:
                raise ValueError("P7_4_NATIVE_PAID_ITERATIONS_INCOMPLETE")
            score = native.get("native_dps")
            if (type(score) not in (int, float)
                    or not math.isfinite(score) or score < 0):
                raise ValueError("P7_4_NATIVE_PAID_DPS_INVALID")
            paid += 1
            score = float(score)
            if best is None or score > best[0]:
                best = (score, candidate_sha, candidate)
            break  # One genuinely accepted, changed native-paid axis is enough.
        except (ValueError, RuntimeError, OSError, KeyError, TypeError,
                AssertionError, subprocess.SubprocessError) as exc:
            errors += 1
            failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    elapsed = time.monotonic() - started
    shared = {
        "production_engine": "pinned_mythicsim_rust_native",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py:native_source_control",
        "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "reference_profile": meta.get("selected_reference_profile", "balance"),
        "checkpoint_spec": spec,
        "source_fixed_rotation_and_talents": True,
        "cold_unique_source_requests": len(seen),
        "source_legal_cold_candidates_paid": paid,
        "native_invalid_candidates": invalid,
        "native_unsupported_candidates": unsupported,
        "native_execution_errors": errors,
        "native_refusal_samples": refusals[:4],
        "source_candidate_failures": failures[:4],
        "source_candidate_failure_count": len(failures) + len(refusals),
        "pinned_rust_item_options_applied": True,
        "item_candidate_admission": "pinned_rust_items_jsonl",
        "pinned_rust_unique_item_options": options_meta["unique_item_options"],
        "pinned_rust_unique_enchant_options": options_meta["unique_enchant_options"],
        "search_wall_s": elapsed,
        "independent_300s_search_requested": False,
        "independent_300s_search_completed": False,
        "search_rng_mode": "balanced",
        "selected_validation": "3_native_balanced_fights_per_changed_gear_or_enchant",
    }
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_4_NO_NATIVE_PAID_CHANGED_GEAR_CANDIDATE"],
                **shared}
    score, winner_sha, winner = best
    return {
        "status": "PASS",
        "reasons": [],
        "runtime_proof": {
            "executed": True,
            "engine_revision": meta.get("selected_engine_revision", PINNED_RUST),
            "source_revision": winner_sha,
            "run_id": "P7.4-native-" + str(uuid4()),
        },
        "winner_native_dps": score,
        "cold_winner_request_sha256": winner_sha,
        "cold_winner_gear": [
            {"slot": slot, "item_id": int(item["id"]),
             "enchant_id": item.get("enchant")}
            for slot, item in enumerate(
                winner["raid"]["parties"][0]["players"][0]["equipment"]["items"])
        ],
        **shared,
    }


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    # Default P7.4 acceptance is the approved direct native single-axis test.
    # FOREVER_P7_FULL_SOURCE_SEARCH=1 retains the old expensive exploration
    # solely as an opt-in diagnostic, not an acceptance prerequisite.
    if os.environ.get("FOREVER_P7_FULL_SOURCE_SEARCH", "0") == "0":
        return _run_native_gear_axis(root, class_key, level, spec)
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
    rng = random.Random(667)
    player = base["raid"]["parties"][0]["players"][0]
    executed = 0
    best = None
    elites = []  # top 24 source-legal loadouts scored with balanced RNG
    screen_archive = []  # top paid native+2D screens eligible for reranking
    reranked = []  # independent 2x3 balanced native+2D finalist scores
    rerank_seen = set()
    confirmed = set()
    confirmation_attempted = set()
    rerank_failures = []
    worst_rerank_s = 0.0
    failures = []
    seen = set()
    proposals = 0
    upstream = binary.parents[2]
    items = upstream / "data/items.jsonl"
    enchants = upstream / "data/enchants.jsonl"
    if not items.is_file() or not enchants.is_file():
        return {"status": "BLOCKED",
                "reasons": ["P7_4_PINNED_RUST_ITEM_OR_ENCHANT_DATA_MISSING"]}
    search_start = time.monotonic()
    search_deadline = search_start + 300.0
    worst_screen_s = 0.0
    try:
        pool, enchant_pools, options_meta = gear_search.pinned_rust_candidate_pool(items, enchants)
    except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
            TypeError, AssertionError, subprocess.SubprocessError) as exc:
        return {
            "status": "FAIL",
            "reasons": ["P7_4_PINNED_RUST_ITEM_OPTIONS_FAILED:"
                        + type(exc).__name__ + ":" + str(exc)[:240]],
            "production_engine": "pinned_mythicsim_rust_gsim_2d",
            "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
            "item_candidate_admission": "pinned_rust_items_jsonl",
        }
    while True:
        elapsed = time.monotonic() - search_start if full_search else 0.0
        if (full_search and elapsed >= 300.0
                or not full_search and proposals >= 3):
            break
        # The old P7.4 froze the maximum of hundreds of noisy three-fight
        # scores. Independently rerank paid leaders *inside* the same
        # search budget to avoid selecting a lucky-screen outlier.
        if full_search and (elapsed >= 240.0 or
                            _p74_early_rerank_due(
                                elapsed, len(reranked))):
            confirmation = (
                _next_p74_confirmation(
                    reranked, confirmation_attempted, elapsed)
                if len(confirmation_attempted) < 3 else None)
            if confirmation is not None and _paid_step_has_budget(
                    search_start, max(worst_rerank_s, worst_screen_s)):
                index, row = confirmation
                confirmation_attempted.add(row[2])
                started = time.perf_counter()
                try:
                    second_score, second_live = _paid_p74_balanced_finalist(
                        production, binary, row[3],
                        player["distanceFromTarget"],
                        seeds=("1955113", "1955139"))
                    # Compare finalists on the same independent 12 fights;
                    # the original lucky 3-fight screen is diagnostic only.
                    reranked[index] = (
                        (row[0] + second_score) / 2,
                        second_live, *row[2:])
                    confirmed.add(row[2])
                except (ValueError, RuntimeError, OSError, KeyError,
                        TimeoutError, TypeError, AssertionError,
                        subprocess.SubprocessError) as exc:
                    rerank_failures.append(
                        "CONFIRM:" + type(exc).__name__ + ":" + str(exc)[:160])
                finally:
                    worst_rerank_s = max(
                        worst_rerank_s, time.perf_counter() - started)
                continue
            pending = next((
                row for row in screen_archive
                if row[2] not in rerank_seen), None)
            if (pending is not None and len(reranked) < 6
                    and _paid_step_has_budget(
                        search_start, max(worst_rerank_s, worst_screen_s))):
                screen_score, screen_live, candidate_sha, candidate = pending
                rerank_seen.add(candidate_sha)
                started = time.perf_counter()
                try:
                    balanced_score, balanced_live = _paid_p74_balanced_finalist(
                        production, binary, candidate,
                        player["distanceFromTarget"])
                    reranked.append((
                        balanced_score, balanced_live, candidate_sha,
                        candidate, screen_score))
                except (ValueError, RuntimeError, OSError, KeyError,
                        TimeoutError, TypeError, AssertionError,
                        subprocess.SubprocessError) as exc:
                    rerank_failures.append(
                        type(exc).__name__ + ":" + str(exc)[:160])
                finally:
                    worst_rerank_s = max(
                        worst_rerank_s, time.perf_counter() - started)
                continue
        if full_search and not _paid_step_has_budget(
                search_start, worst_screen_s):
            break  # preserve time for the final 1,000-fight holdout
        paid_start = time.perf_counter()
        proposals += 1
        try:
            # Local exploitation uses only a winner already paid in THIS
            # cold run; every fifth draw is independently cold. The saved
            # gear and other gates' winners are never injected as elites.
            # Only the balanced-scored paid archive may guide local edits.
            elite = (_paid_gear_elite_choice(elites, rng, proposals, reranked)
                     if full_search else None)
            candidate = _cold_gear(
                base, None, gear_search, rng, pool=pool,
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
                parity_failure = _source_native_world_parity(native, live, 3, allow_world_lethal=True)
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
            screen_archive.append((score, live, candidate_sha, candidate))
            screen_archive.sort(key=lambda row: row[0], reverse=True)
            del screen_archive[24:]
            if best is None or score > best[0]:
                best = (score, live, candidate_sha, candidate)
        except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
                TypeError, AssertionError, subprocess.SubprocessError) as exc:
            failures.append(type(exc).__name__ + ":" + str(exc)[:800])
        finally:
            worst_screen_s = max(
                worst_screen_s, time.perf_counter() - paid_start)

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
                "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
                "pinned_rust_unique_item_options": options_meta["unique_item_options"],
                "pinned_rust_unique_enchant_options": options_meta["unique_enchant_options"],
                "item_candidate_admission": "pinned_rust_items_jsonl",
                "source_candidate_failure_count": len(failures),
                "source_candidate_failures": failures[:4]}

    # Freeze the best balanced-scored loadout before the independent
    # stochastic acceptance holdout. No stochastic score feeds search ranking.
    (score, live, candidate_sha, frozen_winner,
     winner_screen_dps, winner_selection) = _freeze_paid_p74_balanced_winner(
         best, reranked, confirmed)
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
                    native, world, n, expected_raw_sha=frozen_sha,
                    allow_world_lethal=True)
                if mismatch is not None:
                    raise ValueError("FROZEN_STOCHASTIC_NATIVE_WORLD_PARITY:" + mismatch)
                # Score the native engine's coupled world run. A standalone
                # source-only control has no finite-world-HP feedback and is
                # not comparable if any holdout fight ends on a lethal ACK.
                native_control_dps = float(native["native_dps"])
                native_dps = float(world["native_dps"])
                world_dps = float(world["world_mean_dps"])
                lethal_fights = int(world.get("world_target_lethal_fights", 0))
                final = {
                    "frozen_request_raw_sha256": frozen_sha,
                    "frozen_stochastic_iterations": n,
                    "frozen_stochastic_native_dps": native_dps,
                    "frozen_stochastic_native_control_dps": native_control_dps,
                    "frozen_stochastic_native_control_comparable": lethal_fights == 0,
                    "frozen_stochastic_world_dps": world_dps,
                    "frozen_stochastic_world_target_lethal_fights": lethal_fights,
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
        "paid_balanced_finalists": len(reranked),
        "paid_balanced_confirmed": len(confirmed),
        "balanced_finalist_failures": rerank_failures[:4],
        "paid_stochastic_finalists": 0,
        "paid_stochastic_confirmed_finalists": 0,
        "paid_stochastic_deep_confirmed_finalists": 0,
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
        "world_target_lethal_fights": int(live.get("world_target_lethal_fights", 0)),
        "native_source_control_comparable": int(
            live.get("world_target_lethal_fights", 0)) == 0,
        "source_legal_cold_candidates_paid": executed,
        "source_candidate_failure_count": len(failures),
        "source_candidate_failures": failures[:4],
        "source_gear_and_native_item_legality_applied": True,
        "pinned_rust_item_options_applied": True,
        "item_candidate_admission": "pinned_rust_items_jsonl",
        "pinned_rust_unique_item_options": options_meta["unique_item_options"],
        "pinned_rust_unique_enchant_options": options_meta["unique_enchant_options"],
        "python_item_candidate_pre_veto": False,
        "source_fixed_rotation_and_talents": True,
        "selected_validation": (
            "3_native_world_fights_per_cold_gear_candidate"
            if not reranked else winner_selection),
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
