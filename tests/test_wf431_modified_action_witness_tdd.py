"""WF431 RED: source-modified actions must be exercised by paid cold search."""
from pathlib import Path
from dataclasses import replace
from time import perf_counter

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.v2.source_bounded_joint_frontier import (
    bounded_full_point_talent_frontier, source_cold_start_stage,
    source_joint_policy_frontier, _source_talent_policy_variants,
    _prepare_joint_policy_candidate, isolated_joint_evaluation,
    search_bounded_joint_frontier,
)

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'

@pytest.fixture(scope='module')
def setup():
    ir,_=compile_talent_runtime(build_game_ir_slice(
        class_key='druid',level=30,ability_db_path=DB))
    stage=source_cold_start_stage(class_key='druid',level=30,
        source_ir=ir,gear_role='druid_feral')
    talents,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=64)
    policies=source_joint_policy_frontier(ir,stage,max_policies=3,
        include_mode_cycles=True)
    variants,_,blockers=_source_talent_policy_variants(ir,talents,stage,
        policies,level=30,bonus_talent_points=5)
    return ir,stage,talents,variants,blockers


def _starfire_witness(setup):
    ir,stage,talents,variants,blockers=setup
    index=next(i for i,a in enumerate(talents) if a.get('improved_starfire')==5)
    options=variants[index]
    label,policy=next((label,p) for label,p in options
        if label.startswith('talent_modified:improved_starfire:'))
    action=next(a for a in ir.actions if a.family_key=='starfire')
    assert any(rule.action_id==action.id for rule in policy.rules)
    assert options[0][0]==label, 'Source-modified APL must be early, not buried after generic scratch'
    return index,label,policy


def test_compound_source_modified_action_has_independent_cold_policy(setup):
    _starfire_witness(setup)


def test_modified_action_witness_executes_in_real_paid_4_and_100_mobs(setup):
    ir,stage,talents,variants,_=setup
    index,label,policy=_starfire_witness(setup)
    candidate=_prepare_joint_policy_candidate(class_key='druid',level=30,
        stage=stage,allocation=talents[index],source_ir=ir,
        allow_partial_gear_stats=True,policy_label=label,policy=policy,
        bonus_talent_points=5)
    assert candidate.opening==(), 'Old caster or form opening must not hide new witness'
    action=next(a for a in candidate.ir.actions if a.family_key=='starfire')
    assert action.cast_time_s==pytest.approx(3.0)
    for mobs in (4,100):
        result=isolated_joint_evaluation(candidate,level=30,mobs=mobs,
            timeout_s=20.,pack_size=1)
        assert result['status']=='COMPLETE',result
        assert result['mean_s_per_mob']>0
        assert result['source_action_counts'].get(action.id,0)>=mobs


def test_30s_cold_search_actually_pays_for_modified_source_action(setup):
    ir,stage,talents,variants,_=setup
    index,label,policy=_starfire_witness(setup)
    t0=perf_counter()
    result=search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,bonus_talent_points=5,
        max_talents=64,max_gear_moves=2,max_policies=3,
        max_recovery_policies=2,max_paid_builds=120,max_cpu_s=30.,
        per_candidate_wall_s=5.,screen_then_finalists=True,
        max_finalists=3,screen_mobs=4,finalist_mobs=100,
        proposal_strategy='diagonal')
    assert perf_counter()-t0<35
    rows=[r for r in result['rows'] if r['allocation'].get('improved_starfire')==5
          and r['policy_origin']==label]
    assert rows, 'Starfire5 source witness was starved by the Cartesian search'
    action_id=label.split(':',2)[2]  # canonical source action ID, not a family-name string
    assert any(r['screen_status']=='COMPLETE' and
        r['source_action_counts'].get(action_id,0)>0
        for r in rows),rows


def test_modified_witness_does_not_starve_paid_source_action_unlock():
    """A tight paid budget must still execute a source-granted action."""
    import json
    from src.game.data.forever.source_db_scope import ability_source_scope
    root=Path(__file__).resolve().parents[1]
    stage=json.loads((root/'evidence/wf360/WF360_L30_P4_30S.json').read_text())['winner_stage']
    with ability_source_scope(DB):
        ir,_=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30))
        result=search_bounded_joint_frontier(class_key='druid',level=30,
            source_ir=ir,seed_stage=stage,max_talents=4,max_gear_moves=0,
            max_policies=2,max_recovery_policies=1,max_paid_builds=2,
            max_cpu_s=6.,per_candidate_wall_s=2.,screen_mobs=4,
            finalist_mobs=100,screen_then_finalists=True,max_finalists=1,
            proposal_strategy='diagonal',allow_partial_gear_stats=True)
    rows=[r for r in result['rows'] if r['policy_origin']=='talent_unlock:primal_bite:25']
    assert rows, 'Generic modified-action scheduling displaced a legal paid unlock'
    assert rows[0]['screen_status']=='COMPLETE',rows
    assert rows[0]['source_action_counts'].get('primal_bite:25',0)>0


def test_marginal_paid_anchor_scores_stay_bound_to_their_actual_coordinates():
    """Early source probes must not corrupt the 4-axis paid marginal ranking."""
    from types import SimpleNamespace
    from src.v2.source_bounded_joint_frontier import (
        _marginal_screen_coordinates, _source_witness_first_coordinates)
    dims=(4,2,3,2)
    weights=((0.,-5.,-1.,-3.),(0.,-.5),(0.,.1,.7),(0.,-4.))
    def paid_score(coords):
        return 30.+sum(weights[axis][i] for axis,i in enumerate(coords))
    anchor_count=1+sum(d-1 for d in dims)
    original_rows=[]
    original=_marginal_screen_coordinates(dims,original_rows)
    anchors=[]
    for _ in range(anchor_count):
        coords=next(original)
        anchors.append(coords)
        original_rows.append({'screen_status':'COMPLETE',
                              'screen_s_per_mob':paid_score(coords)})
    expected_cross=[c for c in original if c not in set(anchors)]
    dummy=SimpleNamespace(rules=())
    variants=[(('talent_modified:generic:'+str(i),dummy),) if i<3
              else (('incumbent',dummy),) for i in range(dims[0])]
    variants[1]=(('talent_modified:generic:1',dummy),
                 ('talent_unlock:source_action',SimpleNamespace(rules=(1,2,3))))
    actual_rows=[]
    actual=[]
    for coords in _source_witness_first_coordinates(dims,variants,
            'marginal_screen',actual_rows):
        actual.append(coords)
        actual_rows.append({'screen_status':'COMPLETE',
                            'screen_s_per_mob':paid_score(coords)})
    early_unlock=(1,0,1,0)
    actual_cross=[c for c in actual if c not in set(anchors) and c!=early_unlock]
    expected_cross=[c for c in expected_cross if c!=early_unlock]
    assert len(actual)==len(set(actual))==4*2*3*2
    assert actual_cross[:12]==expected_cross[:12],(
        'Marginal model used paid scores from wrong coordinates',
        actual_cross[:12],expected_cross[:12])
