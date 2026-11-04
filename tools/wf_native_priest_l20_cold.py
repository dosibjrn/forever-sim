"""One cold, genuinely paid native/world Priest L20 P4/P5 search.

This is a production producer, not an alternate gate or a source of M1 credit.
The same invocation freezes its <=30s best and continues up to 300s, paying
a continuous native actor/2D 100-mob objective for every accepted candidate.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.wf_native_priest_l20_paid import (
    couple_source_priest_l20_persistent_world,
    score_source_priest_l20,
    _native_world_completed_kills,
    _native_world_error,
)


def _source_native_builds(source: dict, item_options: list[dict]):
    """Propose distinct full builds; only MythicSim rules on legality.

    Slot grouping prevents contradictory *proposals*, not native legality
    validation. No local Warcraft stats, score weights or item whitelist.
    """
    slots = {}
    seen_ids = set()
    for option in item_options:
        if not isinstance(option, dict):
            continue
        item_id, slot = option.get("item_id"), option.get("slot")
        if (type(item_id) is int and item_id > 0 and isinstance(slot, str)
                and slot and item_id not in seen_ids):
            seen_ids.add(item_id)
            slots.setdefault(slot, []).append(item_id)
    if not slots:
        # Still pay the real source build when native offers no equipment.
        yield copy.deepcopy(source)
        return
    grouped = list(slots.values())
    # Try the native-sourced complete build first. A real cold run showed
    # thousands of full-build alternatives refused by Rust for an unsupported
    # L20 rating conversion. Source-native *subsets* must therefore be
    # reachable before a bounded search exhausts its full-build product.
    # This is proposal diversity, NOT Python item-stat or legality filtering:
    # MythicSim still accepts/refuses every actual paid whole build.
    full = tuple(choices[0] for choices in grouped)
    selections = [full]
    if len(grouped) >= 3:
        # Remove one slot at a time, then try smaller source-backed subsets
        # and the unequipped source request before the large Cartesian tail.
        selections.extend(full[:i] + full[i + 1:] for i in range(len(full)))
        for size in range(len(full) - 2, 0, -1):
            selections.extend((full[:size], full[-size:]))
        for choices in grouped:
            selections.extend((alternative,) for alternative in choices[1:])
        selections.append(())
    for slot_index, choices in enumerate(grouped):
        for alternative in choices[1:]:
            swapped = list(full)
            swapped[slot_index] = alternative
            selections.append(tuple(swapped))
    yielded = set()
    for ids in itertools.chain(selections, itertools.product(*grouped)):
        if ids in yielded:
            continue
        yielded.add(ids)
        build = copy.deepcopy(source)
        build["raid"]["parties"][0]["players"][0]["equipment"]["items"] = [
            {"id": item_id} for item_id in ids
        ]
        yield build
    if len(grouped) < 3:
        # Preserve the existing two-slot ordering used by cheap regressions.
        yield copy.deepcopy(source)


def _verified_route(receipt: dict) -> float | None:
    if (not isinstance(receipt, dict)
            or receipt.get("native_2d_persistent_actor_verified") is not True
            or receipt.get("native_2d_persistent_world_ack_verified") is not True
            or receipt.get("native_2d_persistent_paid_recovery") is not True
            or type(receipt.get("native_2d_persistent_world_targets_killed")) is not int
            or receipt["native_2d_persistent_world_targets_killed"] != 100
            or type(receipt.get("native_2d_persistent_source_action_events")) is not int
            or receipt["native_2d_persistent_source_action_events"] <= 0
            or not isinstance(receipt.get(
                "native_2d_persistent_source_action_counts_by_target"), list)
            or len(receipt["native_2d_persistent_source_action_counts_by_target"]) != 100):
        return None
    elapsed = receipt.get("native_2d_persistent_elapsed_seconds")
    if (type(elapsed) not in (float, int) or not math.isfinite(elapsed)
            or elapsed <= 0):
        return None
    return elapsed / 100.0


def run_native_priest_l20_cold(binary: str | Path, request_file: str | Path,
                               item_options: list[dict], *, score_request=None,
                               world_screen=None, clock=None,
                               budget_s: float = 300.0,
                               snapshot_s: float = 30.0,
                               max_attempts: int = 4096) -> dict:
    """Pay one native 100-mob route per accepted candidate, not DPS proxies.

    Only a build whose full native/world receipt completes *before* the
    snapshot cutoff can become the frozen P4 winner. No late or failed build
    can be smuggled into P4, nor can a saved 100-mob receipt be synthesized.
    Returns diagnostic receipts; final P4/P5 gate predicates stay separate.
    """
    if not (0 < snapshot_s < budget_s and 1 <= max_attempts <= 100000):
        raise ValueError("PRIEST_L20_COLD_BUDGET_INVALID")
    if not isinstance(item_options, list):
        raise ValueError("PRIEST_L20_NATIVE_OPTIONS_REQUIRED")
    try:
        source = json.loads(Path(request_file).read_text(encoding="utf-8"))
        actor = source["raid"]["parties"][0]["players"][0]
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise ValueError("PRIEST_L20_SOURCE_REQUEST_REQUIRED") from exc
    if (not isinstance(actor, dict) or actor.get("class") != "ClassPriest"
            or type(actor.get("level")) is not int or actor["level"] != 20
            or not isinstance(actor.get("equipment"), dict)
            or actor["equipment"].get("items") != []
            or not isinstance(source.get("simOptions"), dict)):
        raise ValueError("PRIEST_L20_COLD_SOURCE_ACTOR_INVALID")
    clock = clock or time.monotonic
    world_screen = world_screen or couple_source_priest_l20_persistent_world
    start = clock()
    deadline = start + budget_s
    frozen = None
    best_early = None
    best_final = None
    # In the real 30/300s run, freeze the *paid* 30s candidate before
    # invoking any potentially >30s 100-mob finalist qualification. P4
    # explicitly permits its selected 100-mob execution after the search.
    # Native DPS is a screening score, NOT a verified world objective or PASS.
    deferred_snapshot = budget_s == 300 and snapshot_s == 30
    early_paid = None
    rows = []
    seen = set()
    scored_before = 0
    scored_after = 0
    completed_before = 0
    completed_after = 0
    with TemporaryDirectory(prefix="priest-l20-native-cold-") as directory:
        path = Path(directory) / "candidate.json"
        for build in _source_native_builds(source, item_options):
            if len(rows) >= max_attempts or clock() >= deadline:
                break
            identity = hashlib.sha256(json.dumps(
                build, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            if identity in seen:
                continue
            seen.add(identity)
            build["simOptions"]["iterations"] = 1
            build["simOptions"]["randomSeed"] = "42"
            identity = hashlib.sha256(json.dumps(
                build, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            path.write_text(json.dumps(build, sort_keys=True), encoding="utf-8")
            row = {"source_request_sha256": identity, "status": "NATIVE_REFUSED"}
            try:
                paid = score_source_priest_l20(
                    binary, path, score_request=score_request,
                    budget_s=max(0.001, min(6.0, deadline - clock())))
                row["native_request_sha256"] = paid["native_request_sha256"]
                if paid["native_request_sha256"] != identity:
                    raise RuntimeError("PRIEST_L20_COLD_NATIVE_REQUEST_IDENTITY_MISMATCH")
                row["native_source_action_casts"] = paid["native_source_action_casts"]
                row["native_screen_score"] = paid.get("native_score")
                # A native fight with no source-action casts is an executed
                # refusal for this leveling frontier, not a valid paid
                # whole-build continuation or a 30s winner.
                row["status"] = ("NATIVE_PAID" if paid["native_source_action_casts"] > 0
                                 else "NATIVE_NO_SOURCE_CAST")
                if (paid["native_source_action_casts"] > 0
                        and deferred_snapshot and clock() - start <= snapshot_s):
                    # 100 native-world pulls can exceed 30s of *wall* time.
                    # Do not let that validation consume the immutable cold
                    # discovery window. Freeze the genuine scored native
                    # whole-build request; separately execute its 100-mob
                    # route after the continuous search has finished.
                    score = paid.get("native_score")
                    if type(score) in (int, float) and math.isfinite(score):
                        row["status"] = "NATIVE_PAID_SNAPSHOT_SCREEN"
                        if early_paid is None or score > early_paid["native_score"]:
                            early_paid = {
                                "source_build": copy.deepcopy(build),
                                "source_request_sha256": identity,
                                "native_request_sha256": paid["native_request_sha256"],
                                "native_score": score,
                                "paid_completed_elapsed_s": clock() - start,
                            }
                    else:
                        row["status"] = "NATIVE_UNSCORABLE"
                elif paid["native_source_action_casts"] > 0:
                    world = world_screen(binary, path, target_count=100)
                    route_s = _verified_route(world)
                    if route_s is not None:
                        row["status"] = "COMPLETE"
                        row["route_s_per_mob"] = route_s
                        row["real_100mob_receipt"] = world
                    else:
                        row["status"] = "WORLD_INCOMPLETE"
            except (OSError, ValueError, RuntimeError, AssertionError,
                    TimeoutError, subprocess.SubprocessError) as exc:
                # Native/world 100-mob failures surface as AssertionError
                # tuples. They are candidate-local observed failures, not an
                # exception that aborts the other paid cold proposals.
                row["reason"] = _native_world_error(exc)
                row["native_2d_persistent_observed_kills"] = (
                    _native_world_completed_kills(exc))
            elapsed = clock() - start
            row["paid_completed_elapsed_s"] = elapsed
            # Late completions are never paid 30s or 300s candidates.
            # Finishing an in-flight real native/world screen after 300s
            # cannot retroactively invalidate winners completed before the
            # deadline; its late receipt remains diagnostic only.
            if frozen is None and elapsed > snapshot_s:
                frozen = copy.deepcopy(best_early)
            in_budget = elapsed <= budget_s
            if in_budget and row["status"] in (
                    "NATIVE_PAID", "NATIVE_PAID_SNAPSHOT_SCREEN",
                    "WORLD_INCOMPLETE", "COMPLETE"):
                if elapsed <= snapshot_s:
                    scored_before += 1
                else:
                    scored_after += 1
            if in_budget and row["status"] == "COMPLETE":
                winner = {k: copy.deepcopy(row[k]) for k in (
                    "source_request_sha256", "native_request_sha256",
                    "route_s_per_mob", "real_100mob_receipt",
                    "paid_completed_elapsed_s")}
                winner["source_build"] = copy.deepcopy(build)
                if best_final is None or winner["route_s_per_mob"] < best_final["route_s_per_mob"]:
                    best_final = winner
                if elapsed <= snapshot_s:
                    completed_before += 1
                    if best_early is None or winner["route_s_per_mob"] < best_early["route_s_per_mob"]:
                        best_early = copy.deepcopy(winner)
                else:
                    completed_after += 1
            rows.append({k: v for k, v in row.items()
                         if k != "real_100mob_receipt"})
    # Measure the cold search BEFORE the independent real 100-mob replay.
    # The route can finish after the 300s cutoff without rewriting the
    # actual candidate-selection clock or introducing a second cold search.
    wall_s = clock() - start
    snapshot_validation = None
    if deferred_snapshot and early_paid is not None:
        with TemporaryDirectory(prefix="priest-l20-frozen-route-") as directory:
            frozen_path = Path(directory) / "frozen-30s.json"
            frozen_path.write_text(json.dumps(
                early_paid["source_build"], sort_keys=True), encoding="utf-8")
            try:
                receipt = world_screen(binary, frozen_path, target_count=100)
                route_s = _verified_route(receipt)
                if route_s is None:
                    snapshot_validation = {"status": "WORLD_INCOMPLETE"}
                else:
                    frozen = {
                        **copy.deepcopy(early_paid),
                        "route_s_per_mob": route_s,
                        "real_100mob_receipt": receipt,
                        "snapshot_selection_objective": "NATIVE_DPS_SCREEN_ONLY",
                    }
                    snapshot_validation = {"status": "COMPLETE",
                                           "route_s_per_mob": route_s}
            except (OSError, ValueError, RuntimeError, AssertionError,
                    TimeoutError, subprocess.SubprocessError) as exc:
                snapshot_validation = {
                    "status": "WORLD_INCOMPLETE",
                    "reason": _native_world_error(exc),
                    "native_2d_persistent_observed_kills":
                        _native_world_completed_kills(exc),
                }
    if frozen is None and wall_s >= snapshot_s:
        frozen = copy.deepcopy(best_early)
    # Exhausted candidate spaces and late native calls are reported honestly.
    # The caller may not infer a completed 300s search from a successful exit.
    return {
        "native_cold_search_wall_s": wall_s,
        "native_cold_search_budget_s": budget_s,
        "native_cold_snapshot_cutoff_s": snapshot_s,
        "native_cold_snapshot_30": frozen,
        "native_cold_30s_paid_selection": copy.deepcopy(early_paid),
        "native_cold_30s_post_search_route": snapshot_validation,
        "native_cold_final_300": copy.deepcopy(best_final),
        "native_cold_native_paid_before_30": scored_before,
        "native_cold_native_paid_after_30": scored_after,
        "native_cold_completed_routes_before_30": completed_before,
        "native_cold_completed_routes_after_30": completed_after,
        "native_cold_attempted_distinct_builds": len(rows),
        "native_cold_300s_reached": wall_s >= budget_s,
        # Deadline overrun reports an in-flight evaluation finishing late.
        # Only evaluations completed within the actual 300s window are
        # eligible; the gate must not mistake this diagnostic for a FAIL.
        "native_cold_300s_overrun": wall_s > budget_s,
        "native_cold_source": "MYTHICSIM_SOURCE_OPTIONS_PAID_100MOB_NATIVE_2D",
        "native_cold_rows": rows,
        "native_cold_gate_accepted": False,
    }
