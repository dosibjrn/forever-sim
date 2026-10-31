#!/usr/bin/env python3
"""Class/level/spec-specific P1-P7 acceptance gates for WoW Forever.

Runtime-first acceptance: execute the source-backed gate implementation.
Evidence JSON is OUTPUT ONLY, never an input authority to award PASS. Missing
executable gate implementations are BLOCKED (exit nonzero), even if a historical
JSON claims PASS.

Example:
    python tools/wf_gate.py --class druid --level 20 --gate P2
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

GATES = tuple(f"P{i}" for i in range(1, 7)) + tuple(f"P7.{i}" for i in range(1, 6))
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


def _validate_p1(e: dict, _: dict) -> list[str]:
    errors: list[str] = []
    _count_at_least(e, errors, "executed_ability_behavior_tests", "legal_abilities")
    _require_zero(e, errors, "missing_executors")
    _require_zero(e, errors, "failed_behavior_tests")
    _require_true(e, errors, "source_legal_abilities_checked")
    return errors


def _validate_p2(e: dict, _: dict) -> list[str]:
    errors: list[str] = []
    _count_at_least(e, errors, "ranks_with_executed_behavior_tests", "structurally_reachable_ranks")
    _count_at_least(e, errors, "ranks_with_executor_paths", "structurally_reachable_ranks")
    _require_zero(e, errors, "missing_executor_ranks")
    _require_zero(e, errors, "failed_behavior_ranks")
    _require_true(e, errors, "talent_paths_legal")
    _count_at_least(e, errors, "ranks_represented_in_search", "structurally_reachable_ranks")
    _require_true(e, errors, "unlocked_actions_available_to_generated_search")
    # A per-rank *executed test ledger* prevents a single "129 tests passed"
    # summary from posing as 129 verified behaviors.  Test ids must identify
    # actual executed test nodes, not merely a modifier-compilation receipt.
    rank_keys = e.get("reachable_rank_keys")
    behavior = e.get("rank_behavior_results")
    if rank_keys is not None or behavior is not None:
        if not isinstance(rank_keys, list) or not rank_keys or len(rank_keys) != len(set(rank_keys)):
            errors.append("INVALID_REACHABLE_RANK_KEYS")
        if not isinstance(behavior, list):
            errors.append("MISSING_PER_RANK_EXECUTED_TEST_LEDGER")
        else:
            covered: set[str] = set()
            for row in behavior:
                if not isinstance(row, dict):
                    errors.append("INVALID_RANK_BEHAVIOR_TEST_ENTRY")
                    continue
                k = row.get("rank_key")
                if (not isinstance(k, str) or not k or k in covered
                        or not isinstance(row.get("test_id"), str) or not row["test_id"]
                        or row.get("passed") is not True or row.get("actually_executed") is not True):
                    errors.append("INVALID_OR_FAILED_RANK_TEST:" + str(k))
                else:
                    covered.add(k)
            if isinstance(rank_keys, list):
                missing = sorted(set(rank_keys) - covered)
                unexpected = sorted(covered - set(rank_keys))
                if missing:
                    errors.append(f"UNTESTED_REACHABLE_RANKS:{len(missing)}:first={','.join(missing[:5])}")
                if unexpected:
                    errors.append(f"NONREACHABLE_RANK_TEST_IDS:{len(unexpected)}")
                if _require_count(e, errors, 'ranks_with_executed_behavior_tests') != len(covered):
                    errors.append("BEHAVIOR_COUNT_MISMATCH_WITH_LEDGER")
    if e.get("source_specific_behavior_tests_executed") is False:
        errors.append("NO_CURRENT_REAL_RUNTIME_BEHAVIOR_TESTS")
    if e.get('provenance_scope','').startswith('HISTORICAL_WF443'):
        errors.append('HISTORICAL_IR_SNAPSHOT_NOT_CURRENT_RUNTIME_P2_EVIDENCE')
    unverified=e.get("missing_current_level_runtime_executor_verification", 0)
    if type(unverified) is int and unverified > 0:
        errors.append(f"LEVEL_SPECIFIC_EXECUTOR_TESTS_MISSING:{unverified}")
    unresolved=e.get("source_unresolved_ranks",0)
    if type(unresolved) is int and unresolved > 0:
        errors.append(f"SOURCE_RANK_REACHABILITY_UNRESOLVED:{unresolved}")
    # Deliberately no old semantic_verification_label criterion.
    return errors


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
    exhausted = e.get("full_legal_space_exhausted") is True
    if not exhausted and (not _positive(a) or not _positive(b) or a < 10 * b):
        errors.append(f"INSUFFICIENT_SEARCH_BREADTH:P5={a},P4={b},required>=10x")
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


VALIDATORS = {"P1": _validate_p1, "P2": _validate_p2, "P3": _validate_p3,
              "P4": _validate_p4, "P5": _validate_p5, "P6": _validate_p6,
              "P7": _validate_p7}


# Legacy JSON schema checker retained for diagnostics and old regression tests.
# NEVER call evaluate() from the public acceptance CLI: evidence is not execution.
def evaluate(evidence_dir: Path, class_key: str, level: int, spec: str, gate: str,
             previous: dict) -> dict:
    filename = evidence_dir / class_key / f"L{level}" / spec / f"{gate}.json"
    result = {"class": class_key, "level": level, "spec": spec, "gate": gate,
              "status": "FAIL", "reasons": [], "evidence_file": str(filename)}
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
    if gate in ('P4','P5','P6') and e.get('evidence_kind') == 'WF463_SOURCE_SEARCH_REPLAY':
        try:
            from wf_gate_engine_fingerprint import runtime_fingerprint
            current_id=runtime_fingerprint(ROOT)
            if current_id != e.get('engine_id'):
                errors.append('SEARCH_ENGINE_STALE_SINCE_EVIDENCE_RECORDED')
            source_db=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
            import hashlib
            if not source_db.is_file() or hashlib.sha256(source_db.read_bytes()).hexdigest()!=e.get('source_id'):
                errors.append('SEARCH_DB_STALE_OR_MISSING_SINCE_EVIDENCE_RECORDED')
        except (OSError,ImportError) as exc:
            errors.append('CANNOT_REVERIFY_CURRENT_RUNTIME_CODE:'+type(exc).__name__)
    result["reasons"] = errors
    result["status"] = "PASS" if not errors else "FAIL"
    result["evidence"] = e
    return result


def _run_live_gate(root: Path, class_key: str, level: int, spec: str,
                   gate: str, scenario_id: str) -> dict:
    """Execute a real gate provider. Never award PASS from persisted JSON."""
    if gate == "P1":
        from tools.wf_gate_p1_live import run_live
        kwargs = {"spec": spec, "scenario_id": scenario_id}
    elif gate == "P2":
        from tools.wf_gate_p2_live import run_live
        kwargs = {"spec": spec}
    else:
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
        kwargs = {"spec": spec}
    try:
        report = run_live(root, class_key, level, **kwargs)
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
    # P3–P7 gate providers must identify a real executed engine and its run.
    # These are necessary metadata, NOT a substitute for testing real behavior.
    if gate not in ("P1", "P2") and report["status"] == "PASS":
        proof = report.get("runtime_proof")
        if not isinstance(proof, dict) or proof.get("executed") is not True or any(
                not isinstance(proof.get(k), str) or not proof[k]
                for k in ("engine_revision", "source_revision", "run_id")):
            return {"status": "FAIL", "reasons": [
                "MISSING_EXECUTED_RUNTIME_PROOF"]}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute live source-backed WoW Forever P1–P7.5 gates")
    parser.add_argument("--class", dest="class_key", required=True)
    parser.add_argument("--level", type=int, required=True)
    parser.add_argument("--spec", default="unrestricted")
    parser.add_argument("--gate", choices=(*GATES, "P7", "all"), required=True)
    parser.add_argument("--p1-scenario", default="current_solo_leveling_100mob_v1")
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "gate_evidence",
                        help="Legacy compatibility only; never read for acceptance")
    parser.add_argument("--refresh-p2-source-audit", action="store_true",
                        help="Historical source diagnostics, not live acceptance")
    parser.add_argument("--out", type=Path,
                        help="Write the freshly executed results and provenance")
    a = parser.parse_args(argv)
    for name, value in (("class", a.class_key), ("spec", a.spec)):
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
            parser.error(f"--{name} requires a lower-case source key")
    if not 1 <= a.level <= 60:
        parser.error("--level must be within 1..60")
    if a.refresh_p2_source_audit:
        parser.error("Source-audit refresh must use its dedicated tool; "
                     "this CLI never consumes or regenerates acceptance inputs")
    if a.gate in ("P1", "all"):
        from datetime import date
        from os import environ
        if not environ.get("WOW_FOREVER_BUILD_AS_OF"):
            environ["WOW_FOREVER_BUILD_AS_OF"] = date.today().isoformat()
            environ["WOW_FOREVER_BUILD_SOURCE"] = "p1_live_current_date"
    targets = (GATES if a.gate == "all" else
               tuple(f"P7.{n}" for n in range(1, 6)) if a.gate == "P7"
               else (a.gate,))
    results = []
    for gate in targets:
        report = _run_live_gate(ROOT, a.class_key, a.level, a.spec,
                                gate, a.p1_scenario)
        record = {"gate": gate, "status": report["status"],
                  "reasons": report.get("reasons", [])}
        for key in ("reachability_count", "pass_count", "unresolved_count",
                    "behavior_probes_executed", "runtime_proof"):
            if key in report:
                record[key] = report[key]
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
