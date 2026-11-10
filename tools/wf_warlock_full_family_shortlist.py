#!/usr/bin/env python3
"""Construct *different complete* Warlock talent families using native prepare.

This is a bounded proposal/search adapter, not a Warcraft talent rules engine.
MythicSim supplies the option indices/rank caps and decides every candidate's
legality via prepare. A reset of the paid source talents is counterfactual:
neither respec authorization/cost nor continuous route ancestry is claimed.
The existing hostile-world comparator owns any later measured outcome.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import wf_warlock_next_level_source as native


def _request(original: dict, level: int, allocation: str) -> dict:
    candidate = copy.deepcopy(original)
    player = candidate["raid"]["parties"][0]["players"][0]
    player["level"] = level
    player["talentsString"] = allocation
    candidate["encounter"]["targets"][0]["level"] = level
    return candidate


def _digits(parts: list[list[str]]) -> str:
    return "-".join("".join(tree) for tree in parts)


def _prepare(binary: Path, request: Path, prepared: Path, level: int) -> tuple[bool, str]:
    prepared.unlink(missing_ok=True)  # No stale source actor after a successful exit.
    result = subprocess.run(
        [str(binary.resolve()), "prepare", "--request", str(request.resolve()),
         "--actor-level", str(level), "--outfile", str(prepared.resolve())],
        capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        return False, (result.stderr or result.stdout or "native prepare refused")[-1200:]
    try:
        player = json.loads(prepared.read_text())["player"]
    except (ValueError, KeyError, OSError):
        return False, "NATIVE_PREPARED_ACTOR_MISSING"
    if player.get("level") != level or player.get("class") != "ClassWarlock":
        return False, "NATIVE_PREPARED_ACTOR_LEVEL_OR_CLASS_MISMATCH"
    return True, ""


def _native_screen(binary: Path, candidate: dict, out: Path,
                   number: int, level: int) -> tuple[dict, bool]:
    attempts = out / "candidate_attempts"
    request = attempts / f"candidate_{number:02d}.json"
    screen_request = attempts / f"candidate_{number:02d}.screen.json"
    prepared = attempts / f"candidate_{number:02d}.prepared.json"
    paid_file = attempts / f"candidate_{number:02d}.paid.json"
    request.write_text(json.dumps(candidate, indent=2) + "\n")
    screen = copy.deepcopy(candidate)
    screen.setdefault("simOptions", {}).update({
        "iterations": 8, "randomSeed": "4242", "debugFirstIteration": False,
    })
    screen["encounter"]["duration"] = 30
    screen_request.write_text(json.dumps(screen, indent=2) + "\n")
    paid_file.unlink(missing_ok=True)
    accepted, reason = _prepare(binary, screen_request, prepared, level)
    row = {
        "source_request": str(request.relative_to(out)),
        "source_request_sha256": native.sha256(request),
        "native_screen_request_sha256": native.sha256(screen_request),
        "screen_status": "NATIVE_SCREEN_REFUSED",
        "screen_dps_30s": None,
    }
    if not accepted:
        row["screen_refusal"] = reason
        return row, False
    row["native_prepared_sha256"] = native.sha256(prepared)
    try:
        result = subprocess.run(
            [str(binary.resolve()), "sim", "--infile", str(prepared.resolve()),
             "--rng-mode", "balanced", "--outfile", str(paid_file.resolve())],
            capture_output=True, text=True, timeout=120, check=False)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "native sim refused")[-1200:])
        dps = json.loads(paid_file.read_text())["result"]["raidMetrics"]["parties"][0][
            "players"][0]["dps"]["avg"]
        if type(dps) not in (float, int) or not math.isfinite(dps):
            raise ValueError("native screen returned nonfinite DPS")
        row.update(screen_status="NATIVE_SCREEN_PAID",
                   screen_dps_30s=float(dps),
                   native_paid_receipt_sha256=native.sha256(paid_file))
    except (OSError, ValueError, KeyError, RuntimeError,
            subprocess.TimeoutExpired) as exc:
        row["screen_refusal"] = str(exc)[-1200:]
    return row, True


def build(*, binary: Path, source: Path, predecessor_route: Path, out: Path,
          from_level: int = 46, to_level: int = 47,
          predecessor_binary_sha256: str | None = None,
          max_native_probes_per_family: int = 240) -> dict:
    """Fill each native talent tree to the level's full budget using Rust ACKs.

    Each point proposal is based only on Rust-listed indices/caps. A rank is
    retained *only* after an actual fresh Rust prepare accepts the full actor.
    No Python tier/prerequisite legality or simulated combat is used.
    """
    if not 10 <= from_level < 60 or to_level != from_level + 1:
        raise ValueError("full-family shortlist requires adjacent Warlock levels 10..60")
    if not 1 <= max_native_probes_per_family <= 1000:
        raise ValueError("native probe budget must be 1..1000 per family")
    if not binary.is_file() or not source.is_file() or not predecessor_route.is_file():
        raise ValueError("exact native binary, source and paid predecessor required")
    predecessor = native.verified_paid_predecessor(
        route=predecessor_route, source=source, binary=binary,
        from_level=from_level,
        predecessor_binary_sha256=predecessor_binary_sha256)
    original = json.loads(source.read_text())
    actor = original["raid"]["parties"][0]["players"][0]
    if (actor.get("class") != "ClassWarlock" or
            type(actor.get("level")) is not int or actor["level"] != from_level or
            original["encounter"]["targets"][0].get("level") != from_level):
        raise ValueError("paid source is not the requested adjacent Warlock actor")
    out.mkdir(parents=True, exist_ok=True)
    # No output from a prior attempt may become this invocation's candidate.
    for filename in ("native_paid_shortlist.json", "proposal.json"):
        (out / filename).unlink(missing_ok=True)
    attempts = out / "candidate_attempts"
    attempts.mkdir(exist_ok=True)
    options_call = subprocess.run(
        [str(binary.resolve()), "options", "--class", "warlock",
         "--level", str(to_level)],
        capture_output=True, text=True, timeout=60, check=False)
    if options_call.returncode:
        raise RuntimeError("NATIVE_OPTIONS_REFUSAL: " +
                           (options_call.stderr or options_call.stdout)[-1200:])
    options = json.loads(options_call.stdout)
    talents = options.get("talents", {})
    trees = talents.get("trees")
    budget = talents.get("points_available")
    if (options.get("level") != to_level or talents.get("status") != "ok"
            or type(budget) is not int or budget <= 0
            or not isinstance(trees, list) or len(trees) != 3):
        raise ValueError("native options did not provide a full talent point budget")
    native_trees = []
    for tree in trees:
        rows = tree.get("talents")
        if not isinstance(rows, list) or not rows:
            raise ValueError("native talent tree has no candidate ranks")
        indices = set()
        for row in rows:
            index, cap = row.get("index"), row.get("max_rank")
            if (type(index) is not int or index < 0 or type(cap) is not int
                    or not 1 <= cap <= 9 or index in indices):
                raise ValueError("malformed native talent rank option")
            indices.add(index)
        native_trees.append(sorted(rows, key=lambda row: row["index"]))
    zero = [["0"] * (max(row["index"] for row in tree) + 1)
            for tree in native_trees]
    shortlist = []
    refusals = []
    progress = []
    for family in range(3):
        parts = copy.deepcopy(zero)
        native_calls = 0
        family_refusals = []
        # A complete alternative is a *counterfactual respec*, not an
        # adjacent +1 point from the selected, paid L46 actor.
        while sum(int(rank) for tree in parts for rank in tree) < budget:
            advanced = False
            for option in native_trees[family]:
                index, cap = option["index"], option["max_rank"]
                if int(parts[family][index]) >= cap:
                    continue
                if native_calls >= max_native_probes_per_family:
                    break
                trial = copy.deepcopy(parts)
                trial[family][index] = str(int(trial[family][index]) + 1)
                candidate = _request(original, to_level, _digits(trial))
                native_calls += 1
                request = attempts / f"family_{family}_probe_{native_calls:03d}.json"
                prepared = attempts / f"family_{family}_probe_{native_calls:03d}.prepared.json"
                request.write_text(json.dumps(candidate, indent=2) + "\n")
                accepted, reason = _prepare(binary, request, prepared, to_level)
                if accepted:
                    parts = trial
                    advanced = True
                    break
                family_refusals.append({
                    "tree_index": family, "field_name": option.get("field_name"),
                    "proposed_rank": int(trial[family][index]),
                    "source_request_sha256": native.sha256(request),
                    "reason": reason,
                })
            if not advanced:
                break
        points = [sum(int(d) for d in tree) for tree in parts]
        complete = sum(points) == budget and points[family] > 0
        progress.append({
            "tree_index": family, "accepted_points_by_tree": points,
            "native_budget": budget, "native_prepare_probes": native_calls,
            "full_native_prepared": complete,
        })
        refusals.extend(family_refusals)
        if not complete:
            continue
        candidate = _request(original, to_level, _digits(parts))
        number = len(shortlist) + 1
        screened, prepared = _native_screen(binary, candidate, out, number, to_level)
        if not prepared:
            refusals.append({
                "tree_index": family, "stage": "final_screen_prepare",
                "reason": screened.get("screen_refusal"),
            })
            continue
        screened.update(
            tree_index=family, field_name=f"full_native_family_{family}",
            candidate_talents=_digits(parts),
            talent_points_by_tree=points,
            requires_counterfactual_respec=True)
        shortlist.append(screened)
    # Only truly different *complete* dominant families earn an expensive
    # hostile 100/100 comparison. The previous three Destro +1 receipts are
    # not diverse families and must not be repaid.
    families = {row["tree_index"] for row in shortlist}
    status = ("NATIVE_SCREENED_NOT_WORLD_PAID" if len(families) >= 2 else
              "NATIVE_SHORTLIST_NO_DISTINCT_FAMILIES")
    receipt = {
        "kind": "adjacent_native_warlock_candidate",
        "status": status,
        "allocation_mode": "full_native_prepared_counterfactual_families",
        "from_level": from_level, "to_level": to_level,
        "original_source_sha256": native.sha256(source),
        "native_binary_sha256": native.sha256(binary),
        "native_options_source_revision": options.get("source_revision"),
        "paid_predecessor": predecessor,
        "source_talents": actor["talentsString"],
        "talent_respec_cost_measured": False,
        "native_options_points_available": budget,
        "candidate_families_prepared": sorted(families),
        "family_progress": progress,
        "candidates": shortlist, "native_refusals": refusals,
        "world_winner": None, "m1_recording_performed": False,
    }
    serialized = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    (out / "native_paid_shortlist.json").write_text(serialized)
    (out / "proposal.json").write_text(serialized)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--predecessor-route", type=Path, required=True)
    parser.add_argument("--predecessor-binary-sha256")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--from-level", type=int, default=46)
    parser.add_argument("--to-level", type=int, default=47)
    parser.add_argument("--max-native-probes-per-family", type=int, default=240)
    result = build(**vars(parser.parse_args()))
    print(json.dumps(result, indent=2))
    if result["status"] != "NATIVE_SCREENED_NOT_WORLD_PAID":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
