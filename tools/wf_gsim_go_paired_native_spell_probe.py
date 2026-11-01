#!/usr/bin/env python3
"""Paired *real native Go* range-perturbation diagnostic; NOT a P7 certification.

Both runs use identical pinned Go request bytes and nonzero random seed, with
different genuine gsim target positions; native spells are observed from the
same persistent Go engine per run, not generated from a dummy DPS proxy.
The new native result→gsim world-effect ACK is required on both scenarios;
full Druid P7/source parity and exact in-tick causality remain unverified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wf_gsim_go_live_range_probe import run


def _native_spell_signature(report: dict) -> tuple:
    observations = report.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("NO_NATIVE_RANGE_OBSERVATIONS")
    rows = observations[-1].get("native_spell_counters")
    if not isinstance(rows, list):
        raise ValueError("NO_REAL_NATIVE_SPELL_COUNTERS")
    return tuple(sorted((row["action_id"], row["rank"], row["casts"], row["hits"],
                         row["crits"], row["ticks"], float(row["total_damage"]))
                        for row in rows))


def compare_paired_reports(near: dict, far: dict) -> dict:
    """Summarize genuine reports only; synthetic unit rows prove schema, not causality."""
    keys = ("native_binary_sha256", "native_source_revision", "native_request_sha256")
    if any(near.get(k) != far.get(k) or not near.get(k) for k in keys):
        raise ValueError("PAIRED_NATIVE_REQUEST_OR_ENGINE_NOT_IDENTICAL")
    for report in (near, far):
        if (report.get("status") != "NATIVE_GO_WORLD_DAMAGE_ACK_NOT_P7"
                or not report.get("native_process_reused")
                or not report.get("gsim_runtime_real")
                or type(report.get("native_spell_action_ack")) is not bool
                or report.get("checkpoint_certified") is not False):
            raise ValueError("PAIRED_WORLD_OR_NATIVE_PROVENANCE_UNVERIFIED")
    near_obs, far_obs = near["observations"], far["observations"]
    if len(near_obs) != len(far_obs) or len(near_obs) < 2:
        raise ValueError("PAIRED_WORLD_TICK_COUNT_MISMATCH")
    for report, observations in ((near, near_obs), (far, far_obs)):
        # Real Go must confirm the previous native event/world ACK before any
        # subsequent native step. Synthetic test fixtures assert schema only.
        if any(not isinstance(row.get("gsim_applied_world_ack"), dict)
               or not isinstance(row.get("native_world_ack_confirmation"), dict)
               or row["native_world_ack_confirmation"].get("observed_world_after_sha256")
               != row["gsim_applied_world_ack"].get("world_after_sha256")
               or row["native_world_ack_confirmation"].get("native_spell_action_ack")
               != bool(row["gsim_applied_world_ack"].get("applied_event_ids"))
               for row in observations):
            raise ValueError("PAIRED_NATIVE_WORLD_APPLIED_ACK_NOT_VERIFIED")
        if report["native_spell_action_ack"] != any(
                bool(row["gsim_applied_world_ack"]["applied_event_ids"])
                for row in observations):
            raise ValueError("PAIRED_NATIVE_ACTION_ACK_FLAG_NOT_SOURCE_DERIVED")
    near_range = tuple(round(row["world_tick"]["distance_yards"], 8) for row in near_obs)
    far_range = tuple(round(row["world_tick"]["distance_yards"], 8) for row in far_obs)
    if near_range == far_range:
        raise ValueError("PAIRED_WORLD_PERTURBATION_ABSENT")
    a, b = _native_spell_signature(near), _native_spell_signature(far)
    observed = a != b
    action_ack = near["native_spell_action_ack"] or far["native_spell_action_ack"]
    # A source-owned counter delta is not an applied-world effect. An empty
    # native event journal cannot establish native→gsim HP→native ACK causality.
    status = ("NATIVE_SPELL_DELTA_AND_WORLD_ACK_NOT_DRUID_P7"
              if observed and action_ack else
              "NATIVE_SPELL_DELTA_WITHOUT_WORLD_ACK_NOT_P7"
              if observed else "NO_NATIVE_SPELL_DELTA_OBSERVED")
    return {
        "kind": "pinned_go_real_gsim_range_to_native_spell_pair_v1",
        "status": status,
        "source_revision": near["native_source_revision"],
        "native_binary_sha256": near["native_binary_sha256"],
        "request_sha256": near["native_request_sha256"],
        "scenarios": {"near": near, "far": far},
        "range_perturbation_applied": True,
        "native_spell_counter_delta_observed": observed,
        "native_spell_action_ack": action_ack,
        "druid_l60_balance_proven": False,
        "checkpoint_certified": False,
    }


def run_pair(binary: Path, request: Path, *, ticks: int = 60) -> dict:
    raw = json.loads(request.read_text())
    try:
        seed = int(raw["simOptions"]["randomSeed"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("PAIRED_PINNED_REQUEST_NONZERO_SEED_REQUIRED") from exc
    if seed == 0:
        raise ValueError("PAIRED_PINNED_REQUEST_NONZERO_SEED_REQUIRED")
    near = run(binary, request, ticks=ticks, target_spawn_yards=3.)
    far = run(binary, request, ticks=ticks, target_spawn_yards=80.)
    return compare_paired_reports(near, far)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument("--require-native-spell-delta", action="store_true")
    args = parser.parse_args()
    report = run_pair(args.binary, args.request, ticks=args.ticks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(report["status"], "(native/gsim diagnostic, NOT Druid P7)")
    if args.require_native_spell_delta:
        if not report["native_spell_counter_delta_observed"]:
            raise SystemExit("NATIVE_SPELL_DIFFERENCE_NOT_OBSERVED")
        if not report["native_spell_action_ack"]:
            raise SystemExit("NATIVE_SPELL_APPLIED_WORLD_ACK_NOT_OBSERVED")


if __name__ == "__main__":
    main()
