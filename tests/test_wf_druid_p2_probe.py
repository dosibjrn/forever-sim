"""Source P2 derivation, fatal source corruption, level and test-ledger coverage."""
import copy
import importlib.util
from hashlib import sha256
import json
from pathlib import Path

from tools import m1_progress as m1

ROOT=Path(__file__).resolve().parents[1]
S=ROOT/'tools/wf_druid_p2_probe.py'
spec=importlib.util.spec_from_file_location('druid_p2',S)
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
S2=ROOT/'tools/wf_gate.py'
spec2=importlib.util.spec_from_file_location('wf_gate',S2)
gate=importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(gate)
S3=ROOT/'tools/wf_gate_coverage.py'
spec3=importlib.util.spec_from_file_location('gate_coverage',S3)
coverage=importlib.util.module_from_spec(spec3)
spec3.loader.exec_module(coverage)
R=json.loads((ROOT/'gate_sources/druid/WF443_P2_GATE_RED.json').read_text())
C=(ROOT/'gate_sources/druid/WF443_SOURCE_CATALOGUE.json').read_text().strip()


def test_l20_recompute_91_budget_reachable_and_no_fake_level20_execution():
    x=probe.source_report(20,R,C)
    assert x['source_rank_total']==148
    assert (x['structurally_reachable_ranks'],x['source_budget_unreachable_ranks'],x['source_unresolved_ranks'])==(91,57,0)
    assert x['talent_points']==16 and x['ranks_with_executor_paths']==0
    assert x['ranks_with_executed_behavior_tests']==0
    assert len(x['reachable_rank_keys'])==91 and len(set(x['reachable_rank_keys']))==91
    errors=gate._validate_p2(x,{})
    assert 'LEVEL_SPECIFIC_EXECUTOR_TESTS_MISSING:91' in errors
    assert any(z.startswith('UNTESTED_REACHABLE_RANKS:91') for z in errors)


def test_l30_all_129_have_ir_execution_but_missing_129_behavior_tests():
    x=probe.source_report(30,R,C)
    assert (x['structurally_reachable_ranks'],x['source_budget_unreachable_ranks'],x['source_unresolved_ranks'])==(129,19,0)
    assert x['source_l30_ir_applied_ranks']==x['ranks_with_executor_paths']==129
    assert all(y['source_l30_ir_applied'] for y in x['reachable_ranks'])
    assert 'UNTESTED_REACHABLE_RANKS:129' in ' '.join(gate._validate_p2(x,{}))


def test_source_digest_mismatch_is_not_a_pass():
    corrupted=copy.deepcopy(R);corrupted['source_sha256']='0'*64
    import pytest
    with pytest.raises(ValueError, match='PINNED_SOURCE_SHA256_MISMATCH'):
        probe.source_report(20,corrupted,C)


def test_missing_rank_is_fatal():
    corrupted=copy.deepcopy(R)
    corrupted['structural_witnesses'].pop()
    import pytest
    with pytest.raises(ValueError, match='SOURCE_MISSING_RANKS'):
        probe.source_report(30,corrupted,C)


def test_per_rank_test_ledger_rejects_count_only_and_duplicates():
    x=probe.source_report(20,R,C)
    x['ranks_with_executed_behavior_tests']=91
    errors=gate._validate_p2(x,{})
    assert 'BEHAVIOR_COUNT_MISMATCH_WITH_LEDGER' in errors
    assert any(z.startswith('UNTESTED_REACHABLE_RANKS') for z in errors)
    x['rank_behavior_results']=[{'rank_key':x['reachable_rank_keys'][0],
                                  'test_id':'pytest::rank_witness',
                                  'passed':True,'actually_executed':True}]*2
    errors=gate._validate_p2(x,{})
    assert any('INVALID_OR_FAILED_RANK_TEST' in z for z in errors)


def test_legacy_semantic_labels_do_not_cause_fail():
    x=probe.source_report(30,R,C)
    assert sum(bool(y['historical_semantic_labels']) for y in x['reachable_ranks']) >= 14
    # All non-semantic blockers are filled with executed per-rank test rows,
    # and then old labels cannot break the pass.
    x['rank_behavior_results']=[{'rank_key':k,'test_id':'test::'+k,
                                  'passed':True,'actually_executed':True}
                                 for k in x['reachable_rank_keys']]
    x['ranks_with_executed_behavior_tests']=129
    x['source_specific_behavior_tests_executed']=True
    x['ranks_represented_in_search']=129
    x['unlocked_actions_available_to_generated_search']=True
    x['provenance_scope']='CURRENT_EXECUTED_COMBAT_TESTS'
    x['production_engine']='msim'
    assert gate._validate_p2(x,{})==[]


def test_p2_requires_an_approved_production_backend():
    x=probe.source_report(30,R,C)
    x['rank_behavior_results']=[{'rank_key':k,'test_id':'test::'+k,
                                  'passed':True,'actually_executed':True}
                                 for k in x['reachable_rank_keys']]
    x['ranks_with_executed_behavior_tests']=129
    x['ranks_with_executor_paths']=129
    x['missing_executor_ranks']=0
    x['failed_behavior_ranks']=0
    x['talent_paths_legal']=True
    x['ranks_represented_in_search']=129
    x['unlocked_actions_available_to_generated_search']=True
    x['source_specific_behavior_tests_executed']=True
    x['provenance_scope']='CURRENT_EXECUTED_COMBAT_TESTS'
    assert 'UNAPPROVED_P2_PRODUCTION_ENGINE:missing' in gate._validate_p2(x,{})
    x['production_engine']='live_game_ir_compiler_and_runtime'
    assert ('UNAPPROVED_P2_PRODUCTION_ENGINE:live_game_ir_compiler_and_runtime'
            in gate._validate_p2(x,{}))
    x['production_engine']='msim'
    assert gate._validate_p2(x,{})==[]


def test_retired_p2_diagnostic_cannot_be_recorded_in_m1(tmp_path):
    report={'status':'FAIL','gate':'P2',
            'coverage_basis':'executed_behavior_or_checked_solo_exclusion',
            'pass_count':3,'reachability_count':10,
            'behavior_probes_executed':3,
            'production_engine':'live_game_ir_compiler_and_runtime'}
    assert coverage.measured_live_coverage(report) is None
    report['production_engine']='msim'
    # Diagnostic coverage may be computed, but the M1 recorder rejects P2.
    assert coverage.measured_live_coverage(report)['verified'] == 3
    assert 'P2' not in m1.GATES
    assert m1.record_partial(class_key='druid', level=60, spec='balance',
                             gate='P2', report=report, path=tmp_path/'m1.tsv') is False


def _native_p2_diagnostic_report():
    probe_row = {
        "rank_key": "moonkin_form:1",
        "target_talent_id": "moonkin_form",
        "target_rank": 1,
        "status": "PROBE_PASS",
        "executor": "selected_mythicsim_rust",
        "accepted_for_p2": False,
        "rng_mode": "balanced",
        "iterations": 100,
        "engine_identity": "a" * 40,
        "scenario": "balance",
        "source_layout_sha256": "b" * 64,
        "delta_dps": 2.0,
        "before": {
            "prepared": {"status": "PREPARED", "prepared_sha256": "before"},
            "simulation": {"status": "EXECUTED", "dps": 100.0},
        },
        "after": {
            "prepared": {"status": "PREPARED", "prepared_sha256": "after"},
            "simulation": {"status": "EXECUTED", "dps": 102.0},
        },
    }
    return {
        "production_engine": "live_game_ir_compiler_and_runtime",
        "structurally_reachable_ranks": 1,
        "ranks_with_executed_behavior_tests": 0,
        "ranks_with_executor_paths": 0,
        "missing_executor_ranks": 1,
        "failed_behavior_ranks": 1,
        "talent_paths_legal": False,
        "ranks_represented_in_search": 0,
        "unlocked_actions_available_to_generated_search": False,
        "native_rank_probe_scope": "DIAGNOSTIC_ONLY_NOT_COUNTED_IN_P2_ACCEPTANCE",
        "native_rank_probe_results": [probe_row],
        "native_rank_probe_summary": {
            "scope": "druid:60:balance; moonkin_form:1",
            "attempted": 1,
            "pass_count": 1,
            "fail_count": 0,
            "blocked_count": 0,
            "invalid_count": 0,
            "unsupported_count": 0,
            "error_count": 0,
            "rng_mode": "balanced",
            "counted_in_p2_acceptance": False,
        },
    }


def test_p2_validator_keeps_native_rank_probes_diagnostic_only():
    errors = gate._validate_p2(_native_p2_diagnostic_report(), {})
    # A positive native probe is visible and schema-checked, but it cannot
    # replace the complete per-rank P2 ledger or approve the GameIR provider.
    assert "UNAPPROVED_P2_PRODUCTION_ENGINE:live_game_ir_compiler_and_runtime" in errors
    assert "INCOMPLETE:ranks_with_executed_behavior_tests=0/1" in errors
    assert not any(error.startswith("INVALID_NATIVE_P2") for error in errors)
    assert not any(error.startswith("INCOMPLETE_NATIVE_P2") for error in errors)


def test_p2_validator_preserves_native_terminal_refusal_categories():
    cases = (
        ("INVALID", "invalid_count"),
        ("UNSUPPORTED", "unsupported_count"),
        ("ERROR", "error_count"),
    )
    for status, count_field in cases:
        report = _native_p2_diagnostic_report()
        row = report["native_rank_probe_results"][0]
        row.update(
            status=status,
            reason="native-owned terminal result",
            before={"status": status},
            after={"status": "PREPARED"},
        )
        summary = report["native_rank_probe_summary"]
        summary["pass_count"] = 0
        summary[count_field] = 1
        errors = gate._validate_p2(report, {})
        assert not any(error.startswith("INVALID_NATIVE_P2") for error in errors)
        assert not any(error.startswith("INCOMPLETE_NATIVE_P2") for error in errors)
        assert "NATIVE_P2_DIAGNOSTIC_SUMMARY_NOT_FAIL_CLOSED" not in errors


def test_p2_validator_rejects_native_probe_receipts_that_claim_acceptance():
    report = _native_p2_diagnostic_report()
    report["native_rank_probe_results"][0]["accepted_for_p2"] = True
    report["native_rank_probe_summary"]["counted_in_p2_acceptance"] = True
    errors = gate._validate_p2(report, {})
    assert "NATIVE_P2_DIAGNOSTIC_ACCEPTANCE_CLAIMED:moonkin_form:1" in errors
    assert "NATIVE_P2_DIAGNOSTIC_SUMMARY_NOT_FAIL_CLOSED" in errors

