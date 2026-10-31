"""WF414: source-ranked conditional melee damage is paid only versus existing bleed."""
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.talent_execution_coverage import compile_talent_runtime
from tests.test_wf409_talent_unlock_paid_witness_tdd import SOURCE


def _root():
    with ability_source_scope(SOURCE):
        return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30))[0]


def test_source_rank_1_to_5_conditional_bleed_modifier_compiles():
    ir=_root()
    talent=next(t for t in ir.talents if t.id=='rend_and_tear')
    assert talent.metadata['row']==5
    assert talent.prerequisite=={'talent_id':'predatory_strikes','required_rank':3}
    assert [round(r.modifiers[0].value,4) for r in talent.ranks]==[.02,.04,.06,.08,.10]
    assert all(r.modifiers[0].kind=='conditional_target_aura_damage_pct' for r in talent.ranks)


def test_rend_and_tear_reaches_real_ir_source_actions():
    ir=_root()
    # The legal 26-point allocation witness is asserted in the paid integration test.
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    allocations,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=256)
    found=[x for x in allocations if x.get('rend_and_tear')==1]
    assert found, '26-point legal Feral tree must contain a Rend and Tear candidate'
    changed,application=apply_talent_selection(ir,found[0],level=30,bonus_talent_points=5)
    assert application.spent_points==26
    claw=next(a for a in changed.actions if a.family_key=='claw')
    assert claw.metadata['conditional_target_aura_damage_multipliers']


def test_generated_conditional_policy_tracks_rake_bleed_and_claw_damage():
    from src.v2.source_bounded_joint_frontier import (
        bounded_full_point_talent_frontier, _source_conditional_aura_policy_witnesses)
    ir=_root()
    frontier,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=16)
    allocation=next(row for row in frontier if row.get('rend_and_tear')==1)
    selected,_=apply_talent_selection(ir,allocation,level=30,bonus_talent_points=5)
    witness=_source_conditional_aura_policy_witnesses(selected)
    assert len(witness)==1
    label,policy=witness[0]
    assert label.startswith('talent_condition:')
    assert len(policy.rules)>=2  # source mode transitions may precede damage rules
    assert any(c.kind=='aura_missing' and c.scope=='target' for c in policy.rules[-2].conditions)
    assert any(r.action_id.startswith('claw:') for r in policy.rules)


def test_paid_real_100mob_conditional_bleed_damage_and_no_bleed():
    from dataclasses import replace
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
    from tests.test_wf409_talent_unlock_paid_witness_tdd import _stage
    ir=_root()
    frontier,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=16)
    alloc=next(row for row in frontier if row.get('rend_and_tear')==1)
    with ability_source_scope(SOURCE):
        cand=prepare_candidate(class_key='druid',level=30,stage=_stage(),
            source_ir=ir,allocation_override=alloc,bonus_talent_points=5,
            allow_partial_gear_stats=True)
    policy=PolicyDefinition(id='source_rake_claw_probe', label='paid source bleed opener',
        rules=(PolicyRuleDefinition(id='claw',action_id='claw:28'),))
    cand=replace(cand,policy=policy,opening=('cat_form:768','rake:1822'))
    real=evaluate_persistent_candidate(cand,level=30,mobs=100,max_total_events=200000)
    assert real['status']=='COMPLETE',real
    assert real['source_action_counts']['rake:1822']==100
    assert real['source_action_counts']['claw:28']>=100
    assert real['mean_s_per_mob']>0


def test_persisted_bleed_target_activates_exactly_two_percent_melee_damage():
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    from src.game.runtime import ActorState,CombatRuntime,TargetState
    from src.game.policy import execute_priority_policy
    from src.v2.source_persistent_joint_finalists import prepare_candidate
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    from tests.test_wf409_talent_unlock_paid_witness_tdd import _stage
    ir=_root()
    frontier,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=16)
    allocation=next(row for row in frontier if row.get('rend_and_tear')==1)
    with ability_source_scope(SOURCE):
        candidate=prepare_candidate(class_key='druid',level=30,stage=_stage(),
            allocation_override=allocation,bonus_talent_points=5,
            source_ir=ir,allow_partial_gear_stats=True)
    policy=PolicyDefinition(id='sourced_melee',label='sourced melee',rules=(
        PolicyRuleDefinition(id='claw',action_id='claw:28'),))
    def execute(opening):
        actor=ActorState.from_ir(candidate.ir.actor,candidate.ir.resources,candidate.ir.modes)
        target=TargetState.with_health('same_target',1200)
        runtime=CombatRuntime(actor=actor,target=target,auto_attacks=candidate.ir.auto_attacks,
            incoming_attacks=candidate.ir.incoming_attacks,
            mitigation_rules=candidate.ir.mitigation_rules,triggers=candidate.ir.triggers)
        result=execute_priority_policy(policy=policy,actions=candidate.ir.actions,
            runtime=runtime,opening_action_ids=opening,max_actions=25)
        assert result.timeline.target_defeated,result.stopped_reason
        return [e for e in result.timeline.events
                if e.kind=='Damage' and e.action_id in ('claw:28','rake:1822')]
    bleeding=execute(('cat_form:768','rake:1822'))
    plain=execute(('cat_form:768',))
    b_claw=next(e for e in bleeding if e.action_id=='claw:28')
    n_claw=next(e for e in plain if e.action_id=='claw:28')
    assert abs(b_claw.payload['amount']/n_claw.payload['amount']-1.02)<1e-10
    assert b_claw.payload['conditional_aura_damage'][0]['active'] is True
    assert n_claw.payload['conditional_aura_damage'][0]['active'] is False
    rake_opener=next(e for e in bleeding if e.action_id=='rake:1822'
                     and not e.payload.get('periodic'))
    assert rake_opener.payload['conditional_aura_damage'][0]['active'] is False
    assert all(e.payload.get('conditional_aura_damage') is None for e in bleeding
               if e.action_id=='rake:1822' and e.payload.get('periodic'))


def test_rend_rank_is_illegal_at_21_points_and_valid_at_26():
    import pytest
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    ir=_root()
    frontier,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=16)
    allocation=next(row for row in frontier if row.get('rend_and_tear')==1)
    with pytest.raises(ValueError,match='budget'):
        apply_talent_selection(ir,allocation,level=30,bonus_talent_points=0)
    selected,paid=apply_talent_selection(ir,allocation,level=30,bonus_talent_points=5)
    assert paid.spent_points==paid.available_points==26
    assert any(a.metadata.get('conditional_target_aura_damage_multipliers')
               for a in selected.actions)
