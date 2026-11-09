#!/usr/bin/env python3
"""One cold Warlock L20 native/gsim search with paid recovery and 100-mob finalists.

This is a producer for the existing P4-P6 objective, not an alternate gate.
Rust supplies source options and judges every submitted build. The existing
native/world runner supplies the measured eight-target screening objective and
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
    # Candidate spell IDs come only from get_options, and Rust still decides
    # whether a spell is executable at this level/talent/build.
    for spell in options["spells"]:
        spell_id = spell.get("spell_id") if isinstance(spell, dict) else None
        if type(spell_id) is int and spell_id > 0:
            proposal = [{"action": {"castSpell": {
                "spellId": {"spellId": spell_id}}}}, *copy.deepcopy(apl)]
            apl_variants.append(proposal)
    unique_apl = list({json.dumps(x, sort_keys=True): x
                       for x in apl_variants}.values())
    return {"gear": gear, "talents": talents or [player.get("talentsString", "0-0-0")],
            "apl": unique_apl,
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
        # A cold proposal changes multiple axes; subsequent mutation explores
        # both local and joint moves using the generic search scheduler.
        selected = rng.sample(axes, rng.randint(2, 4) if cold else rng.randint(1, 3))
        player = actor(value["source"])
        for axis in selected:
            if axis == "gear" and domain["gear"]:
                position = rng.choice(list(domain["gear"]))
                player["equipment"]["items"][position] = copy.deepcopy(
                    rng.choice(domain["gear"][position]))
            elif axis == "talents":
                player["talentsString"] = rng.choice(domain["talents"])
            elif axis == "apl":
                player["rotation"]["priorityList"] = copy.deepcopy(
                    rng.choice(domain["apl"]))
            elif axis == "recovery":
                hp, mana = rng.choice(domain["recovery"])
                value["recovery"] = {"health_threshold": hp, "mana_threshold": mana}
        return value

    def propose(rng):
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
    process = subprocess.run(command, capture_output=True, text=True,
                             timeout=timeout, check=False, cwd=ROOT)
    summary_path = out / "world" / "summary.json"
    if not summary_path.exists():
        raise RuntimeError("Native paid runner did not emit a structured receipt: " +
                           (process.stderr or process.stdout)[-800:])
    summary = json.loads(summary_path.read_text())
    rows = summary.get("results")
    if (not isinstance(rows, list) or len(rows) != 1
            or not isinstance(rows[0], dict)):
        raise RuntimeError("Native paid runner returned an invalid summary")
    receipt = rows[0]
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
    never stitched from the independent eight-target screens.
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
    def evaluate(candidate: dict, *, iterations: int, seed: int,
                 rng_mode: str) -> float:
        nonlocal early
        # The kernel provides the shared balanced search protocol. Real-world
        # scoring is an independent native/world 8-target run, not native DPS.
        if rng_mode != "balanced":
            raise ValueError("BALANCED_NATIVE_SCREEN_REQUIRED")
        index = len(paid_rows)
        path = out / "screens" / f"{index:05d}"
        receipt = chain(binary, candidate, path, targets=8,
                        timeout=max(0.05, deadline - clock()))
        completed_at = clock() - start
        score = -float(receipt["seconds_per_mob"])
        row = {"candidate": copy.deepcopy(candidate),
               "candidate_sha256": identity(candidate),
               "screen_paid_s_per_mob": -score,
               "paid_completed_elapsed_s": completed_at,
               "native_receipt": receipt}
        paid_rows.append(row)
        if completed_at <= snapshot_s and (
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
    final = max(paid_rows, key=lambda row: -row["screen_paid_s_per_mob"],
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
            except (NativeUnscoredCandidate, RuntimeError,
                    subprocess.TimeoutExpired, ValueError) as exc:
                result = {"status": "INCOMPLETE_100_NATIVE_FINALIST",
                          "reason": str(exc)[-1200:]}
            finalists.setdefault("_by_sha", {})[key] = result
        finalists[label] = {"candidate_sha256": key,
                            "screen_paid_s_per_mob": winner["screen_paid_s_per_mob"],
                            "paid_completed_elapsed_s": winner["paid_completed_elapsed_s"],
                            **finalists["_by_sha"][key]}
    finalists.pop("_by_sha", None)
    report = {
        "kind": "warlock_l20_cold_native_world_candidate_search",
        "source_revision": options.get("source_revision"),
        "engine_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_request_sha256": identity(reference),
        "native_options_source": "selected_rust_get_options",
        "native_world_source": "wf_warlock_l20_100mob.py",
        "recovery": "native_decisions_food_water",
        "screen_targets": 8, "finalist_targets": 100,
        "budget_s": budget_s, "snapshot_s": snapshot_s,
        "elapsed_search_s": search["elapsed_s"],
        "cold_300_reached": search["elapsed_s"] >= budget_s,
        "native_paid_screen_count": len(paid_rows),
        "distinct_paid_candidates": len({
            row["candidate_sha256"] for row in paid_rows}),
        "native_search": {k: v for k, v in search.items()
                          if k not in ("best_candidate",)},
        "snapshot_30": ({k: v for k, v in early.items() if k != "native_receipt"}
                        if early else None),
        "final_300": ({k: v for k, v in final.items() if k != "native_receipt"}
                      if final else None),
        "finalists": finalists,
        "gate_recorded": False, "p4_p5_p6_pass": False,
    }
    (out / "cold_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261109)
    parser.add_argument("--budget", type=float, default=300.0)
    parser.add_argument("--snapshot", type=float, default=30.0)
    args = parser.parse_args()
    options = query_native_options(args.binary, "warlock", 20)
    source = json.loads(args.source.read_text())
    result = run_cold(source, options, binary=args.binary, out=args.out,
                      seed=args.seed, budget_s=args.budget,
                      snapshot_s=args.snapshot)
    print("WARLOCK_NATIVE_COLD_PAID_SEARCH", json.dumps({
        "status": result["native_search"]["status"],
        "native_paid_screen_count": result["native_paid_screen_count"],
        "finalists": {k: row["status"] for k, row in result["finalists"].items()},
        "summary": str(args.out / "cold_summary.json"),
    }), flush=True)


if __name__ == "__main__":
    main()
