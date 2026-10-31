"""RED: source-parametrized control damage break; Forever probability is unknown."""
from dataclasses import replace
import pytest
from src.game.model import (ActorDefinition,ResourceDefinition,ActionDefinition,
                            DamageEffect,ControlEffect,PolicyDefinition,PolicyRuleDefinition,PolicyCondition)
from src.game.runtime import ActorState,TargetState,CombatRuntime
from src.game.multi_pull import evaluate_repeated_pulls
from tests.test_wf433_source_root_concurrency_tdd import _selected,_root


def _synthetic(p):
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),
        (ResourceDefinition('health','Health','hero',initial_amount=500,capacity=500),),())
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('m0',1000.),
        other_targets=(TargetState.with_health('m1',1000.),),
        spatial_positions_yards={'m0':(0.,0.),'m1':(20.,0.)},
        enemy_move_speed_yards_s=5.,melee_radius_yards=5.)
    root=ActionDefinition('root','root','root','hero',requirements=(),costs=(),
        cast_time_s=0,gcd_s=0,cooldown_s=0,effects=(ControlEffect('control','root','enemy',12.,
        breaks_on_damage=False,break_chance_on_damage=p),),provenance=(),metadata={'range_yards':30.})
    damage=ActionDefinition('damage','damage','damage','hero',requirements=(),costs=(),
        cast_time_s=0,gcd_s=0,cooldown_s=0,effects=(DamageEffect('damage','nature','enemy',10.,10.),),provenance=(),metadata={'range_yards':30.})
    rt.engage_target('m1');rt.select_target('m1')
    rt.enqueue_action(root);rt.advance_to(0.)
    assert rt.targets['m1'].active_controls.get('root',0.)>0.
    rt.enqueue_action(damage);rt.advance_to(0.)
    return rt


@pytest.mark.parametrize('chance,expected_broken',[(0.,False),(1.,True)])
def test_generic_damage_break_probability_extremes_on_real_2d_target(chance,expected_broken):
    rt=_synthetic(chance)
    assert ('root' not in rt.targets['m1'].active_controls) is expected_broken
    dmg=[e for e in rt.trace if e.kind=='Damage']
    assert len(dmg)==1 and dmg[0].payload['amount']>0
    rolls=dmg[0].payload['control_break_rolls']
    assert rolls[0]['chance']==chance
    assert rolls[0]['broken'] is expected_broken
    assert 'root' not in rt.targets['m0'].active_controls


def test_generic_fractional_break_is_deterministic_and_source_parameterized():
    a=_synthetic(0.5);b=_synthetic(0.5)
    aa=[e.payload['control_break_rolls'] for e in a.trace if e.kind=='Damage']
    bb=[e.payload['control_break_rolls'] for e in b.trace if e.kind=='Damage']
    assert aa==bb
    assert len(aa)==1 and 0.<=aa[0][0]['roll']<1.
    assert aa[0][0]['chance']==0.5


def test_paid_2d_100mob_source_root_break_sensitivity_is_diagnostic_only():
    ir=_selected(2)
    root=_root(ir)
    wrath=next(a for a in ir.actions if a.family_key=='wrath')
    policy=PolicyDefinition('root_break_sensitivity','Root then Wrath',rules=(
        PolicyRuleDefinition('root',root.id,conditions=(PolicyCondition(kind='target_control_missing',value='root'),)),
        PolicyRuleDefinition('wrath',wrath.id)))
    results=[]
    for chance in (0.,1.):
        actions=tuple(replace(a,effects=tuple(
            replace(e,break_chance_on_damage=chance) if isinstance(e,ControlEffect)
            and e.control_id=='root' else e for e in a.effects))
            if a.family_key=='entangling_roots' else a for a in ir.actions)
        scenario=replace(ir,actions=actions)
        r=evaluate_repeated_pulls(ir_slice=scenario,policy=policy,level=30,
            target_health=200.,count=100,pack_size=2,schedule_incoming_attacks=True,
            recovery_mode='always',max_actions=256)
        assert len(r.pulls)==50 and all(p['pack_all_defeated'] for p in r.pulls)
        results.append(r)
    assert results[0].seconds_per_mob != results[1].seconds_per_mob
    # These are hypothetical sensitivity endpoints, NOT sourced Forever rates.
    assert all(any(x['semantic']=='root_break_on_damage_or_heartbeat'
                   for x in e.unsupported_semantics)
               for a in ir.actions if a.family_key=='entangling_roots'
               for e in a.effects if hasattr(e,'unsupported_semantics'))
