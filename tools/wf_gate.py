#!/usr/bin/env python3
"""Class/level/spec-specific active P3-P7.5 acceptance gates for WoW Forever.

Runtime-first acceptance: execute the source-backed gate implementation.
Evidence JSON is OUTPUT ONLY, never an input authority to award PASS. Missing
executable gate implementations are BLOCKED (exit nonzero), even if a historical
JSON claims PASS.

Example:
    python tools/wf_gate.py --class druid --level 20 --gate P3
    python tools/wf_gate.py --class druid --level 30 --spec feral-cat --gate all

A gate provider runs the actual code and returns an auditable result. An optional
--out file stores the report after execution. Cold 30/300-second searches are
separate explicit runs: this command never substitutes stale stored JSON
or silently launches expensive searches for other gates.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import re
import sys
from pathlib import Path

GATES = tuple(f"P{i}" for i in range(3, 7)) + tuple(f"P7.{i}" for i in range(1, 6))
ROOT = Path(__file__).resolve().parent.parent
# The documented CLI works from a clean checkout without PYTHONPATH exports.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_live_gate(root: Path, class_key: str, level: int, spec: str,
                   gate: str, scenario_id: str = "") -> dict:
    """Execute one active production gate; retired P1/P2 are not callable.

    Keep the optional trailing scenario argument for existing P7 callers; it is
    intentionally ignored because scenario-specific P1 execution is retired.
    """
    if gate not in GATES:
        return {"status": "BLOCKED", "reasons": ["RETIRED_OR_UNKNOWN_GATE:" + gate]}
    # Explicit provider naming contract for one-gate-sized implementations.
    # A provider implements run_live(root, class_key, level, *, spec=...)
    # and MUST execute/check the actual runtime and acceptance predicate.
    module_name = "tools.wf_gate_" + gate.lower().replace(".", "_") + "_live"
    try:
        provider = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return {"status": "BLOCKED", "reasons": [
                "LIVE_GATE_RUNNER_MISSING:" + module_name]}
        return {"status": "BLOCKED", "reasons": [
            "LIVE_GATE_DEPENDENCY_MISSING:" + str(exc.name)]}
    except Exception as exc:
        return {"status": "FAIL", "reasons": [
            "LIVE_GATE_IMPORT_FAILED:" + type(exc).__name__]}
    run_live = getattr(provider, "run_live", None)
    if not callable(run_live):
        return {"status": "BLOCKED", "reasons": [
            "LIVE_GATE_RUNNER_NOT_CALLABLE:" + module_name]}
    try:
        report = run_live(root, class_key, level, spec=spec)
    except Exception as exc:
        return {"status": "FAIL", "reasons": [
            "LIVE_GATE_EXECUTION_FAILED:" + type(exc).__name__ + ":" + str(exc)[:240]]}
    if not isinstance(report, dict) or report.get("status") not in (
            "PASS", "FAIL", "BLOCKED"):
        return {"status": "FAIL", "reasons": ["INVALID_LIVE_GATE_REPORT"]}
    reasons = report.get("reasons", [])
    if not isinstance(reasons, list) or any(not isinstance(x, str) for x in reasons):
        return {"status": "FAIL", "reasons": ["INVALID_LIVE_GATE_REASONS"]}
    if report["status"] == "PASS" and reasons:
        return {"status": "FAIL", "reasons": ["INCONSISTENT_LIVE_GATE_PASS"]}
    if report["status"] != "PASS" and not reasons:
        return {"status": "FAIL", "reasons": ["LIVE_GATE_FAILURE_WITHOUT_REASON"]}
    # Every active gate must identify a real executed engine and its run.
    # These are necessary metadata, NOT a substitute for testing real behavior.
    if report["status"] == "PASS":
        proof = report.get("runtime_proof")
        if not isinstance(proof, dict) or proof.get("executed") is not True or any(
                not isinstance(proof.get(k), str) or not proof[k]
                for k in ("engine_revision", "source_revision", "run_id")):
            return {"status": "FAIL", "reasons": [
                "MISSING_EXECUTED_RUNTIME_PROOF"]}
    return report


def _p6_replay_receipts(report: dict) -> list[dict] | None:
    """Surface the two actual paid replay outcomes without changing gate scoring.

    The paid provider already computes each cold leg's status and first reason.
    Without these small receipts the public no-record gate report only says
    100/200, losing the actual failure necessary for the next RED->GREEN fix.
    Keep the output bounded; this is diagnostic data, never PASS evidence.
    """
    rows = report.get("source_replay_results")
    if not isinstance(rows, list):
        return None
    allowed = ("cold_search_budget_s", "status", "reason", "count",
               "mob_completed", "failed_pull_index", "paid_screens",
               "mean_s_per_mob", "s_per_mob", "events")
    out = []
    for row in rows[:2]:
        if not isinstance(row, dict):
            out.append({"status": "INVALID_REPLAY_RECEIPT"})
            continue
        clean = {}
        for key in allowed:
            value = row.get(key)
            if type(value) is str:
                clean[key] = value[:240]
            elif type(value) in (int, float) and math.isfinite(value):
                clean[key] = value
        out.append(clean)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute live source-backed WoW Forever active P3–P7.5 gates")
    parser.add_argument("--class", dest="class_key", required=True)
    parser.add_argument("--level", type=int, required=True)
    parser.add_argument("--spec", default="unrestricted")
    parser.add_argument("--gate", choices=(*GATES, "P7", "all"), required=True)
    parser.add_argument("--out", type=Path,
                        help="Write the freshly executed results and provenance")
    parser.add_argument("--record-pass", "--record-progress", dest="record_pass",
                        action="store_true",
                        help="Merge-only: record genuine live PASS or measured PARTIAL in the same M1 ledger")
    a = parser.parse_args(argv)
    for name, value in (("class", a.class_key), ("spec", a.spec)):
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
            parser.error(f"--{name} requires a lower-case source key")
    if not 1 <= a.level <= 60:
        parser.error("--level must be within 1..60")
    targets = (GATES if a.gate == "all" else
               tuple(f"P7.{n}" for n in range(1, 6)) if a.gate == "P7"
               else (a.gate,))
    results = []
    for gate in targets:
        report = _run_live_gate(ROOT, a.class_key, a.level, a.spec, gate)
        if a.record_pass:
            from tools.m1_progress import record_partial, record_pass
            if report["status"] == "PASS":
                record_pass(class_key=a.class_key, level=a.level, spec=a.spec,
                            gate=gate, report=report)
            elif report["status"] == "FAIL" or (
                    gate.startswith("P7.") and report["status"] == "BLOCKED"):
                # A real coupled P7 DPS measurement can be useful even if a
                # separate UI/holdout requirement keeps the gate BLOCKED.
                # The recorder rejects non-executed BLOCKED and fake counts.
                record_partial(class_key=a.class_key, level=a.level, spec=a.spec,
                               gate=gate, report=report)
        record = {"gate": gate, "status": report["status"],
                  "reasons": report.get("reasons", [])}
        for key in ("reachability_count", "pass_count", "unresolved_count",
                    "behavior_probes_executed", "runtime_proof",
                    "production_engine", "engine_id", "source_id",
                    "source_context_sha256", "real_source_search_attempts",
                    "real_source_search_evaluated", "source_naked_stage",
                    "source_naked_diagnostics", "source_actor_context",
                    "real_catalogue_top5_items_scored",
                    "source_report_url", "source_request_raw_sha256",
                    "native_source_revision", "iterations",
                    "sampled_source_fights", "saved_source_iterations",
                    "native_first_duration_s", "world_first_duration_s",
                    "source_replay_Tfirst_Tsecond", "source_replay_numeric_saturation",
                    "joint_cold_world_dps", "joint_cold_native_dps",
                    "frozen_stochastic_iterations", "frozen_stochastic_native_dps",
                    "frozen_request_raw_sha256", "search_wall_s",
                    "external_reference_only_floor",
                    "final_required_dps", "source_legal_joint_candidates_paid",
                    "cold_winner_request_sha256",
                    "selected_balanced_request_sha256",
                    "cold_candidate_failures"):
            if key in report:
                record[key] = report[key]
        if gate == "P3":
            # Make the real bounded Rust baseline/equipped pair visible to the
            # ordinary no-record CLI. Otherwise the producer's native verdict,
            # paid attempts and actor identity silently disappear from Actions.
            native_pair = report.get("native_equipped_paid_receipt")
            if isinstance(native_pair, dict):
                record["native_equipped_paid_receipt"] = {
                    key: native_pair[key]
                    for key in ("status", "paid_attempts", "swap",
                                "comparison", "evaluations",
                                "actor_checkpoint_verified", "promotion")
                    if key in native_pair
                }
            for key in ("native_equipped_paid_attempts",
                        "p3_shared_budget_attempts",
                        "p3_native_pair_reserved_attempts"):
                value = report.get(key)
                if type(value) is int and 0 <= value <= 44:
                    record[key] = value
            # Preserve the measured source-policy witness and weight vector so
            # a first-contact P3 failure can be repaired from its actual cause.
            # These are bounded diagnostics only; they never alter PASS/M1.
            witnesses = report.get("source_policy_stat_witnesses")
            if isinstance(witnesses, list):
                record["source_policy_stat_witnesses"] = witnesses[:8]
            axis_selection = report.get("real_stat_probe_axis_selection")
            if isinstance(axis_selection, dict):
                record["real_stat_probe_axis_selection"] = axis_selection
            weights = report.get("real_measured_stat_weights")
            if isinstance(weights, dict):
                record["real_measured_stat_weights"] = {
                    str(axis): float(value)
                    for axis, value in list(weights.items())[:32]
                    if type(value) in (int, float) and math.isfinite(value)
                }
            for key in ("real_catalogue_legal_items", "real_catalogue_slots_scored",
                        "actual_search_result_status", "item_options_source",
                        "native_item_options_status", "native_unverified_candidate_count",
                        "native_excluded_non_client_item_count", "native_item_options_source"):
                value = report.get(key)
                if type(value) is int or isinstance(value, str):
                    record[key] = value
            # Keep the exact native spell-rank source receipt in the public
            # gate report; the context hash alone is not enough to reproduce
            # which Rust spell coefficients were applied to the L30 actions.
            for key in (
                "native_spell_coefficients_source",
                "native_spell_coefficients_engine_revision",
                "native_spell_coefficients_error",
            ):
                value = report.get(key)
                if isinstance(value, str):
                    record[key] = value
            applied = report.get("native_spell_coefficients_applied")
            if isinstance(applied, list):
                record["native_spell_coefficients_applied"] = applied[:8]
            paid_winner_probe = report.get("native_paid_winner_spell_probe_enabled")
            if type(paid_winner_probe) is bool:
                record["native_paid_winner_spell_probe_enabled"] = paid_winner_probe
            # Forward only the native context identity and bounded facts already
            # returned by the P3 provider. This is a source receipt, not a new
            # player-stat calculation or acceptance requirement.
            for key in ("native_player_context_id", "native_player_context_scope",
                        "native_player_context_kind", "native_player_context_race"):
                value = report.get(key)
                if isinstance(value, str) and 0 < len(value) <= 256:
                    record[key] = value
            for context_key in ("native_player_context_base_stats",
                                "native_player_context_resources",
                                "native_player_context_weapon"):
                facts = report.get(context_key)
                if isinstance(facts, dict):
                    record[context_key] = {
                        str(key): value
                        for key, value in list(facts.items())[:24]
                        if (type(value) in (int, float) and math.isfinite(value))
                        or (isinstance(value, str) and len(value) <= 256)
                    }
            profile = report.get("source_profile_production_build")
            if isinstance(profile, dict):
                record["source_profile_production_build"] = profile
        if gate.startswith("P7."):
            # Real P7 providers report the frozen 1,000-stochastic outcome,
            # but the public CLI previously dropped it. Keep this bounded
            # receipt available for diagnosing a failed paid search. These
            # values never modify the provider verdict or create M1 credit.
            for key in ("search_wall_s", "cold_unique_source_requests",
                        "winner_live_dps", "winner_screen_dps",
                        "paid_stochastic_finalists",
                        "paid_stochastic_confirmed_finalists",
                        "source_legal_cold_candidates_paid",
                        "native_world_scored_candidates_paid",
                        "native_invalid_candidates",
                        "native_unsupported_candidates",
                        "native_unscored_candidates",
                        "native_execution_errors",
                        "world_execution_errors",
                        "frozen_stochastic_iterations",
                        "frozen_stochastic_native_dps",
                        "frozen_stochastic_world_dps",
                        "frozen_stochastic_world_damage_events",
                        "frozen_stochastic_world_boundaries"):
                # P7.4 uses paid Balanced finalist screens. Its provider's
                # stochastic finalist counters are hard-coded placeholders.
                if gate == "P7.4" and key in (
                        "paid_stochastic_finalists",
                        "paid_stochastic_confirmed_finalists"):
                    continue
                value = report.get(key)
                if type(value) in (int, float) and math.isfinite(value):
                    record[key] = value
            for key in ("independent_300s_search_completed",
                        "frozen_stochastic_reference_floor_met",
                        "frozen_stochastic_external_only_floor_met"):
                if type(report.get(key)) is bool:
                    record[key] = report[key]
            for key in ("winner_selection", "frozen_request_raw_sha256",
                        "frozen_stochastic_failure", "search_strategy",
                        "source_original_talents", "cold_winner_talents"):
                value = report.get(key)
                if isinstance(value, str) and len(value) <= 256:
                    record[key] = value
            for key in ("native_refusal_samples", "native_unscored_samples"):
                value = report.get(key)
                if isinstance(value, list):
                    record[key] = value[:4]
        if gate in ("P7.2", "P7.3", "P7.4"):
            # The approved single-axis producers score changed APL, talent or
            # gear directly on selected native Rust. Forward actual paid native
            # scores; no legacy 2D or stochastic proxy can stand in for them.
            score = report.get("winner_native_dps")
            if (type(score) in (int, float) and math.isfinite(score)
                    and score >= 0):
                record["winner_native_dps"] = score
            for key in ("original_apl_hash", "source_original_talents",
                        "cold_winner_talents", "selected_validation",
                        "reference_profile", "checkpoint_spec"):
                value = report.get(key)
                if isinstance(value, str) and len(value) <= 128:
                    record[key] = value
            for flag in ("source_fixed_gear_and_talents", "fixed_rotation_and_gear",
                         "source_fixed_rotation_and_talents"):
                if type(report.get(flag)) is bool:
                    record[flag] = report[flag]
            apl = report.get("cold_winner_apl")
            if (isinstance(apl, list) and 0 < len(apl) <= 50
                    and len(json.dumps(apl, ensure_ascii=False).encode("utf-8")) <= 8192):
                record["cold_winner_apl"] = apl
        if gate == "P7.5":
            # The live provider now returns the exact independently paid
            # frozen winner. Preserve it in the CLI/M1 Actions receipt so a
            # failed 300s search can be diagnosed without repeating the heavy
            # run just to recover gear, talents and APL. Reporting only.
            frozen_build = report.get("frozen_source_build")
            if (isinstance(frozen_build, dict)
                    and len(json.dumps(frozen_build, ensure_ascii=False).encode(
                        "utf-8")) <= 16384):
                record["frozen_source_build"] = frozen_build
            # A P7.5 production FAIL may have a high short balanced score
            # but a low independent frozen 1,000-stochastic result. Forward
            # the actually paid confirmation tier/counts from this same run
            # so the next Work1 cycle can diagnose selection without another
            # heavy 300 s search. These are diagnostics, never gate credit.
            for key in ("cold_balanced_screen_best_dps",
                        "selected_balanced_screen_dps",
                        "paid_joint_balanced_finalists",
                        "paid_joint_balanced_confirmed",
                        "paid_joint_balanced_deep_confirmed",
                        "balanced_parent_proposals"):
                value = report.get(key)
                if type(value) in (int, float) and math.isfinite(value):
                    record[key] = value
            selected_validation = report.get("selected_validation")
            if isinstance(selected_validation, str) and len(selected_validation) <= 128:
                record["selected_validation"] = selected_validation
            failures = report.get("balanced_finalist_failures")
            if isinstance(failures, list):
                record["balanced_finalist_failures"] = [
                    str(error)[:180] for error in failures[:4]]
            # The P7.5 provider exposes WF613's own adaptive-search counters.
            # Preserve these bounded diagnostics in the CLI receipt: the
            # default-only balanced_parent_proposals counter is not meaningful
            # for WF613. They never affect the gate verdict or M1 credit.
            if report.get("search_strategy") == "wf613":
                for key in ("operator_attempts", "operator_best_improvements"):
                    value = report.get(key)
                    if (isinstance(value, dict) and 0 < len(value) <= 16
                            and all(isinstance(name, str) and 0 < len(name) <= 64
                                    and type(count) is int and count >= 0
                                    for name, count in value.items())):
                        record[key] = value
                archive_size = report.get("paid_archive_size")
                if type(archive_size) is int and 0 <= archive_size <= 48:
                    record["paid_archive_size"] = archive_size
                best_paid = report.get("best_paid_balanced_world_dps")
                if (type(best_paid) in (int, float)
                        and math.isfinite(best_paid) and best_paid >= 0):
                    record["best_paid_balanced_world_dps"] = best_paid
        if gate == "P7.4":
            # The P7.4 provider selects with paid Balanced screens, not
            # stochastic finalists. Forward the actual bounded counts; the
            # provider's stochastic counters are placeholders, not evidence.
            for key in ("paid_balanced_finalists", "paid_balanced_confirmed"):
                value = report.get(key)
                if type(value) is int and 0 <= value <= 6:
                    record[key] = value
            # Forward only bounded, source-executed winner identity. This is
            # diagnostic provenance, never an additional gate predicate.
            gear = report.get("cold_winner_gear")
            if (isinstance(gear, list) and 0 < len(gear) <= 24
                    and all(isinstance(row, dict)
                            and type(row.get("slot")) is int
                            and type(row.get("item_id")) is int
                            and (row.get("enchant_id") is None
                                 or type(row.get("enchant_id")) is int)
                            for row in gear)):
                record["cold_winner_gear"] = gear
            # Native option-source identity and refusal totals show whether
            # the production search used the pinned engine's candidate space.
            for key in ("source_candidate_failure_count",
                        "pinned_rust_unique_item_options",
                        "pinned_rust_unique_enchant_options"):
                value = report.get(key)
                if type(value) is int and 0 <= value <= 100000:
                    record[key] = value
            if type(report.get("pinned_rust_item_options_applied")) is bool:
                record["pinned_rust_item_options_applied"] = report["pinned_rust_item_options_applied"]
            for key in ("native_source_revision", "item_candidate_admission"):
                value = report.get(key)
                if isinstance(value, str) and len(value) <= 128:
                    record[key] = value
            # Actual rejected paid proposals and finalist reevaluations are
            # necessary to distinguish a quality regression from a failed
            # search invocation. Bound the receipt; it is not M1 evidence.
            for key in ("source_candidate_failures", "balanced_finalist_failures"):
                errors = report.get(key)
                if isinstance(errors, list):
                    limit = 800 if key == "source_candidate_failures" else 180
                    record[key] = [error[:limit] for error in errors[:4]
                                   if isinstance(error, str)]
        if gate in ("P4", "P5"):
            # Real 30/300s search and 100-mob finalist measurements are already
            # present in the live provider. Keep them visible when the gate is
            # still FAIL for separate native/world or source predicates.
            # Report only bounded factual fields; no fabricated gate coverage.
            paid_fields = (
                "requested_wall_budget_s", "real_search_wall_s",
                "real_paid_unique_full_builds", "real_paid_screen_complete",
                "real_100mob_complete", "real_100mob_count",
                "real_100mob_s_per_mob", "saved_full_source_winner_build",
                "gear_source_snapshot_matches_current",
                "winning_gear_source_legality_verified",
                "source_class_gear_membership_attested",
                "independent_N30_unique_paid", "independent_N300_unique_paid",
                "independent_p5_2x_breadth",
                "independent_same_source_candidate_space",
                "independent_100mob_winner_replays_complete")
            boolean_fields = {
                "real_100mob_complete", "saved_full_source_winner_build",
                "gear_source_snapshot_matches_current",
                "winning_gear_source_legality_verified",
                "source_class_gear_membership_attested",
                "independent_p5_2x_breadth",
                "independent_same_source_candidate_space",
                "independent_100mob_winner_replays_complete"}
            for key in paid_fields:
                value = report.get(key)
                if ((key in boolean_fields and type(value) is bool)
                    or (key not in boolean_fields
                        and type(value) in (int, float)
                        and math.isfinite(value))):
                    record[key] = value
        if gate == "P6":
            # The existing paid evaluator already supplied these outcomes;
            # publishing them reveals the first real incomplete replay reason.
            # The receipt is NOT an additional passed assertion or M1 credit.
            replay_receipts = _p6_replay_receipts(report)
            if replay_receipts is not None:
                record["source_replay_results"] = replay_receipts
        # One canonical calculation: no percent for BLOCKED, inventories,
        # or FAIL without an executed production behavior. A bounded component
        # is explicitly provisional and never substitutes for gate acceptance.
        from tools.wf_gate_coverage import (measured_live_coverage,
                                            measured_p7_dps_proximity)
        measured = measured_live_coverage(report)
        if measured is not None:
            record.update(measured)
        # P7 is a score target: show how close actual coupled DPS comes
        # to the correct threshold, not what fraction of fights was sampled.
        # This is separately named because DPS proximity is not gate success.
        dps = measured_p7_dps_proximity(gate, report)
        if dps is not None:
            record.update(dps)
        results.append(record)
    statuses = [x["status"] for x in results]
    verdict = ("PASS" if all(x == "PASS" for x in statuses)
               else "FAIL" if "FAIL" in statuses else "BLOCKED")
    output = {"class": a.class_key, "level": a.level, "spec": a.spec,
              "gate": a.gate, "status": verdict, "results": results}
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    return 0 if verdict == "PASS" else 1

if __name__ == "__main__":
    sys.exit(main())
