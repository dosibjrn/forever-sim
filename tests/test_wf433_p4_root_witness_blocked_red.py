"""INTENTIONALLY RED: Root periodic/heartbeat semantics are not source-executable.

Do not turn these tests green by removing missing effect semantics or by
admitting an L1 partial proxy to a P4 certifying cold search.
"""
from tests.test_wf433_source_root_concurrency_tdd import _ir,_selected,_root,FILLER


def test_cold_64_frontier_reserves_legal_full_point_control_cap_witness():
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    from src.game.talents import validate_talent_selection
    ir=_ir()
    allocations,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=64)
    winners=[a for a in allocations if a.get('overgrowth')==2]
    assert winners
    assert any(sum(a.values())==26 for a in winners)
    for a in winners:
        validate_talent_selection(ir,a,level=30,bonus_talent_points=5)


def test_cold_search_generates_actual_source_control_cap_apl():
    from src.v2.source_bounded_joint_frontier import (
        _source_modified_action_policy_witnesses,source_cold_start_stage)
    ir=_ir()
    stage=source_cold_start_stage(class_key='druid',level=30,
        source_ir=ir,gear_role='druid_feral')
    allocation={**FILLER,'overgrowth':2,'ferocity':4}
    selected=_selected(2)
    witnesses=_source_modified_action_policy_witnesses(ir,selected,allocation,stage)
    assert witnesses
    assert any(label.startswith('talent_modified:overgrowth:') for label,_ in witnesses)
    root=_root(selected)
    assert any(any(rule.action_id==root.id and any(c.kind=='target_control_missing'
               and c.value=='root' for c in rule.conditions) for rule in policy.rules)
               and any(rule.action_id!=root.id for rule in policy.rules)
               for _,policy in witnesses)


def test_bounded_cold_search_pays_control_cap_witness_before_budget_expires():
    from src.v2.source_bounded_joint_frontier import (
        search_bounded_joint_frontier,source_cold_start_stage)
    ir=_ir()
    stage=source_cold_start_stage(class_key='druid',level=30,
        source_ir=ir,gear_role='druid_feral')
    result=search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,bonus_talent_points=5,
        max_talents=64,max_gear_moves=4,max_policies=4,
        max_recovery_policies=2,max_paid_builds=12,max_cpu_s=30.,
        per_candidate_wall_s=3.,screen_then_finalists=True,
        max_finalists=2,screen_mobs=4,finalist_mobs=100,
        proposal_strategy='diagonal')
    paid=[row for row in result['rows'] if row['allocation'].get('overgrowth')==2
          and row['policy_origin'].startswith('talent_modified:overgrowth:')]
    assert paid
    root_id=_root(_selected(2)).id
    assert any(row.get('screen_status')=='COMPLETE'
        and int(row.get('source_action_counts',{}).get(root_id,0))>0 for row in paid)
