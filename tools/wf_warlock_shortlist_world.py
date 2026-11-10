#!/usr/bin/env python3
"""Pay and compare source-native Warlock shortlist builds in real hostile 100-mob worlds.

The adjacent-level source proposer owns the immutable shortlist. The existing
Warlock guide executes each candidate using the same retained-actor Rust/gsim
Decisions world as the adjacent paid route. Only paid, complete, comparable
native receipts earn an elapsed-time rank. No DPS proxy, rules model, M1 gate,
or re-execution of previously paid candidates is introduced here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import wf_warlock_next_level_source as native_source
from tools import wf_warlock_route_guide as guide


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]


def _candidate_sources(shortlist: dict, directory: Path, original: dict,
                       limit: int) -> list[tuple[dict, Path]]:
    """Check the actual unmodified native-generated world request for each row."""
    results = []
    seen = set()
    level = shortlist["to_level"]
    # Validate all source-receipt candidates before choosing the bounded paid
    # finalists, even when a candidate falls beyond the paid trial budget.
    for row in shortlist["candidates"]:
        label = row.get("source_request")
        if (not isinstance(label, str)
                or not label.startswith("candidate_attempts/candidate_")
                or not label.endswith(".json")
                or "/" in label[len("candidate_attempts/"):]
                or "\\" in label):
            raise ValueError("unsafe shortlist candidate request path")
        source = directory / label
        if not source.is_file() or native_source.sha256(source) != row.get("source_request_sha256"):
            raise ValueError("shortlist candidate bytes do not match native receipt")
        if row.get("screen_status") not in ("NATIVE_SCREEN_PAID", "NATIVE_SCREEN_REFUSED"):
            raise ValueError("shortlist row was not successfully native-prepared")
        candidate = _json(source)
        expected = copy.deepcopy(original)
        expected["raid"]["parties"][0]["players"][0]["level"] = level
        expected["raid"]["parties"][0]["players"][0]["talentsString"] = row["candidate_talents"]
        expected["encounter"]["targets"][0]["level"] = level
        if candidate != expected:
            raise ValueError("candidate changed source actor/scenario beyond native talent proposal")
        if row["source_request_sha256"] in seen:
            raise ValueError("duplicate candidate source in paid comparison")
        if row.get("tree_index") not in (0, 1, 2):
            raise ValueError("missing source-native talent tree identity")
        seen.add(row["source_request_sha256"])
        results.append((row, source))
    # A source-native shortlist may have several prepared proposals from the
    # same talent tree before a different tree's first successful prepare.
    # Preserve Rust's order within each tree, but pay a bounded spread across
    # source-labeled trees rather than accidentally comparing one tree thrice.
    by_tree = {tree: [] for tree in (0, 1, 2)}
    for candidate in results:
        by_tree[candidate[0]["tree_index"]].append(candidate)
    balanced = []
    for depth in range(max(map(len, by_tree.values()), default=0)):
        for tree in (0, 1, 2):
            if depth < len(by_tree[tree]):
                balanced.append(by_tree[tree][depth])
                if len(balanced) == limit:
                    return balanced
    return balanced


def _talent_points_by_tree(talents: str) -> list[int]:
    """Describe invested rank digits, without judging native talent legality."""
    if (not isinstance(talents, str)
            or len(talents.split("-")) != 3
            or any(not part or not part.isascii() or not part.isdigit()
                   for part in talents.split("-"))):
        raise ValueError("native source talent allocation cannot be described")
    return [sum(int(rank) for rank in tree) for tree in talents.split("-")]


def _dominant_talent_tree(points: list[int]) -> int | None:
    """Tree with strictly the most invested points; ties have no unique family."""
    largest = max(points)
    return points.index(largest) if largest > 0 and points.count(largest) == 1 else None


def _paid_row(*, route: Path, summary: Path, source: Path, binary_sha: str,
              level: int, trial: str, recovery: dict) -> tuple[dict, dict | None]:
    """Re-read native evidence; a successful publisher exit is never a score."""
    payload = _json(summary)
    if (payload.get("kind") != "real_100_target_source_native_world_attempts"
            or payload.get("target_count_requested") != 100
            or payload.get("actor_level") != level
            or payload.get("original_source_sha256") != native_source.sha256(source)
            or payload.get("native_binary_sha256") != binary_sha
            or payload.get("native_recovery_requested") != recovery
            or payload.get("hostile_player_tank_requested") is not True):
        raise ValueError("cached native world does not match compared source/scenario")
    attempts = payload.get("results")
    if not isinstance(attempts, list) or len(attempts) != 1:
        raise ValueError("expected one unmodified best_apl native world attempt")
    attempt = attempts[0]
    if attempt.get("variant") != "best_apl":
        raise ValueError("unexpected native candidate variant")
    # The summary header is not sufficient to authenticate a cached paid
    # finalist: the individual native attempt must belong to this exact
    # candidate and hostile recovery protocol, including native refusals.
    if (attempt.get("original_source_sha256") != native_source.sha256(source)
            or attempt.get("native_binary_sha256") != binary_sha
            or attempt.get("actor_level") != level
            or attempt.get("hostile_player_tank_requested") is not True
            or attempt.get("recovery_request") != recovery):
        raise ValueError("cached native attempt differs from candidate or hostile recovery")
    result = {"status": attempt.get("status"), "targets_killed": attempt.get("killed"),
              "error": attempt.get("error"), "native_summary": str(summary)}
    if attempt.get("status") != "COMPLETED_100_REAL_NATIVE_GSIM_KILLS":
        return result, None
    if (attempt.get("target_count_requested") != 100
            or attempt.get("native_actor_continuity_receipt_complete") is not True
            or attempt.get("native_2d_paid_objective_eligible") is not True
            or attempt.get("native_recovery_clock_accounted") is not True
            or attempt.get("world_target_hp_matches_request") is not True
            or attempt.get("paid_recovery") is not True
            or attempt.get("native_enemy_attack_prepared") is not True):
        raise ValueError("world winner cannot use incomplete actor/hostile recovery receipt")
    executed_source = summary.parent / "best_apl" / "source_request.json"
    if (not executed_source.is_file()
            or native_source.sha256(executed_source) != attempt.get("source_request_sha256")):
        raise ValueError("executed hostile request is missing or changed")
    report = _json(route)
    matches = [
        row for row in report.get("observations", [])
        if row.get("trial") == trial
        and row.get("level") == level
        and row.get("source_request_sha256") == native_source.sha256(executed_source)
        and row.get("engine_binary_sha256") == binary_sha
        and row.get("status") == "measured_native_chain"
        and row.get("targets_requested") == row.get("targets_killed") == 100
        and row.get("paid_native_recovery") is True
        and row.get("native_world_ack") is True
        and row.get("receipt_path") == str(summary.resolve())
    ]
    if len(matches) != 1:
        raise ValueError("no unique matching actual published 100/100 native observation")
    observation = matches[0]
    seconds = observation.get("elapsed_seconds_for_observed_chain")
    native_seconds = attempt.get("seconds_per_mob")
    if (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0
            or type(native_seconds) not in (int, float) or not math.isfinite(native_seconds)
            or not math.isclose(seconds, native_seconds * 100, rel_tol=0, abs_tol=0.001)):
        raise ValueError("native paid elapsed differs from published world clock")
    # Source scenario identity, not Warcraft rules; the candidate talent is
    # intentionally different while the enemy and charged recovery must match.
    signature = {
        "mob_hp": attempt.get("mob_hp_native_scenario"),
        "damage": attempt.get("scenario_min_base_damage"),
        "swing_speed": attempt.get("scenario_swing_speed"),
        "target_name": attempt.get("scenario_target_name"),
        "recovery": attempt.get("recovery_request"),
        "hostile": payload["hostile_player_tank_requested"],
    }
    result.update(status="MEASURED_NATIVE_100", targets_killed=100,
                  elapsed_seconds=seconds, final_hp=attempt.get("final_hp"),
                  final_mana=attempt.get("final_mana"),
                  native_world_ack=True, paid_native_recovery=True,
                  native_observation_id=observation["id"],
                  executed_source_sha256=native_source.sha256(executed_source),
                  native_actor=attempt.get("native_actor"))
    return result, signature


def run(*, binary: Path, source: Path, predecessor_route: Path, shortlist: Path,
        out: Path, max_new_trials: int = 3, max_candidates: int = 6,
        health_threshold: float = 0.7, mana_threshold: float = 0.25) -> dict:
    if max_new_trials < 0 or not 1 <= max_candidates <= 30:
        raise ValueError("invalid bounded paid finalist budget")
    if not 0 < health_threshold <= 1 or not 0 < mana_threshold <= 1:
        raise ValueError("Decisions recovery thresholds must be in (0,1]")
    if not all(path.is_file() for path in (binary, source, predecessor_route, shortlist)):
        raise ValueError("exact binary, native shortlist, source and predecessor receipt required")
    proposal = _json(shortlist)
    binary_sha = native_source.sha256(binary)
    source_sha = native_source.sha256(source)
    if (proposal.get("kind") != "adjacent_native_warlock_candidate"
            or proposal.get("status") != "NATIVE_SCREENED_NOT_WORLD_PAID"
            or proposal.get("native_binary_sha256") != binary_sha
            or proposal.get("original_source_sha256") != source_sha
            or proposal.get("to_level") != proposal.get("from_level", -100) + 1
            or not isinstance(proposal.get("candidates"), list)):
        raise ValueError("not a matching source-native prepared shortlist")
    original = _json(source)
    source_talent_points = _talent_points_by_tree(
        original["raid"]["parties"][0]["players"][0]["talentsString"])
    level = proposal["to_level"]
    paid = proposal.get("paid_predecessor")
    if not isinstance(paid, dict) or paid != native_source.verified_paid_predecessor(
            route=predecessor_route, source=source, binary=binary,
            from_level=level - 1,
            predecessor_binary_sha256=paid.get("engine_binary_sha256")):
        raise ValueError("shortlist has no identical genuine native-paid predecessor")
    candidates = _candidate_sources(proposal, shortlist.parent, original, max_candidates)
    if not candidates:
        raise ValueError("no native-prepared build to pay")
    recovery = {"recovery_policy": "decisions",
                "health_threshold": health_threshold, "mana_threshold": mana_threshold}
    identity = {"shortlist_sha256": native_source.sha256(shortlist),
                "source_sha256": source_sha, "binary_sha256": binary_sha,
                "paid_predecessor": paid,
                "level": level, "recovery": recovery,
                "candidate_shas": [row["source_request_sha256"] for row, _ in candidates]}
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "comparison_identity.json"
    if manifest.is_file() and _json(manifest) != identity:
        raise ValueError("comparison directory belongs to a different native paid scenario")
    manifest.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    spent = 0
    rows = []
    signatures = []
    pending = []
    for index, (candidate, candidate_source) in enumerate(candidates, start=1):
        folder = out / f"candidate_{index:02d}_{candidate['source_request_sha256'][:12]}"
        summary = folder / f"native_l{level}" / "summary.json"
        route = folder / "route.json"
        trial = f"source-cross-tree-L{level}-{_digest(identity)}-{index:02d}"
        candidate_points = _talent_points_by_tree(candidate["candidate_talents"])
        row = {"index": index, "tree_index": candidate["tree_index"],
               "talent": candidate["field_name"], "talents": candidate["candidate_talents"],
               "talent_points_by_tree": candidate_points,
               "dominant_talent_tree_index": _dominant_talent_tree(candidate_points),
               "original_source_sha256": candidate["source_request_sha256"],
               "native_screen_dps_30s": candidate.get("screen_dps_30s")}
        if summary.is_file() and not route.is_file():
            # Recover the publisher from paid native bytes, never pay again.
            guide.main(["--native-summary", str(summary),
                        "--baseline-observations", str(predecessor_route),
                        "--trial", trial, "--out", str(folder)])
        if not summary.is_file():
            if spent >= max_new_trials:
                row["status"] = "PENDING_UNPAID"
                pending.append(index)
                rows.append(row)
                continue
            spent += 1
            guide.main(["--execute-native", "--actor-level", str(level),
                        "--binary", str(binary), "--source", str(candidate_source),
                        "--health-threshold", str(health_threshold),
                        "--mana-threshold", str(mana_threshold),
                        "--baseline-observations", str(predecessor_route),
                        "--trial", trial, "--out", str(folder)])
        if not route.is_file() or not summary.is_file():
            raise ValueError("native paid attempt did not publish its raw summary and route")
        receipt, signature = _paid_row(
            route=route, summary=summary, source=candidate_source,
            binary_sha=binary_sha, level=level, trial=trial, recovery=recovery)
        row.update(receipt)
        rows.append(row)
        if signature is not None:
            signatures.append(signature)
    comparable = (not signatures or
                  all(s == signatures[0] for s in signatures))
    ranked = sorted((row for row in rows if row.get("status") == "MEASURED_NATIVE_100"),
                    key=lambda row: (row["elapsed_seconds"], row["index"])) if comparable else []
    trees = {row["tree_index"] for row in ranked}
    # The tree receiving a NEW rank is not the candidate's build family.
    # E.g. one Affliction point atop 30+ Destruction points is still a
    # Destruction-heavy build. Count the source-issued rank digits only for
    # transparent presentation, never as a legality or power model.
    families = {row["dominant_talent_tree_index"] for row in ranked}
    actual_cross_family = len(families) >= 2 and None not in families
    # A tie is genuinely measured, but selecting the first row as a "winner"
    # fabricates an Affliction advantage when the native world elapsed times
    # are equal. Do not introduce a Python gameplay tie-breaker.
    comparison_complete = not pending and len(ranked) >= 2 and len(trees) >= 2
    tied_best = ([row for row in ranked
                  if row["elapsed_seconds"] == ranked[0]["elapsed_seconds"]]
                 if comparison_complete else [])
    winner = (ranked[0] if comparison_complete and len(tied_best) == 1
              else None)
    result = {
        "kind": "warlock_native_world_finalist_comparison_v1",
        "status": ("INCOMPARABLE_NATIVE_SCENARIOS" if not comparable
                   else ("MEASURED_CROSS_TREE_TIE_100" if actual_cross_family
                         else "MEASURED_SAME_BUILD_FAMILY_TIE_100")
                   if len(tied_best) > 1
                   else ("MEASURED_CROSS_TREE_100" if actual_cross_family
                         else "MEASURED_SAME_BUILD_FAMILY_100")
                   if winner
                   else "PARTIAL_WORLD_PAID"),
        "from_level": level - 1, "level": level,
        "source_talent_points_by_tree": source_talent_points,
        "source_dominant_talent_tree_index": _dominant_talent_tree(source_talent_points),
        "measured_dominant_talent_tree_indexes": sorted(
            family for family in families if family is not None),
        "distinct_build_families_compared": actual_cross_family,
        "tree_index_meaning": "new_rank_allocated_to_tree_not_build_family",
        "paid_predecessor": paid, "native_binary_sha256": binary_sha,
        "recovery": recovery, "new_native_100_trials": spent,
        "reused_native_100_trials": sum(
            row.get("status") != "PENDING_UNPAID" for row in rows) - spent,
        "pending_candidate_indexes": pending,
        "tied_best_candidate_indexes": ([row["index"] for row in tied_best]
                                        if len(tied_best) > 1 else []),
        "candidates": rows,
        "world_winner": ({"candidate_index": winner["index"],
                          "tree_index": winner["tree_index"],
                          "talents": winner["talents"],
                          "elapsed_seconds": winner["elapsed_seconds"],
                          "native_observation_id": winner["native_observation_id"]}
                         if winner else None),
        "world_winner_is_full_level_route": False,
        "stat_weights_measured": False,
        "m1_recording_performed": False,
    }
    (out / "comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--predecessor-route", type=Path, required=True)
    parser.add_argument("--shortlist", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-new-trials", type=int, default=3)
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--health-threshold", type=float, default=0.7)
    parser.add_argument("--mana-threshold", type=float, default=0.25)
    result = run(**vars(parser.parse_args(argv)))
    print(json.dumps(result, indent=2))
    return 2 if result["status"] == "INCOMPARABLE_NATIVE_SCENARIOS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
