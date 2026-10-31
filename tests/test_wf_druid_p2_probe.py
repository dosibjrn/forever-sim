"""Source P2 derivation, fatal source corruption, level and test-ledger coverage."""
import copy
import importlib.util
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
S=ROOT/'tools/wf_druid_p2_probe.py'
spec=importlib.util.spec_from_file_location('druid_p2',S)
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
S2=ROOT/'tools/wf_gate.py'
spec2=importlib.util.spec_from_file_location('wf_gate',S2)
gate=importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(gate)
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
    assert gate._validate_p2(x,{})==[]
