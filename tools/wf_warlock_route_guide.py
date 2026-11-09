#!/usr/bin/env python3
"""Publish bounded Warlock 10-60 route coverage from actual native receipts.

This is a gsim-owned publication adapter, not a combat model or gate recorder.
The existing v2 DecisionResult/path_dp/dual_spec solver needs contiguous
source-native level frontiers; sparse observations must not be converted into
fake level nodes or stitched into an invented route.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBSERVATIONS = ROOT / "data/warlock/native_route_observations.json"


def _positive_number(value: Any, name: str) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return float(value)


def _observation(raw: dict, start: int, end: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("native observation must be an object")
    level = raw.get("level")
    if type(level) is not int or not start <= level <= end:
        raise ValueError("observation level outside requested route")
    requested, killed = raw.get("targets_requested"), raw.get("targets_killed")
    if type(requested) is not int or requested < 1 or type(killed) is not int or killed < 0 or killed > requested:
        raise ValueError("invalid native target counts")
    if raw.get("paid_native_recovery") is not True or raw.get("native_world_ack") is not True:
        raise ValueError("cannot publish unpaid/non-native-world receipt as measured")
    if requested != killed:
        raise ValueError("cannot score incomplete native-world chain")
    seconds = _positive_number(raw.get("seconds_per_mob"), "seconds_per_mob")
    run = raw.get("run_url")
    receipt = raw.get("receipt_path")
    linked = (isinstance(run, str) and run.startswith("https://github.com/")
              and "/actions/runs/" in run)
    local = (isinstance(receipt, str) and bool(receipt)
             and isinstance(raw.get("engine_binary_sha256"), str)
             and len(raw["engine_binary_sha256"]) == 64
             and isinstance(raw.get("source_request_sha256"), str)
             and len(raw["source_request_sha256"]) == 64)
    if not linked and not local:
        raise ValueError("measured observation requires an actual Actions run or hashed local native receipt")
    if run is not None and not linked:
        raise ValueError("invalid native Actions run URL")
    for key in ("id", "trial", "candidate", "scenario"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ValueError(f"missing {key} observation identity")
    for key in ("talents", "gear", "apl", "pet", "pulls", "recovery_policy", "engine_sha"):
        if raw.get(key) is not None and not isinstance(raw[key], (str, dict, list)):
            raise ValueError(f"invalid {key} description")
    return {
        "id": raw["id"], "level": level, "trial": raw["trial"],
        "candidate": raw["candidate"], "scenario": raw["scenario"],
        "targets_requested": requested, "targets_killed": killed,
        "seconds_per_mob": seconds,
        "elapsed_seconds_for_observed_chain": round(seconds * killed, 4),
        "paid_native_recovery": True, "native_world_ack": True,
        "run_url": run, "receipt_path": receipt, "artifact_url": raw.get("artifact_url"),
        "engine_sha": raw.get("engine_sha"),
        "engine_binary_sha256": raw.get("engine_binary_sha256"),
        "source_revision": raw.get("source_revision"),
        "candidate_sha256": raw.get("candidate_sha256"),
        "source_request_sha256": raw.get("source_request_sha256"),
        "talents": raw.get("talents"), "gear": raw.get("gear"),
        "apl": raw.get("apl"), "pet": raw.get("pet"),
        "pulls": raw.get("pulls"), "recovery_policy": raw.get("recovery_policy"),
        "notes": raw.get("notes"),
        "native_final_hp": raw.get("native_final_hp"),
        "native_final_mana": raw.get("native_final_mana"),
        "native_health_damage": raw.get("native_health_damage"),
        "native_food_seconds": raw.get("native_food_seconds"),
        "native_water_seconds": raw.get("native_water_seconds"),
        "status": "measured_native_chain",
    }



def observations_from_cold_summary(summary: dict, *, run_url: str,
                                   trial: str) -> list[dict]:
    """Read real retained-actor finalists from the existing native cold output.

    The producer's cold_summary.json keeps selected finalists, their native
    receipts and candidate hashes. Its snapshot rows contain exact builds
    only if the selected 100-target finalist is that snapshot candidate.
    Never fill in a build from a different candidate merely because its
    snapshot label matches.
    """
    if (not isinstance(summary, dict) or
            summary.get("kind") != "warlock_l20_cold_native_world_candidate_search" or
            summary.get("finalist_targets") != 100):
        raise ValueError("expected native Warlock L20 cold search summary")
    finalists = summary.get("finalists")
    if not isinstance(finalists, dict):
        raise ValueError("missing native 100-target finalists")
    source_revision = summary.get("source_revision")
    engine_binary = summary.get("engine_binary_sha256")
    if not isinstance(source_revision, str) or not source_revision or (
            not isinstance(engine_binary, str) or len(engine_binary) != 64):
        raise ValueError("native source and binary identity are required")
    out = []
    for label, snapshot_name in (("30s", "snapshot_30"), ("300s", "final_300")):
        result = finalists.get(label)
        if not isinstance(result, dict):
            raise ValueError(f"missing {label} finalist")
        receipt = result.get("native_receipt")
        sha = result.get("candidate_sha256")
        if (not isinstance(receipt, dict) or
                result.get("status") != "COMPLETED_100_REAL_NATIVE_GSIM_KILLS" or
                receipt.get("status") != "COMPLETED_100_REAL_NATIVE_GSIM_KILLS" or
                receipt.get("target_count_requested") != 100 or
                receipt.get("world_targets_killed") != 100 or
                receipt.get("native_actor_continuity_receipt_complete") is not True or
                receipt.get("native_recovery_clock_accounted") is not True or
                receipt.get("native_2d_paid_objective_eligible") is not True or
                receipt.get("native_recovery_mode") != "decisions_food_water" or
                receipt.get("native_binary_sha256") != engine_binary or
                not isinstance(sha, str) or len(sha) != 64 or
                result.get("seconds_per_mob") != receipt.get("seconds_per_mob")):
            raise ValueError(f"{label} has no comparable complete paid native receipt")
        snapshot = summary.get(snapshot_name)
        candidate = (snapshot.get("candidate")
                     if isinstance(snapshot, dict) and
                     snapshot.get("candidate_sha256") == sha else None)
        actor = None
        if isinstance(candidate, dict):
            try:
                actor = candidate["source"]["raid"]["parties"][0]["players"][0]
            except (KeyError, IndexError, TypeError):
                raise ValueError(f"{label} matched candidate lacks native actor request")
            # This fingerprint is the actual JSON bytes written by paid_chain().
            source_bytes = (json.dumps(candidate["source"], sort_keys=True) + "\n").encode()
            import hashlib
            if hashlib.sha256(source_bytes).hexdigest() != receipt.get("original_source_sha256"):
                raise ValueError(f"{label} candidate does not match native source request")
        recover = candidate.get("recovery") if candidate is not None else None
        out.append({
            "id": f"{trial}-{label}", "level": 20, "trial": trial,
            "candidate": f"{label} selected paid native finalist {sha[:12]}",
            "scenario": f"Native hostile L20 2D world / Decisions, source {source_revision}, engine binary {engine_binary}",
            "targets_requested": 100, "targets_killed": 100,
            "seconds_per_mob": receipt["seconds_per_mob"],
            "paid_native_recovery": True, "native_world_ack": True,
            "run_url": run_url,
            "artifact_url": None,
            "engine_sha": None, "engine_binary_sha256": engine_binary,
            "source_revision": source_revision,
            "candidate_sha256": sha,
            "source_request_sha256": receipt.get("original_source_sha256"),
            "talents": actor.get("talentsString") if actor else None,
            "gear": actor.get("equipment", {}).get("items") if actor else None,
            "apl": actor.get("rotation", {}).get("priorityList") if actor else None,
            "pet": actor.get("warlockOptions") if actor else None,
            "pulls": None, "recovery_policy": recover,
            "notes": ("Exact matched 100-target finalist build from native snapshot."
                      if actor else
                      "Selected 100-target finalist differs from frozen snapshot; "
                      "inspect preserved paid candidate/request artifact for exact build."),
        })
    return out



def observations_from_native_chain_summary(summary: dict, *, summary_path: Path,
                                           run_url: str | None = None,
                                           trial: str = "native-paid-l20") -> tuple[list[dict], list[dict]]:
    """Consume the *actual* paid native/gsim producer output and saved requests.

    No new combat evaluator. Failures remain observable, never scored. A local
    receipt is tied to the exact binary and prepared source request hashes;
    no unrelated historic Actions run is attributed to a new local execution.
    """
    if (not isinstance(summary, dict)
            or summary.get("kind") != "real_100_target_source_native_world_attempts"
            or summary.get("target_count_requested") != 100
            or summary.get("native_recovery_requested", {}).get("recovery_policy") != "decisions"):
        raise ValueError("expected 100-target paid native Decisions/gsim producer summary")
    binary = summary.get("native_binary_sha256")
    if not isinstance(binary, str) or len(binary) != 64:
        raise ValueError("native executable fingerprint missing")
    rows: list[dict] = []
    refusals: list[dict] = []
    attempts = summary.get("results")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("native producer has no attempted candidates")
    for result in attempts:
        if not isinstance(result, dict) or not isinstance(result.get("variant"), str):
            raise ValueError("malformed native producer candidate")
        status = result.get("status")
        if status != "COMPLETED_100_REAL_NATIVE_GSIM_KILLS":
            refusals.append({"variant": result["variant"], "status": status,
                             "error": result.get("error"), "killed": result.get("killed"),
                             "native_exit_code": result.get("native_exit_code")})
            continue
        if not (result.get("killed") == 100
                and result.get("target_count_requested") == 100
                and result.get("native_binary_sha256") == binary
                and result.get("native_actor_continuity_receipt_complete") is True
                and result.get("paid_recovery") is True
                and result.get("native_recovery_clock_accounted") is True
                and result.get("native_recovery_mode") == "decisions_food_water"
                and result.get("native_2d_paid_objective_eligible") is True
                and result.get("world_target_hp_matches_request") is True
                and result.get("native_food_water_observed") is True):
            raise ValueError("native candidate lacks complete paid 100-target world/actor receipt")
        source_path = summary_path.parent / result["variant"] / "source_request.json"
        if not source_path.is_file():
            raise ValueError(f"missing actually executed source request: {source_path}")
        raw_bytes = source_path.read_bytes()
        request_sha = hashlib.sha256(raw_bytes).hexdigest()
        if request_sha != result.get("source_request_sha256"):
            raise ValueError("source request bytes differ from executed native candidate")
        source = json.loads(raw_bytes)
        try:
            actor = source["raid"]["parties"][0]["players"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("executed native candidate has no source actor") from exc
        rows.append({
            "id": f"{trial}-{result['variant']}",
            "level": 20, "trial": trial,
            "candidate": f"paid native {result['variant']} ({request_sha[:12]})",
            "scenario": (f"Hostile retained-actor L20 native/gsim world, "
                         f"HP {result.get('mob_hp_native_scenario')}, "
                         f"damage {result.get('scenario_min_base_damage')}/"
                         f"{result.get('scenario_swing_speed')}s; binary {binary}"),
            "targets_requested": 100, "targets_killed": 100,
            "seconds_per_mob": result.get("seconds_per_mob"),
            "paid_native_recovery": True, "native_world_ack": True,
            "run_url": run_url, "receipt_path": str(summary_path.resolve()),
            "engine_binary_sha256": binary,
            "source_request_sha256": request_sha,
            "source_revision": None, "candidate_sha256": None,
            "talents": actor.get("talentsString"),
            "gear": actor.get("equipment", {}).get("items"),
            "apl": actor.get("rotation", {}).get("priorityList"),
            "pet": actor.get("warlockOptions"),
            "pulls": None,
            "recovery_policy": result.get("recovery_request"),
            "native_final_hp": result.get("final_hp"),
            "native_final_mana": result.get("final_mana"),
            "native_health_damage": result.get("native_health_damage"),
            "native_food_seconds": result.get("native_food_seconds"),
            "native_water_seconds": result.get("native_water_seconds"),
            "notes": "Actually executed and paid native chain, not a continuous 10–60 route.",
        })
    if not rows:
        return [], refusals
    return rows, refusals


def execute_native_l20(*, binary: Path, source: Path, out: Path) -> Path:
    """Invoke existing Rust/gsim producer once, then consume its persisted receipt."""
    if not binary.is_file() or not source.is_file():
        raise ValueError("native --binary and --source must be existing files")
    native_out = out / "native_l20"
    cmd = [
        sys.executable, str(ROOT / "tools/wf_warlock_l20_100mob.py"),
        "--binary", str(binary.resolve()), "--source", str(source.resolve()),
        "--out", str(native_out.resolve()),
        "--targets", "100", "--variant", "best_apl",
        "--hostile-player-tank", "--recovery-policy", "decisions",
        "--require-native-health-damage",
    ]
    outcome = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                             check=False)
    summary_path = native_out / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError(f"native producer failed ({outcome.returncode}): "
                           f"{(outcome.stderr or outcome.stdout)[-2500:]}")
    # Do not hide a refusal: summary.json contains its exact status/killed/error;
    # caller only publishes complete paid kills as measured observations.
    return summary_path


def build_route_report(payload: dict) -> dict:
    """Preserve distinct paid measurements; never fabricate missing level costs."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("class") != "warlock":
        raise ValueError("expected warlock native route observations schema v1")
    start, end = payload.get("start_level"), payload.get("end_level")
    if type(start) is not int or type(end) is not int or start < 1 or end < start:
        raise ValueError("invalid route level range")
    observations = [_observation(row, start, end) for row in payload.get("observations", [])]
    refusals = payload.get("native_refusals", [])
    if not isinstance(refusals, list):
        raise ValueError("native_refusals must be a list")
    if len({row["id"] for row in observations}) != len(observations):
        raise ValueError("duplicate observation IDs")
    # A trial only compares build candidates against one declared scenario.
    # A separate official cold search is not numerically interchangeable with
    # an earlier no-record run even if the actor's level matches.
    trials: dict[str, dict] = {}
    for row in observations:
        trial = trials.setdefault(row["trial"], {
            "scenario": row["scenario"], "level": row["level"], "candidates": []})
        if (trial["scenario"], trial["level"]) != (row["scenario"], row["level"]):
            raise ValueError("trial combines different levels or scenarios")
        trial["candidates"].append(row)
    comparisons = []
    for name, trial in sorted(trials.items()):
        ordered = sorted(trial["candidates"], key=lambda r: (r["seconds_per_mob"], r["id"]))
        comparisons.append({
            "trial": name, "level": trial["level"], "scenario": trial["scenario"],
            "observations": [r["id"] for r in ordered],
            "fastest_observed_id": ordered[0]["id"],
            "fastest_observed_seconds_per_mob": ordered[0]["seconds_per_mob"],
            "comparable_with_other_trials": False,
        })
    by_level = {level: [] for level in range(start, end + 1)}
    for row in observations:
        by_level[row["level"]].append(row["id"])
    levels = [
        {"level": level, "status": "measured_native_chain" if by_level[level] else "not_measured",
         "observations": sorted(by_level[level]), "route_step_selected": False}
        for level in range(start, end + 1)
    ]
    missing = [level for level in by_level if not by_level[level]]
    return {
        "schema_version": 1, "class": "warlock", "start_level": start,
        "end_level": end, "authority": "source_native_observations",
        "status": "sparse_evidence_no_executable_continuous_route",
        "full_10_60_native_replay_executed": False,
        "elapsed_10_60_seconds": None,
        "levels": levels, "observations": observations, "comparisons": comparisons,
        "native_refusals": refusals,
        "measured_levels": [level for level in by_level if by_level[level]],
        "unmeasured_levels": missing,
        "dual_spec": {
            "unlock_level": 40, "status": "not_measured",
            "single_spec_elapsed_seconds": None,
            "dual_spec_elapsed_seconds": None, "time_saved_seconds": None,
            "note": "Optional L40 dual-spec requires contiguous paid native frontiers; no forced switch.",
        },
        "next_step": (
            "Load native candidate/build receipts, then feed contiguous measured "
            "level frontiers into existing v2 DecisionResult/path_dp and dual_spec; "
            "execute selected route in Rust and publish its retained-state trace."
        ),
    }


def _ranges(levels: list[int]) -> str:
    if not levels:
        return "none"
    runs = []
    start = end = levels[0]
    for n in levels[1:]:
        if n == end + 1:
            end = n
        else:
            runs.append(f"L{start}" if start == end else f"L{start}-{end}")
            start = end = n
    runs.append(f"L{start}" if start == end else f"L{start}-{end}")
    return ", ".join(runs)


def render_guide(report: dict) -> str:
    lines = [
        "# Warlock 10–60 — native evidence and route coverage",
        "",
        "This is a measured **partial route dossier**, not a claimed executed 10–60 leveling route.",
        "No hypothetical level transitions, talent allocations, consumables or dual-spec savings are filled in.",
        "",
        f"Measured levels: **{_ranges(report['measured_levels'])}**.",
        f"Not measured: **{_ranges(report['unmeasured_levels'])}**.",
        "",
        "## Paid native-world observations (do not compare unrelated trials)",
        "",
    ]
    for comp in report["comparisons"]:
        lines += [f"### {comp['trial']} — L{comp['level']}", "",
                  f"Scenario: {comp['scenario']}.", ""]
        for oid in comp["observations"]:
            row = next(r for r in report["observations"] if r["id"] == oid)
            lines += [
                f"- **{row['candidate']}**: {row['targets_killed']}/{row['targets_requested']} "
                f"native ACK kills, {row['seconds_per_mob']:.4f} s/mob, "
                f"paid native recovery. "
                + (f"[Actual run]({row['run_url']})." if row["run_url"]
                   else f"Local receipt: {row['receipt_path']}.")
            ]
            if row["notes"]:
                lines.append(f"  - {row['notes']}")
            for field in ("talents", "gear", "apl", "pet", "recovery_policy"):
                if row[field] is not None:
                    lines.append(f"  - {field}: {json.dumps(row[field], sort_keys=True)}")
            unknown = [k for k in ("talents", "gear", "apl", "pet", "pulls", "recovery_policy")
                       if row[k] is None]
            if unknown:
                lines.append("  - Build/policy not supplied in this compact receipt: " + ", ".join(unknown) +
                             "; inspect linked run artifacts before copying this build.")
        lines += ["", "Fastest **within this trial only**: " +
                  comp["fastest_observed_id"] + ". This is not a cross-trial route winner.", ""]
    if report["native_refusals"]:
        lines += ["## Native refusals (not scored)", ""]
        for refused in report["native_refusals"]:
            lines.append(f"- {refused['variant']}: {refused['status']}, "
                         f"killed={refused.get('killed')}, "
                         f"error={refused.get('error')}")
        lines.append("")
    lines += [
        "## Route and dual spec",
        "",
        "No contiguous source-native L10–60 level frontier or full replay is available "
        "in these observations. The existing gsim path DP and dual-spec solver must "
        "not be run with invented intermediate candidates.",
        "",
        "L40 optional dual spec: **not measured**. No switch, savings or cost claim.",
        "",
        "## Next executable step",
        "",
        report["next_step"], "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, help="Native observation manifest (default: historical L20 evidence)")
    parser.add_argument("--cold-summary", type=Path, help="Read actual native cold_summary.json finalists instead")
    parser.add_argument("--native-summary", type=Path, help="Consume existing paid Warlock L20 native/gsim 100-target summary.json")
    parser.add_argument("--execute-native", action="store_true", help="Execute one paid hostile Warlock L20 100-target Rust/gsim scenario and publish its result")
    parser.add_argument("--binary", type=Path, help="Selected compiled native Rust binary for --execute-native")
    parser.add_argument("--source", type=Path, help="Exact native Warlock L20 source request for --execute-native")
    parser.add_argument("--run-url", help="Exact GitHub Actions run URL for --cold-summary")
    parser.add_argument("--trial", default="imported-native-cold", help="Identity of one comparable native run")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if sum(bool(x) for x in (args.observations, args.cold_summary,
                             args.native_summary, args.execute_native)) > 1:
        parser.error("choose one input: --observations, --cold-summary, --native-summary, or --execute-native")
    if args.execute_native and (not args.binary or not args.source):
        parser.error("--execute-native requires --binary and --source")
    if not args.execute_native and (args.binary or args.source):
        parser.error("--binary/--source require --execute-native")
    if (args.native_summary or args.execute_native) and args.run_url is None:
        # Local receipts are first-class and must never pretend to be an old CI run.
        pass
    if args.cold_summary:
        if args.observations or not args.run_url:
            parser.error("--cold-summary needs --run-url and cannot combine --observations")
        payload = {
            "schema_version": 1, "class": "warlock",
            "start_level": 10, "end_level": 60,
            "observations": observations_from_cold_summary(
                json.loads(args.cold_summary.read_text()),
                run_url=args.run_url, trial=args.trial),
        }
    elif args.native_summary or args.execute_native:
        native_path = (execute_native_l20(binary=args.binary, source=args.source, out=args.out)
                       if args.execute_native else args.native_summary)
        rows, refusals = observations_from_native_chain_summary(
            json.loads(native_path.read_text()), summary_path=native_path,
            run_url=args.run_url, trial=args.trial)
        if not rows:
            raise ValueError(f"no complete paid native L20 100-target candidate; "
                             f"refusals preserved in {native_path}: {refusals}")
        payload = {"schema_version": 1, "class": "warlock",
                   "start_level": 10, "end_level": 60,
                   "observations": rows, "native_refusals": refusals}
    else:
        payload = json.loads((args.observations or DEFAULT_OBSERVATIONS).read_text())
    report = build_route_report(payload)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "route.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.out / "GUIDE.md").write_text(render_guide(report))
    print(f"Published {len(report['observations'])} native observations; "
          f"{len(report['measured_levels'])} measured level(s), "
          f"{len(report['unmeasured_levels'])} unmeasured level(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
