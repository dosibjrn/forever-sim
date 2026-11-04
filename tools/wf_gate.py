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
from typing import Any

GATES = tuple(f"P{i}" for i in range(3, 7)) + tuple(f"P7.{i}" for i in range(1, 6))
ROOT = Path(__file__).resolve().parent.parent
# The documented CLI works from a clean checkout without PYTHONPATH exports.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _nonneg(x: Any) -> bool:
    return type(x) in (int, float) and math.isfinite(x) and x >= 0


def _positive(x: Any) -> bool:
    return _nonneg(x) and x > 0


def _fail_if(errors: list[str], condition: bool, message: str) -> None:
    if condition:
        errors.append(message)


def _require_count(e: dict, errors: list[str], field: str) -> Any:
    value = e.get(field)
    if type(value) is not int or value < 0:
        errors.append(f"INVALID_OR_MISSING:{field}")
        return None
    return value


def _count_at_least(e: dict, errors: list[str], numerator: str, denominator: str) -> None:
    n = _require_count(e, errors, numerator)
    d = _require_count(e, errors, denominator)
    if d == 0:
        errors.append(f"NO_SOURCE_COVERAGE:{denominator}=0")
    if n is not None and d is not None and n < d:
        errors.append(f"INCOMPLETE:{numerator}={n}/{d}")


def _require_zero(e: dict, errors: list[str], field: str) -> None:
    value = e.get(field)
    if isinstance(value, list):
        if value:
            errors.append(f"NONEMPTY:{field}={len(value)}")
    elif type(value) is int:
        if value:
            errors.append(f"NONZERO:{field}={value}")
    else:
        errors.append(f"INVALID_OR_MISSING:{field}")


def _require_true(e: dict, errors: list[str], field: str) -> None:
    if e.get(field) is not True:
        errors.append(f"FALSE_OR_MISSING:{field}")



def _validate_p3(e: dict, _: dict) -> list[str]:
    """Approved P3 v2.1: fast ilvl-top5 legal items and contextual scoring.

    NOT a full BiS catalogue proof or a mandatory nonzero equipped-weapon DPS
    weight for an unrelated caster rotation. Applicable weapon channels must
    come from the currently executed IR/policy, never hardcoded by class.
    """
    errors: list[str] = []
    _count_at_least(e, errors, "slots_with_valid_top5", "legal_equipment_slots")
    _require_true(e, errors, "all_top5_items_source_legal")
    _require_true(e, errors, "per_item_stat_contributions_present")
    _require_true(e, errors, "contextual_weights_tested_against_objective")
    _require_zero(e, errors, "missing_stat_axes")
    weights = e.get("context_stat_weights")
    if not isinstance(weights,dict) or not weights or any(
            not isinstance(k,str) or not k or type(v) not in (float,int)
            or not math.isfinite(v) or v < 0 for k,v in weights.items()):
        errors.append("INVALID_NEGATIVE_OR_MISSING_CONTEXT_STAT_WEIGHTS")
        weights = weights if isinstance(weights,dict) else {}
    required_axes=e.get('applicable_positive_stat_axes')
    if not isinstance(required_axes,list):
        errors.append('MISSING_CONTEXT_REQUIRED_POSITIVE_AXES')
    else:
        for axis in required_axes:
            if type(weights.get(axis)) not in (float,int) or weights[axis]<=0:
                errors.append('APPLICABLE_STAT_WEIGHT_NOT_POSITIVE:'+str(axis))
    weapon_axes=e.get('applicable_weapon_dps_axes')
    if not isinstance(weapon_axes,list) or any(x not in ('weapon_dps','wand_dps','ranged_weapon_dps') for x in weapon_axes):
        errors.append('MISSING_OR_INVALID_IR_DEPENDENT_WEAPON_CHANNELS')
    elif weapon_axes and not any(type(weights.get(axis)) in (float,int) and weights[axis]>0 for axis in weapon_axes):
        errors.append('NO_POSITIVE_CAUSAL_WEAPON_DPS_CHANNEL')
    if type(e.get('mean_weapon_hit_damage_applicable')) is not bool:
        errors.append('MISSING_MEAN_EQUIPPED_HIT_CAUSALITY')
    elif e['mean_weapon_hit_damage_applicable'] and not (type(weights.get('mean_weapon_hit_damage')) in (int,float)
            and weights['mean_weapon_hit_damage']>0):
        errors.append('CAUSAL_EQUIPPED_MEAN_HIT_WEIGHT_NOT_POSITIVE')
    slots=e.get('slot_tests')
    if not isinstance(slots,list) or type(e.get('legal_equipment_slots')) is not int or len(slots)!=e['legal_equipment_slots']:
        errors.append('MISSING_PER_SLOT_ILVL_TOP5_TEST_RECORDS')
        return errors
    used=set()
    for slot in slots:
        if not isinstance(slot,dict) or not isinstance(slot.get('slot'),str):
            errors.append('INVALID_SLOT_TEST_ROW')
            continue
        name=slot['slot']
        if name in used:errors.append('DUPLICATE_TEST_SLOT:'+name)
        used.add(name)
        n=slot.get('source_legal_item_count')
        items=slot.get('items')
        if type(n) is not int or n<0 or not isinstance(items,list) or len(items)!=min(5,n):
            errors.append('TOP5_ILVL_ITEM_COUNT_MISMATCH:'+name)
            continue
        if slot.get('selected_from_db_by_ilvl') is not True:
            errors.append('TOP5_NOT_SELECTED_BY_ILVL:'+name)
        last=float('inf')
        seen=set()
        for item in items:
            if not isinstance(item,dict):
                errors.append('INVALID_TEST_ITEM:'+name);continue
            ident=item.get('item_id')
            if ident is None or ident in seen:
                errors.append('DUPLICATE_OR_MISSING_ITEM:'+name)
            seen.add(ident)
            ilvl=item.get('ilvl');score=item.get('score')
            if type(ilvl) not in (int,float) or not math.isfinite(ilvl) or ilvl>last:
                errors.append('NOT_TOP5_ILVL_DESCENDING:'+name)
            elif type(ilvl) in (int,float):
                last=ilvl
            if item.get('source_legal') is not True:
                errors.append('ILLEGAL_GEAR_ITEM:'+name+':'+str(ident))
            if type(score) not in (int,float) or not math.isfinite(score):
                errors.append('NONFINITE_GEAR_ITEM_SCORE:'+name+':'+str(ident))
            contrib=item.get('stat_contributions')
            if not isinstance(contrib,dict):
                errors.append('MISSING_ITEM_STAT_CONTRIBUTIONS:'+name+':'+str(ident))
            elif any(type(v) not in (int,float) or not math.isfinite(v) for v in contrib.values()):
                errors.append('INVALID_ITEM_STAT_CONTRIBUTIONS:'+name+':'+str(ident))
            if item.get('ordinary_stat_fields') and not any(abs(v)>1e-12 for v in (contrib or {}).values()
                if type(v) in (int,float)):
                errors.append('ITEM_ORDINARY_STATS_IGNORED:'+name+':'+str(ident))
    return errors

def _validate_search(e: dict, seconds: int) -> list[str]:
    errors: list[str] = []
    _fail_if(errors, not _positive(e.get("search_wall_s")) or e["search_wall_s"] > seconds + 1.0,
             f"SEARCH_BUDGET_NOT_MET:{seconds}s")
    _fail_if(errors, not _positive(e.get("unique_full_builds")), "NO_UNIQUE_FULL_BUILDS")
    _fail_if(errors, not _positive(e.get("complete_100mob_replays")), "NO_COMPLETED_100MOB_REPLAY")
    _fail_if(errors, not _positive(e.get("best_full_s_per_mob")), "NO_VALID_100MOB_SCORE")
    _require_true(e, errors, "unlock_coverage_pass")
    if isinstance(e.get('uncovered_unlock_families'), list) and e['uncovered_unlock_families']:
        errors.append('SOURCE_UNLOCK_UNEXECUTED:'+','.join(map(str,e['uncovered_unlock_families'][:8])))
    if e.get('independent_replay_outside_budget') is False:
        errors.append('100MOB_NOT_INDEPENDENT_OUTSIDE_PAID_SEARCH')
    _require_true(e, errors, "talent_gear_apl_jointly_searched")
    _require_true(e, errors, "full_legal_builds")
    _fail_if(errors, e.get("mob_count") != 100, "MOB_COUNT_NOT_100")
    return errors


def _validate_p4(e: dict, _: dict) -> list[str]:
    return _validate_search(e, 30)


def _validate_p5(e: dict, previous: dict) -> list[str]:
    errors = _validate_search(e, 300)
    p4 = previous.get("P4")
    if not p4 or p4.get("status") != "PASS":
        errors.append("P4_NOT_PASS")
        return errors
    a = e.get("unique_full_builds")
    b = p4["evidence"].get("unique_full_builds")
    # PROCESS v2.17 / docs/gates/P4-P6.md require actual doubled paid
    # breadth. A caller-supplied finite-space flag is not an approved waiver.
    if not _positive(a) or not _positive(b) or a < 2 * b:
        errors.append(f"INSUFFICIENT_SEARCH_BREADTH:P5={a},P4={b},required>=2x")
    return errors


def _validate_p6(e: dict, previous: dict) -> list[str]:
    errors: list[str] = []
    for gate in ("P4", "P5"):
        if previous.get(gate, {}).get("status") != "PASS":
            errors.append(f"{gate}_NOT_PASS")
    p4 = previous.get("P4", {}).get("evidence", {})
    p5 = previous.get("P5", {}).get("evidence", {})
    s30 = e.get("s_per_mob_30")
    s300 = e.get("s_per_mob_300")
    if not _positive(s30) or not _positive(s300):
        errors.append("INVALID_30_300_100MOB_TIMES")
    elif s30 > 1.01 * s300 + 1e-9:
        errors.append(f"P6_RATIO_EXCEEDS_1_PERCENT:{s30 / s300:.8f}")
    _require_true(e, errors, "independent_replays_same_scenario")
    for n, source in (("30", p4), ("300", p5)):
        if source and _positive(source.get("best_full_s_per_mob")) and _positive(e.get(f"s_per_mob_{n}")):
            if not math.isclose(e[f"s_per_mob_{n}"], source["best_full_s_per_mob"], rel_tol=1e-6):
                errors.append(f"{n}_REPLAY_MISMATCH_WITH_SEARCH")
    return errors


def _validate_p7(e: dict, _: dict) -> list[str]:
    errors: list[str] = []
    _require_true(e, errors, "legacy_winner_full_configuration_replayed_in_new_engine")
    _require_true(e, errors, "both_configurations_same_100mob_scenario")
    old = e.get("legacy_winner_on_new_engine_s_per_mob")
    new = e.get("new_winner_on_new_engine_s_per_mob")
    if not _positive(old) or not _positive(new):
        errors.append("MISSING_COMPARABLE_FULL_REPLAYS")
    elif new > old + 1e-9:
        errors.append(f"NEW_WINNER_SLOWER_THAN_LEGACY:new={new},legacy={old}")
    return errors


# P1 and P2 are retired; historical evidence is not a live validator.
VALIDATORS = {"P3": _validate_p3,
              "P4": _validate_p4, "P5": _validate_p5, "P6": _validate_p6,
              "P7": _validate_p7}


# Legacy JSON schema checker retained for diagnostics and old regression tests.
# NEVER call evaluate() from the public acceptance CLI: evidence is not execution.
def evaluate(evidence_dir: Path, class_key: str, level: int, spec: str, gate: str,
             previous: dict) -> dict:
    filename = evidence_dir / class_key / f"L{level}" / spec / f"{gate}.json"
    result = {"class": class_key, "level": level, "spec": spec, "gate": gate,
              "status": "FAIL", "reasons": [], "evidence_file": str(filename)}
    if gate not in VALIDATORS:
        result["reasons"] = ["RETIRED_OR_UNKNOWN_GATE:" + gate]
        return result
    if not filename.is_file():
        result["reasons"] = ["EVIDENCE_NOT_FOUND"]
        return result
    try:
        e = json.loads(filename.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result["reasons"] = [f"INVALID_JSON:{type(exc).__name__}"]
        return result
    if not isinstance(e, dict):
        result["reasons"] = ["INVALID_EVIDENCE_NOT_OBJECT"]
        return result
    mismatches = [k for k, expected in (("class", class_key), ("level", level),
                  ("spec", spec), ("gate", gate)) if e.get(k) != expected]
    if mismatches:
        result["reasons"] = ["CHECKPOINT_IDENTITY_MISMATCH:" + ",".join(mismatches)]
        return result
    errors = VALIDATORS[gate](e, previous)
    # Source/engine provenance comes from the same generated evidence as results.
    if not e.get("source_id") or not e.get("engine_id"):
        errors.append("MISSING_SOURCE_OR_ENGINE_ID")
    if gate in ("P4", "P5", "P6") and not e.get("scenario_id"):
        errors.append("MISSING_SCENARIO_ID")
    if gate in ("P5", "P6"):
        for preceding in ("P4", "P5") if gate == "P6" else ("P4",):
            prior = previous.get(preceding, {}).get("evidence", {})
            if prior and any(e.get(x) != prior.get(x) for x in ("source_id", "engine_id", "scenario_id")):
                errors.append(f"INCOMPARABLE_WITH_{preceding}_SOURCE_ENGINE_SCENARIO")
    result["reasons"] = errors
    result["status"] = "PASS" if not errors else "FAIL"
    result["evidence"] = e
    return result


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
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "gate_evidence",
                        help="Legacy compatibility only; never read for acceptance")
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
                    "source_context_sha256", "real_source_search_evaluated",
                    "real_catalogue_top5_items_scored",
                    "source_report_url", "source_request_raw_sha256",
                    "native_source_revision", "iterations",
                    "sampled_source_fights", "saved_source_iterations",
                    "native_first_duration_s", "world_first_duration_s",
                    "source_replay_Tfirst_Tsecond", "source_replay_numeric_saturation",
                    "joint_cold_world_dps", "external_reference_only_floor",
                    "final_required_dps", "source_legal_joint_candidates_paid",
                    "cold_winner_request_sha256",
                    "selected_balanced_request_sha256",
                    "cold_candidate_failures"):
            if key in report:
                record[key] = report[key]
        if gate == "P3":
            # Preserve the measured source-policy witness and weight vector so
            # a first-contact P3 failure can be repaired from its actual cause.
            # These are bounded diagnostics only; they never alter PASS/M1.
            witnesses = report.get("source_policy_stat_witnesses")
            if isinstance(witnesses, list):
                record["source_policy_stat_witnesses"] = witnesses[:8]
            weights = report.get("real_measured_stat_weights")
            if isinstance(weights, dict):
                record["real_measured_stat_weights"] = {
                    str(axis): float(value)
                    for axis, value in list(weights.items())[:32]
                    if type(value) in (int, float) and math.isfinite(value)
                }
            for key in ("real_catalogue_legal_items", "real_catalogue_slots_scored",
                        "actual_search_result_status"):
                value = report.get(key)
                if type(value) is int or isinstance(value, str):
                    record[key] = value
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
                        "paid_balanced_finalists",
                        "paid_balanced_confirmed",
                        "paid_balanced_deep_confirmed",
                        "balanced_finalist_failure_count",
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
            # Actual rejected paid proposals and finalist reevaluations are
            # necessary to distinguish a quality regression from a failed
            # search invocation. Bound the receipt; it is not M1 evidence.
            for key in ("source_candidate_failures", "paid_stochastic_finalist_failures"):
                errors = report.get(key)
                if isinstance(errors, list):
                    record[key] = [error[:180] for error in errors[:4]
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
