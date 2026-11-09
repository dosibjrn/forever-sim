#!/usr/bin/env python3
"""One cold Warlock L20 native/gsim search with paid recovery and 100-mob finalists.

This is a producer for the existing P4-P6 objective, not an alternate gate.
Rust supplies source options and judges every submitted build. The existing
native/world runner supplies the measured two-target screening objective and
a separate full continuous 100-target receipt for each frozen winner.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))

from native_matrix import NativeUnscoredCandidate, search_native  # noqa: E402
from native_options import native_equipment_proposals, query_native_options  # noqa: E402
from tools.wf_warlock_l20_talent_apl_optimizer import (  # noqa: E402
    proposals_from_native_talents,
)
from tools.wf_warlock_l20_100mob import guarded_life_tap_action  # noqa: E402


def actor(request: dict) -> dict:
    return request["raid"]["parties"][0]["players"][0]


def identity(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def native_candidate_domain(reference: dict, options: dict, seed: int) -> dict:
    """Only source-returned alternatives; no Python game eligibility judgment."""
    player = actor(reference)
    items = player["equipment"]["items"]
    gear = native_equipment_proposals(options, items)
    talents = list(dict.fromkeys(
        row["talents"] for row in proposals_from_native_talents(
            options, player.get("talentsString", "0-0-0"), seed)
    ))
    apl = copy.deepcopy(player["rotation"]["priorityList"])
    apl_variants = [apl]
    if len(apl) > 1:
        apl_variants.append(list(reversed(apl)))
    native_actions = []
    # Candidate spell IDs come only from get_options, and Rust still decides
    # whether a spell is executable at this level/talent/build. A prefix-only
    # proposal cannot replace an existing filler or try a new standalone APL:
    # both are genuine candidate-search dimensions, not Python spell rules.
    for spell in options["spells"]:
        spell_id = spell.get("spell_id") if isinstance(spell, dict) else None
        if type(spell_id) is int and spell_id > 0:
            # This is source-named Life Tap, not a Python spell catalogue.
            # An unconditional candidate can self-kill a retained actor;
            # offer only native health-guarded APL policies for these ranks.
            if str(spell.get("name", "")).casefold().strip() == "life tap":
                actions = [
                    guarded_life_tap_action(
                        spell_id, mana_percent=mana, health_percent=health)
                    for mana in (20, 40) for health in (50, 70)
                ]
            else:
                actions = [{"action": {"castSpell": {
                    "spellId": {"spellId": spell_id}}}}]
            for action in actions:
                native_actions.append(action)
                apl_variants.append([copy.deepcopy(action), *copy.deepcopy(apl)])
                apl_variants.append([copy.deepcopy(action)])
                for index in range(len(apl)):
                    proposal = copy.deepcopy(apl)
                    proposal[index] = copy.deepcopy(action)
                    apl_variants.append(proposal)
    unique_apl = list({json.dumps(x, sort_keys=True): x
                       for x in apl_variants}.values())
    unique_actions = list({json.dumps(x, sort_keys=True): x
                           for x in native_actions}.values())
    # The native Warlock options endpoint supplies the exact proto enum numbers.
    # These are proposals only: native prepare/combat alone accepts or refuses
    # a summon for the actual level, build and encounter.
    pets = list(dict.fromkeys(
        row["proto_enum_value"] for row in options.get("pets", [])
        if isinstance(row, dict) and type(row.get("proto_enum_value")) is int
    ))
    return {"gear": gear, "talents": talents or [player.get("talentsString", "0-0-0")],
            "apl": unique_apl, "apl_actions": unique_actions, "pets": pets,
            # These are recovery *policy proposals*, not Python regen mechanics.
            "recovery": [(0.35, 0.10), (0.50, 0.10),
                         (0.50, 0.25), (0.70, 0.25)]}


def candidate_factory(reference: dict, domain: dict):
    """Cold whole-build proposals and native-sourced mutations, never seeded scores."""
    def mutate(candidate: dict, rng: random.Random, *, cold: bool = False) -> dict:
        value = {"source": copy.deepcopy(reference),
                 "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1}
                 } if cold else copy.deepcopy(candidate)
        axes = ("gear", "talents", "apl", "recovery")
        if domain.get("pets"):
            axes += ("pet",)
        # A cold proposal changes multiple axes; subsequent mutation explores
        # both local and joint moves using the generic search scheduler.
        selected = rng.sample(axes, rng.randint(2, len(axes)) if cold
                              else rng.randint(1, min(3, len(axes))))
        player = actor(value["source"])
        for axis in selected:
            if axis == "gear" and domain["gear"]:
                position = rng.choice(list(domain["gear"]))
                player["equipment"]["items"][position] = copy.deepcopy(
                    rng.choice(domain["gear"][position]))
            elif axis == "talents":
                player["talentsString"] = rng.choice(domain["talents"])
            elif axis == "apl":
                actions = domain.get("apl_actions") or []
                if not cold and actions and rng.random() < 0.75:
                    # Recombine source-returned actions in the current elite.
                    # A whole-APL replacement alone cannot accumulate two new
                    # spells, so a valid multi-spell challenger is unreachable.
                    # Rust remains the only judge of executable rotations.
                    rotation = player["rotation"]["priorityList"]
                    if len(rotation) > 1 and rng.random() > 0.70:
                        # Reorder/prune an evolved policy in one mutation:
                        # replacing its whole APL loses previously discovered
                        # Rust actions, while elite-only search cannot rely on
                        # keeping a worse intermediate edit. Never delete the
                        # last action; Rust judges executable candidates.
                        operation = rng.choice(("move", "remove"))
                        index = rng.randrange(len(rotation))
                        if operation == "move":
                            entry = rotation.pop(index)
                            rotation.insert(rng.randrange(len(rotation) + 1),
                                            entry)
                        else:
                            rotation.pop(index)
                    else:
                        action = copy.deepcopy(rng.choice(actions))
                        operation = rng.choice(("replace", "insert"))
                        if operation == "replace" and rotation:
                            rotation[rng.randrange(len(rotation))] = action
                        else:
                            rotation.insert(rng.randrange(len(rotation) + 1), action)
                else:
                    player["rotation"]["priorityList"] = copy.deepcopy(
                        rng.choice(domain["apl"]))
            elif axis == "pet":
                # Request shape is the existing native protojson WarlockOptions
                # classOptions.summon field, not a Python demon model.
                player.setdefault("warlock", {}).setdefault("options", {}).setdefault(
                    "classOptions", {})["summon"] = rng.choice(domain["pets"])
            elif axis == "recovery":
                hp, mana = rng.choice(domain["recovery"])
                value["recovery"] = {"health_threshold": hp, "mana_threshold": mana}
        return value

    # Give the known request its own real paid trial before mutating any axis.
    # An otherwise legal reference can be the only executable proposal in a
    # short 30s window; the Rust/world evaluator, not this scheduler, still
    # decides whether it executes and earns a score.
    reference_proposed = False

    def propose(rng):
        nonlocal reference_proposed
        if not reference_proposed:
            reference_proposed = True
            return {
                "source": copy.deepcopy(reference),
                "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1},
            }
        return mutate({}, rng, cold=True)

    def change(previous, rng):
        return mutate(previous, rng)

    return propose, change


def paid_chain(binary: Path, candidate: dict, out: Path, *,
               targets: int, timeout: float) -> dict:
    """Invoke exactly the production paid Decisions world runner, not a proxy."""
    out.mkdir(parents=True, exist_ok=True)
    source = out / "candidate.request.json"
    source.write_text(json.dumps(candidate["source"], sort_keys=True) + "\n")
    policy = candidate["recovery"]
    command = [
        sys.executable, str(ROOT / "tools/wf_warlock_l20_100mob.py"),
        "--binary", str(binary.resolve()), "--source", str(source.resolve()),
        "--out", str((out / "world").resolve()),
        "--targets", str(targets), "--variant", "best_apl",
        "--recovery-policy", "decisions",
        "--health-threshold", str(policy["health_threshold"]),
        "--mana-threshold", str(policy["mana_threshold"]),
    ]
    # The native/world receipt records actual incoming damage, but a
    # surviving 100-mob candidate may legitimately avoid every hit with
    # control, pet tanking or movement. Positive damage taken is not one of
    # the approved P4-P6 acceptance predicates; do not impose a hidden gate.
    # A retry in the same output directory must consume a receipt produced
    # by THIS subprocess. Otherwise an earlier successful native run can be
    # silently reused when the new invocation exits without writing a file.
    summary_path = out / "world" / "summary.json"
    summary_path.unlink(missing_ok=True)
    process = subprocess.run(command, capture_output=True, text=True,
                             timeout=timeout, check=False, cwd=ROOT)
    if not summary_path.exists():
        raise RuntimeError("Native paid runner did not emit a structured receipt: " +
                           (process.stderr or process.stdout)[-800:])
    summary = json.loads(summary_path.read_text())
    rows = summary.get("results")
    if (not isinstance(rows, list) or len(rows) != 1
            or not isinstance(rows[0], dict)):
        raise RuntimeError("Native paid runner returned an invalid summary")
    receipt = rows[0]
    # The native 100-mob tool writes these exact input and engine fingerprints.
    # Refuse cross-run/cross-build receipts even if their scalar score and
    # target count look plausible. Rust remains the gameplay authority.
    expected_provenance = {
        "original_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "native_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "recovery_request": {"recovery_policy": "decisions", **policy},
    }
    if any(receipt.get(key) != value for key, value in
           expected_provenance.items()):
        raise NativeUnscoredCandidate(
            "Native world receipt provenance does not match current request, "
            "engine or paid recovery policy",
            raw_response=receipt, request_sha256=identity(candidate))
    if (receipt.get("target_count_requested") != targets
            or receipt.get("status") != f"COMPLETED_{targets}_REAL_NATIVE_GSIM_KILLS"
            or receipt.get("native_actor_continuity_receipt_complete") is not True
            or receipt.get("native_recovery_clock_accounted") is not True
            or receipt.get("native_recovery_mode") != "decisions_food_water"
            or receipt.get("native_2d_paid_objective_eligible") is not (targets == 100)
            or type(receipt.get("seconds_per_mob")) not in (int, float)
            or not math.isfinite(receipt["seconds_per_mob"])
            or receipt["seconds_per_mob"] <= 0 or process.returncode):
        raise NativeUnscoredCandidate(
            "Native world chain incomplete/refused: " +
            str(receipt.get("status", "UNKNOWN")),
            raw_response=receipt, request_sha256=identity(candidate))
    return receipt


def run_cold(reference: dict, options: dict, *, binary: Path, out: Path,
             seed: int = 20261109, budget_s: float = 300.0,
             snapshot_s: float = 30.0, clock=time.monotonic,
             chain=paid_chain) -> dict:
    """One 30/300s cold search; snapshot only paid results completed by 30s.

    All screening calls execute actual retained-actor native/world Decisions
    routes. Full 100-mob verification occurs AFTER the cold 300s window; it is
    never stitched from the independent two-target screens.
    """
    if not (0 < snapshot_s < budget_s and math.isfinite(budget_s)):
        raise ValueError("INVALID_COLD_SEARCH_BUDGET")
    if (actor(reference).get("class") != "ClassWarlock"
            or actor(reference).get("race") != "RaceTroll"
            or options.get("class") != "warlock" or options.get("level") != 20):
        raise ValueError("WRONG_NATIVE_WARLOCK_L20_SOURCE")
    out.mkdir(parents=True, exist_ok=True)
    domain = native_candidate_domain(reference, options, seed)
    propose, mutate = candidate_factory(reference, domain)
    start = clock()
    deadline = start + budget_s
    early = None
    paid_rows = []
    screen_attempts = []
    def evaluate(candidate: dict, *, iterations: int, seed: int,
                 rng_mode: str) -> float:
        nonlocal early
        # The kernel provides the shared balanced search protocol. Real-world
        # scoring is an independent native/world 2-target run, not native DPS.
        if rng_mode != "balanced":
            raise ValueError("BALANCED_NATIVE_SCREEN_REQUIRED")
        # Count *all* attempted native calls, including rejected builds. Using
        # len(paid_rows) would reuse an old screen directory after a refusal:
        # the next subprocess could overwrite the failed request or consume
        # its leftover world/summary.json as though it were a fresh receipt.
        index = len(screen_attempts)
        path = out / "screens" / f"{index:05d}"
        attempt = {
            "candidate_sha256": identity(candidate),
            "native_receipt_path": str((path / "world" / "summary.json").relative_to(out)),
            "status": "IN_PROGRESS",
        }
        screen_attempts.append(attempt)
        try:
            receipt = chain(binary, candidate, path, targets=2,
                            timeout=max(0.05, deadline - clock()))
        except Exception as exc:
            # The generic native kernel still judges refusals, timeout and
            # errors. Preserve actual attempted request/receipt locations
            # without making an unscored native result eligible for P4/P5.
            raw = getattr(exc, "raw_response", None)
            attempt.update(
                status=str(getattr(exc, "status", type(exc).__name__)),
                reason=str(exc)[-1200:],
                native_response_status=(raw.get("status") if isinstance(raw, dict)
                                        else None),
                paid_completed_elapsed_s=clock() - start,
            )
            raise
        completed_at = clock() - start
        attempt.update(status="COMPLETED",
                       paid_completed_elapsed_s=completed_at)
        score = -float(receipt["seconds_per_mob"])
        # A native call admitted just before a deadline can finish after it.
        # Only paid evaluations completed by the actual wall-clock boundary
        # are eligible for the frozen P4/P5 winner. Preserve late receipts
        # diagnostically instead of retroactively awarding their scores.
        within_budget = completed_at <= budget_s
        row = {"candidate": copy.deepcopy(candidate),
               "candidate_sha256": identity(candidate),
               "screen_paid_s_per_mob": -score,
               "paid_completed_elapsed_s": completed_at,
               "eligible_at_300s": within_budget,
               "native_receipt": receipt}
        paid_rows.append(row)
        if within_budget and completed_at <= snapshot_s and (
                early is None or score > -early["screen_paid_s_per_mob"]):
            early = row
        return score

    search = search_native(
        profile_id="warlock:20:unrestricted:P4-P6-cold-screen",
        reference=reference, propose=propose, mutate=mutate,
        legal=lambda c: isinstance(c.get("source"), dict)
        and isinstance(c.get("recovery"), dict),
        evaluate=evaluate, seconds=budget_s, iterations=1, seed=seed,
        clock=clock)
    on_time_rows = [row for row in paid_rows if row["eligible_at_300s"]]
    final = max(on_time_rows, key=lambda row: -row["screen_paid_s_per_mob"],
                default=None)
    # Only frozen winners, not an arbitrary list of short screens, earn
    # separate 100/100 native/world receipts. Identical winners reuse only
    # when their exact request and recovery policy also match.
    finalists = {}
    for label, winner in (("30s", early), ("300s", final)):
        if winner is None:
            finalists[label] = {"status": "NO_PAID_SCREEN_WINNER"}
            continue
        key = winner["candidate_sha256"]
        if key not in finalists.get("_by_sha", {}):
            try:
                receipt = chain(binary, winner["candidate"],
                                out / "finalists" / key, targets=100,
                                timeout=1800.0)
                result = {"status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
                          "seconds_per_mob": receipt["seconds_per_mob"],
                          "native_receipt": receipt}
            except NativeUnscoredCandidate as exc:
                # A paid native chain can ACK some targets and then refuse.
                # Preserve its actual killed/recovery/source receipt without
                # treating an incomplete replay as a scored 100-mob finalist.
                raw = exc.raw_response
                result = {
                    "status": "INCOMPLETE_100_NATIVE_FINALIST",
                    "reason": str(exc)[-1200:],
                    "native_response_status": (
                        raw.get("status") if isinstance(raw, dict) else None),
                    "native_receipt": copy.deepcopy(raw) if isinstance(raw, dict)
                    else None,
                }
            except (RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
                result = {"status": "INCOMPLETE_100_NATIVE_FINALIST",
                          "reason": str(exc)[-1200:]}
            # A path is evidence only if the paid subprocess actually wrote it.
            receipt_path = out / "finalists" / key / "world" / "summary.json"
            if receipt_path.is_file():
                result["native_receipt_path"] = str(receipt_path.relative_to(out))
            finalists.setdefault("_by_sha", {})[key] = result
        finalists[label] = {"candidate_sha256": key,
                            "screen_paid_s_per_mob": winner["screen_paid_s_per_mob"],
                            "paid_completed_elapsed_s": winner["paid_completed_elapsed_s"],
                            **finalists["_by_sha"][key]}
    finalists.pop("_by_sha", None)
    # Diagnostic only: these are the real retained-actor, paid 100-mob
    # objectives for the two frozen builds, not a shadow P6 gate verdict.
    p6_comparison = None
    if all(finalists[label].get("status") ==
           "COMPLETED_100_REAL_NATIVE_GSIM_KILLS" for label in ("30s", "300s")):
        t30 = finalists["30s"]["seconds_per_mob"]
        t300 = finalists["300s"]["seconds_per_mob"]
        p6_comparison = {
            "status": "MEASURED_PAID_100_MOB_FINALISTS",
            "t30_seconds_per_mob": t30,
            "t300_seconds_per_mob": t300,
            "t30_over_t300": t30 / t300,
            "within_one_percent": t30 <= 1.01 * t300,
            "gate_recorded": False,
        }
    report = {
        "kind": "warlock_l20_cold_native_world_candidate_search",
        "source_revision": options.get("source_revision"),
        "engine_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_request_sha256": identity(reference),
        "native_options_source": "selected_rust_get_options",
        "native_world_source": "wf_warlock_l20_100mob.py",
        "recovery": "native_decisions_food_water",
        "screen_targets": 2, "finalist_targets": 100,
        "budget_s": budget_s, "snapshot_s": snapshot_s,
        "elapsed_search_s": search["elapsed_s"],
        "cold_300_reached": search["elapsed_s"] >= budget_s,
        "native_paid_screen_count": len(on_time_rows),
        "late_paid_screen_count": len(paid_rows) - len(on_time_rows),
        "native_screen_attempt_count": len(screen_attempts),
        "native_screen_unscored_count": sum(
            attempt["status"] != "COMPLETED" for attempt in screen_attempts),
        "native_screen_unscored_samples": [
            attempt for attempt in screen_attempts
            if attempt["status"] != "COMPLETED"
        ][:8],
        "distinct_paid_candidates": len({
            row["candidate_sha256"] for row in on_time_rows}),
        "native_search": {k: v for k, v in search.items()
                          if k not in ("best_candidate",)},
        "snapshot_30": ({k: v for k, v in early.items() if k != "native_receipt"}
                        if early else None),
        "final_300": ({k: v for k, v in final.items() if k != "native_receipt"}
                      if final else None),
        "finalists": finalists,
        "p6_comparison": p6_comparison,
        "gate_recorded": False, "p4_p5_p6_pass": False,
    }
    (out / "cold_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report



def run_paid_hundred_target_baseline(reference: dict, *, binary: Path, out: Path,
                                     health_threshold: float = 0.5,
                                     mana_threshold: float = 0.1,
                                     timeout: float = 1800.0,
                                     clock=time.monotonic,
                                     chain=paid_chain) -> dict:
    """One frozen, actually paid 100-mob Decisions baseline; no cold search.

    Uses the identical request/engine/recovery-provenance and continuous-world
    receipt path as the cold finalists. This is diagnostic evidence, not P4–P6
    acceptance: it neither performs a 30/300 search nor records a gate.
    """
    if (not math.isfinite(timeout) or timeout <= 0
            or not all(math.isfinite(x) and 0 <= x <= 1
                       for x in (health_threshold, mana_threshold))):
        raise ValueError("INVALID_PAID_BASELINE_ARGUMENT")
    out.mkdir(parents=True, exist_ok=True)
    candidate = {
        "source": copy.deepcopy(reference),
        "recovery": {"health_threshold": health_threshold,
                     "mana_threshold": mana_threshold},
    }
    started = clock()
    receipt = None
    reason = None
    try:
        receipt = chain(binary, candidate, out / "paid", targets=100,
                        timeout=timeout)
        status = "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"
    except NativeUnscoredCandidate as exc:
        status = "NATIVE_HUNDRED_TARGET_BASELINE_UNSCORED"
        reason = str(exc)
        receipt = exc.raw_response
    except subprocess.TimeoutExpired as exc:
        status = "NATIVE_HUNDRED_TARGET_BASELINE_TIMEOUT"
        reason = str(exc)
    except (RuntimeError, ValueError) as exc:
        status = "NATIVE_HUNDRED_TARGET_BASELINE_ERROR"
        reason = str(exc)
    report = {
        "kind": "warlock_l20_frozen_paid_hundred_target_baseline",
        "status": status,
        "elapsed_wall_s": max(0.0, clock() - started),
        "source_request_sha256": identity(reference),
        "engine_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "target_count_requested": 100,
        "recovery": candidate["recovery"],
        "seconds_per_mob": (receipt["seconds_per_mob"]
                            if status == "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"
                            else None),
        "native_receipt": receipt,
        "reason": reason,
        "gate_recorded": False,
        "p4_p5_p6_pass": False,
    }
    (out / "hundred_target_baseline_summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def run_paid_two_target_screen(reference: dict, *, binary: Path, out: Path,
                               health_threshold: float = 0.5,
                               mana_threshold: float = 0.1,
                               timeout: float = 120.0,
                               clock=time.monotonic,
                               chain=paid_chain) -> dict:
    """Measure one actual 2-target paid source run, without starting a cold gate.

    This is a bounded production-path latency diagnostic. It does not rank
    candidates, freeze a 30-second winner or replay 100-target finalists.
    """
    if (not math.isfinite(timeout) or timeout <= 0
            or not all(math.isfinite(x) and 0 <= x <= 1
                       for x in (health_threshold, mana_threshold))):
        raise ValueError("INVALID_PAID_SCREEN_ARGUMENT")
    out.mkdir(parents=True, exist_ok=True)
    candidate = {
        "source": copy.deepcopy(reference),
        "recovery": {"health_threshold": health_threshold,
                     "mana_threshold": mana_threshold},
    }
    started = clock()
    receipt = None
    reason = None
    try:
        receipt = chain(binary, candidate, out / "paid", targets=2,
                        timeout=timeout)
        status = "COMPLETED_2_REAL_NATIVE_GSIM_KILLS"
    except NativeUnscoredCandidate as exc:
        status = "NATIVE_TWO_TARGET_SCREEN_UNSCORED"
        reason = str(exc)
        receipt = exc.raw_response
    except subprocess.TimeoutExpired as exc:
        status = "NATIVE_TWO_TARGET_SCREEN_TIMEOUT"
        reason = str(exc)
    except (RuntimeError, ValueError) as exc:
        status = "NATIVE_TWO_TARGET_SCREEN_ERROR"
        reason = str(exc)
    elapsed = max(0.0, clock() - started)
    report = {
        "kind": "warlock_l20_single_paid_two_target_diagnostic",
        "status": status,
        "elapsed_wall_s": elapsed,
        "completed_by_30s": (status == "COMPLETED_2_REAL_NATIVE_GSIM_KILLS"
                             and elapsed <= 30.0),
        "source_request_sha256": identity(reference),
        "engine_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "screen_targets": 2,
        "recovery": candidate["recovery"],
        "native_receipt": receipt,
        "reason": reason,
        "gate_recorded": False,
        "p4_p5_p6_pass": False,
    }
    (out / "two_target_screen_summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def cold_search_has_paid_finalist_evidence(report: dict) -> bool:
    """CLI completion means observable paid finalists, not a gate PASS.

    A measured P6 ratio outside 1% is still useful evidence of a real
    completed search. Missing 30s/300s snapshots or native 100-target
    receipts are not a successfully completed cold evidence producer.
    """
    finalists = report.get("finalists")
    comparison = report.get("p6_comparison")
    return (
        report.get("cold_300_reached") is True
        and isinstance(report.get("snapshot_30"), dict)
        and isinstance(report.get("final_300"), dict)
        and isinstance(finalists, dict)
        and all(isinstance(finalists.get(label), dict)
                and finalists[label].get("status")
                == "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"
                for label in ("30s", "300s"))
        and isinstance(comparison, dict)
        and comparison.get("status") == "MEASURED_PAID_100_MOB_FINALISTS"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261109)
    parser.add_argument("--budget", type=float, default=300.0)
    parser.add_argument("--snapshot", type=float, default=30.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--two-target-screen", action="store_true",
                      help="Measure one real paid 2-target candidate only; no cold gate")
    mode.add_argument("--hundred-target-baseline", action="store_true",
                      help="Pay one frozen 100-target Decisions build; no cold search")
    parser.add_argument("--baseline-timeout", type=float, default=1800.0)
    parser.add_argument("--screen-timeout", type=float, default=120.0)
    parser.add_argument("--health-threshold", type=float, default=0.5)
    parser.add_argument("--mana-threshold", type=float, default=0.1)
    args = parser.parse_args()
    source = json.loads(args.source.read_text())
    if args.two_target_screen:
        result = run_paid_two_target_screen(
            source, binary=args.binary, out=args.out,
            timeout=args.screen_timeout,
            health_threshold=args.health_threshold,
            mana_threshold=args.mana_threshold)
        print("WARLOCK_NATIVE_TWO_TARGET_PAID_DIAGNOSTIC", json.dumps({
            "status": result["status"],
            "elapsed_wall_s": result["elapsed_wall_s"],
            "completed_by_30s": result["completed_by_30s"],
            "summary": str(args.out / "two_target_screen_summary.json"),
        }), flush=True)
        if result["status"] != "COMPLETED_2_REAL_NATIVE_GSIM_KILLS":
            raise SystemExit(1)
        return
    if args.hundred_target_baseline:
        result = run_paid_hundred_target_baseline(
            source, binary=args.binary, out=args.out,
            timeout=args.baseline_timeout,
            health_threshold=args.health_threshold,
            mana_threshold=args.mana_threshold)
        print("WARLOCK_NATIVE_HUNDRED_TARGET_PAID_BASELINE", json.dumps({
            "status": result["status"],
            "elapsed_wall_s": result["elapsed_wall_s"],
            "seconds_per_mob": result["seconds_per_mob"],
            "summary": str(args.out / "hundred_target_baseline_summary.json"),
        }), flush=True)
        if result["status"] != "COMPLETED_100_REAL_NATIVE_GSIM_KILLS":
            raise SystemExit(1)
        return
    options = query_native_options(args.binary, "warlock", 20)
    result = run_cold(source, options, binary=args.binary, out=args.out,
                      seed=args.seed, budget_s=args.budget,
                      snapshot_s=args.snapshot)
    complete = cold_search_has_paid_finalist_evidence(result)
    print("WARLOCK_NATIVE_COLD_PAID_SEARCH", json.dumps({
        "status": result["native_search"]["status"],
        "evidence_status": ("COMPLETED_PAID_FINALISTS" if complete
                            else "INCOMPLETE_PAID_FINALIST_EVIDENCE"),
        "native_paid_screen_count": result["native_paid_screen_count"],
        "finalists": {k: row["status"] for k, row in result["finalists"].items()},
        "p6_within_one_percent": (
            result["p6_comparison"].get("within_one_percent")
            if isinstance(result.get("p6_comparison"), dict) else None),
        "summary": str(args.out / "cold_summary.json"),
    }), flush=True)
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
