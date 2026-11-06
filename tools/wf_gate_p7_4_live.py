"""P7.4: evaluate one genuinely changed gear/enchant candidate in native Rust.

The sole active acceptance path preserves fixed talent/APL axes and native
INVALID/UNSUPPORTED/execution refusals. P7.5 alone owns the independent
300-second joint search and 1,000-stochastic holdout.
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
import time


from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity)
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
                    native_options = {"go_rules": True} if spec == "feral" else {}
                    native = production.native_source_control(
                        binary, request, 3, rng_mode="balanced", **native_options)
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
        "source_request_raw_sha256": meta.get(
            "source_request_raw_sha256", SAVED_BALANCE_RAW_SHA),
        "native_rules": "go_reference" if spec == "feral" else "forever",
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
    """P7.4 is one changed, paid native gear/enchant axis, not a 300s search.

    The retired FOREVER_P7_FULL_SOURCE_SEARCH switch cannot reintroduce a
    300-second cold search, a 1,000-fight holdout, or a 2D prerequisite.
    Those are not P7.4 acceptance predicates under docs/gates/P7.md.
    """
    return _run_native_gear_axis(root, class_key, level, spec)
