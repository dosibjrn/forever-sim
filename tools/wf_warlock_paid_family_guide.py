#!/usr/bin/env python3
"""Publish an already-paid Warlock build comparison as a bounded guide input.

This is presentation of existing native/gsim 100-target receipts, not a
new simulation, legality check, source model, or M1 gate. The comparison
producer has already validated its raw native attempt and route receipts.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlparse

FAMILIES = ("Affliction", "Demonology", "Destruction")
PAID_STATES = {"MEASURED_CROSS_TREE_100", "MEASURED_CROSS_TREE_TIE_100"}


def _run_link(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").split("/")
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or len(path) != 5 or path[2:4] != ["actions", "runs"]
            or not path[4].isdigit() or parsed.query or parsed.fragment):
        raise ValueError("source run must be a concrete GitHub Actions run URL")
    return url.rstrip("/")


def _paid_measurement(row: dict) -> dict:
    """Require source-linked native-paid identities, not a short DPS screen."""
    elapsed = row.get("elapsed_seconds")
    source_sha = row.get("original_source_sha256")
    executed_sha = row.get("executed_source_sha256")
    family = row.get("dominant_talent_tree_index")
    if (row.get("status") != "MEASURED_NATIVE_100"
            or row.get("targets_killed") != 100
            or row.get("native_world_ack") is not True
            or row.get("paid_native_recovery") is not True
            or type(elapsed) not in (int, float)
            or not math.isfinite(elapsed) or elapsed <= 0
            or type(family) is not int or family not in (0, 1, 2)
            or not isinstance(row.get("native_observation_id"), str)
            or not row["native_observation_id"]
            or not isinstance(row.get("native_summary"), str)
            or not row["native_summary"]
            or not isinstance(source_sha, str) or len(source_sha) != 64
            or not isinstance(executed_sha, str) or len(executed_sha) != 64
            or not isinstance(row.get("talents"), str) or not row["talents"]):
        raise ValueError("measured build lacks complete native-paid receipt provenance")
    return {
        "candidate_index": row["index"],
        "family": FAMILIES[family],
        "family_tree_index": family,
        "talents": row["talents"],
        "elapsed_seconds_for_100_mobs": elapsed,
        "seconds_per_mob": elapsed / 100,
        "native_observation_id": row["native_observation_id"],
        "source_request_sha256": source_sha,
        "executed_source_sha256": executed_sha,
        "native_summary": row["native_summary"],
        "requires_respec_from_paid_predecessor": row["requires_talent_respec_from_paid_source"],
        "final_hp": row.get("final_hp"),
        "final_mana": row.get("final_mana"),
    }


def build(comparison: dict, *, source_run_url: str, artifact_id: int) -> dict:
    """Turn a native-paid comparison into portable, honestly scoped guide data.

    The run/artifact URL is operator-supplied attribution, not a new receipt
    verification. No new native combat is executed or replayed.
    """
    run = _run_link(source_run_url)
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ValueError("original artifact ID is required")
    if comparison.get("kind") != "warlock_native_world_finalist_comparison_v1":
        raise ValueError("not an original native paid world comparison")
    if comparison.get("talent_respec_cost_measured") is not False:
        raise ValueError("cannot infer counterfactual talent respec cost")
    if comparison.get("m1_recording_performed") is not False:
        raise ValueError("route comparison cannot claim formal M1 recording")
    level = comparison.get("level")
    if type(level) is not int or not 10 <= level <= 60:
        raise ValueError("missing measured actor level")
    rows = comparison.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("missing native candidate receipts")
    paid = comparison.get("paid_predecessor")
    binary_sha = comparison.get("native_binary_sha256")
    if (not isinstance(paid, dict) or not paid.get("observation_id")
            or not isinstance(binary_sha, str) or len(binary_sha) != 64):
        raise ValueError("missing paid predecessor or selected Rust binary identity")
    pending = comparison.get("pending_candidate_indexes")
    if not isinstance(pending, list):
        raise ValueError("missing native paid trial completion state")

    measured = [_paid_measurement(row) for row in rows
                if row.get("status") == "MEASURED_NATIVE_100"]
    measured.sort(key=lambda row: (row["elapsed_seconds_for_100_mobs"],
                                   row["candidate_index"]))
    complete = (comparison.get("status") in PAID_STATES
                and comparison.get("distinct_build_families_compared") is True
                and not pending and len(measured) >= 2
                and len({row["family_tree_index"] for row in measured}) >= 2)
    winner = comparison.get("world_winner")
    if complete:
        fastest = measured[0]["elapsed_seconds_for_100_mobs"]
        tied = [row for row in measured
                if row["elapsed_seconds_for_100_mobs"] == fastest]
        if comparison["status"] == "MEASURED_CROSS_TREE_TIE_100":
            if winner is not None or len(tied) < 2:
                raise ValueError("tie claim differs from paid native measurements")
        elif (len(tied) != 1 or not isinstance(winner, dict)
              or winner.get("candidate_index") != tied[0]["candidate_index"]
              or winner.get("elapsed_seconds") != fastest):
            raise ValueError("winner claim differs from paid native measurements")

    return {
        "kind": "warlock_paid_family_guide_input_v1",
        "status": ("MEASURED_BOUNDED_FAMILY_COMPARISON" if complete
                   else "PROVISIONAL_NO_COMPARABLE_FAMILY_GUIDE"),
        "actor_level": level,
        "scope": "one hostile 100-mob native/gsim scenario; counterfactual builds",
        "source_run_url": run,
        "original_artifact_id": artifact_id,
        "original_artifact_url": run + "/artifacts/" + str(artifact_id),
        "selected_native_binary_sha256": binary_sha,
        "paid_predecessor_observation_id": paid["observation_id"],
        "measurements": measured if complete else [],
        "bounded_fastest_family": (tied[0]["family"] if complete and len(tied) == 1
                                   else None),
        "tied_fastest_families": ([row["family"] for row in tied]
                                 if complete and len(tied) > 1 else []),
        "other_or_unpaid_candidate_indexes": sorted(
            {row["index"] for row in rows
             if row.get("status") != "MEASURED_NATIVE_100"} | set(pending)),
        "actual_respec_execution_measured": False,
        "talent_respec_cost_measured": False,
        "continuous_level_route_measured": False,
        "full_route_optimum_measured": False,
        "stat_weights_measured": False,
        "m1_recording_performed": False,
    }


def publish(*, comparison: Path, source_run_url: str, artifact_id: int,
            out: Path) -> dict:
    result = build(json.loads(comparison.read_text()),
                   source_run_url=source_run_url, artifact_id=artifact_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", required=True, type=Path)
    parser.add_argument("--source-run-url", required=True)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    result = publish(**vars(parser.parse_args()))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
