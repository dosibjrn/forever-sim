"""P2 RED->mechanics GREEN: typed source critical spell timed cast/GCD buff."""
from pathlib import Path
from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from src.game.data.forever.source_rank_promotion import _staged_timed_spell_crit_haste

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'
FILL={'genesis':5,'improved_entangling_roots':1,'improved_moonfire':2,'improved_wrath':5,
      'moonglow':3,'natures_grace':1,'natures_majesty':2,'natures_reach':2}

def prepare():
    ir=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB))[0]
    selected,_=apply_talent_selection(ir,FILL,level=30,bonus_talent_points=5)
    return ir,selected

def actions(ir):
    return (next(a for a in ir.actions if a.family_key=='moonfire' and a.id=='moonfire:8927'),
            next(a for a in ir.actions if a.family_key=='wrath' and a.id=='wrath:5180'))

def runtime(ir,crit):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.stats['spell_crit_chance']=crit
    actor.resources['mana']=max(3000,actor.resources.get('mana',0))
    actor.resource_capacity['mana']=max(3000,actor.resource_capacity.get('mana',0))
    return CombatRuntime(actor=actor,target=TargetState.with_health('dummy',100000))


def test_compiles_full_pinned_two_clause_source_rank_and_applies_legal_build():
    base,selected=prepare();t=next(t for t in base.talents if t.id=='natures_grace')
    assert [m.kind for m in t.ranks[0].modifiers]==['timed_spell_crit_cast_haste']
    rule=selected.actor.metadata['source_timed_spell_crit_haste']
    assert rule['cast_speed_fraction']==pytest.approx(.1)
    assert rule['gcd_reduction_fraction']==pytest.approx(.1)
    assert rule['duration_s']==pytest.approx(3.)
    assert rule['source']['source_build']=='1.60.1.70338'


def test_real_spell_crit_applies_timed_speed_to_following_cast_and_gcd():
    _,ir=prepare();moon,wrath=actions(ir)
    rt=runtime(ir,crit=1.)
    rt.schedule_action(moon);rt.advance_to(.01)
    assert rt.actor.source_timed_spell_crit_haste_until_s==pytest.approx(3.)
    assert any(e.kind=='TimedSpellCritHasteGranted' for e in rt.trace)
    # Prevent the *following* spell from refreshing the 3 s buff.
    rt.actor.stats['spell_crit_chance']=0.
    wrath=replace(wrath,effects=tuple(replace(e,crit_chance_bonus=0.,
        crit_chance_stat_id=None) if type(e).__name__=='DamageEffect' else e
        for e in wrath.effects))
    rt.enqueue_action(wrath,at_time_s=1.5)
    rt.advance_to(1.5)
    starts=[e for e in rt.trace if e.kind=='ActionStarted' and e.action_id==wrath.id]
    assert starts
    assert starts[-1].payload['cast_time_s']==pytest.approx(wrath.cast_time_s/1.1)
    assert rt.actor.gcd_ready_s==pytest.approx(1.5+wrath.gcd_s*.9)
    rt.advance_to(3.6)
    assert rt.actor.source_timed_spell_crit_haste_until_s==pytest.approx(3.)
    # New cast after expiry is unhasted.
    rt.enqueue_action(wrath,at_time_s=3.7)
    rt.advance_to(3.7)
    starts=[e for e in rt.trace if e.kind=='ActionStarted' and e.action_id==wrath.id]
    assert starts[-1].payload['cast_time_s']==pytest.approx(wrath.cast_time_s)


def test_zero_crit_and_periodic_spell_damage_cannot_grant_haste():
    _,ir=prepare();moon,wrath=actions(ir)
    rt=runtime(ir,crit=0.)
    # DamageEffect may carry intrinsic spell crit; override for deterministic 0.
    moon=replace(moon,effects=tuple(replace(e,crit_chance_bonus=0.,
        crit_chance_stat_id=None) if type(e).__name__=='DamageEffect' else e
        for e in moon.effects))
    rt.schedule_action(moon);rt.advance_to(5.)
    assert not any(e.kind=='TimedSpellCritHasteGranted' for e in rt.trace)
    assert rt.actor.source_timed_spell_crit_haste_until_s==0


def test_invalid_source_compound_fails_closed_not_half_modifier():
    _,ir=prepare();talent=next(t for t in ir.talents if t.id=='natures_grace')
    source=dict(talent.ranks[0].provenance['checkpoint_source_l0'])
    for field,bad in (('additional_value',None),('target','melee'),('condition','passive'),
                      ('source_build','1.60.1.99999')):
        tampered={**source,field:bad}
        assert _staged_timed_spell_crit_haste(tampered,source_build='1.60.1.70338') is None


def test_p2_gate_does_not_claim_certified_crit_distribution():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    report=audit_checkpoint_p2_executor(ir,db_path=DB,
      checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),bonus_talent_points=5)
    row=next(r for r in report['structural_witnesses'] if r['talent_id']=='natures_grace')
    assert row['application']['status']=='APPLIED_IN_GAME_IR'
    assert row['status']=='SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS'
    assert not report['green']
    assert report['reachable_without_executor']<=9


def test_paid_100_mob_caster_probe_finds_real_cast_speed_difference_not_optimality():
    """Synthetic 100%-crit fixture tests event/gcd/carry, not game crit odds."""
    from src.game.multi_pull import evaluate_repeated_pulls
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    _,with_buff=prepare()
    base=compiled_ir=compile_talent_runtime(build_game_ir_slice(
        class_key='druid',level=30,ability_db_path=DB))[0]
    without_buff=apply_talent_selection(base,
        {k:v for k,v in FILL.items() if k!='natures_grace'},
        level=30,bonus_talent_points=5)[0]
    results={}
    for key,ir in [('off',without_buff),('on',with_buff)]:
        forced=replace(ir,actor=replace(ir.actor,base_stats={
            **dict(ir.actor.base_stats),'spell_crit_chance':1.0}))
        wrath=next(a for a in forced.actions if a.id=='wrath:5180')
        policy=PolicyDefinition('wf439_mechanics_not_optimization','wrath only',
            (PolicyRuleDefinition('wrath',wrath.id),))
        run=evaluate_repeated_pulls(ir_slice=forced,policy=policy,level=30,
            target_health=275.,count=100,schedule_incoming_attacks=False,
            recovery_mode='always',max_actions=64)
        assert len(run.pulls)==100
        assert all(p['pack_all_defeated'] for p in run.pulls)
        assert sum(len(p['selected_actions']) for p in run.pulls)==200
        results[key]=run.seconds_per_mob
    assert results['on'] < results['off']
    # Stable fixture on this baseline: a real second spell benefits from haste.
    assert results['on']==pytest.approx(3.575410557184769,abs=.01)
    assert results['off']==pytest.approx(3.8467741935483946,abs=.01)


def test_haste_never_shortens_melee_gcd_even_if_buff_is_active():
    _,ir=prepare();moon,_=actions(ir)
    claw=next(a for a in ir.actions if a.family_key=='claw')
    rt=runtime(ir,crit=1.)
    rt.actor.source_timed_spell_crit_haste_until_s=3.
    rt.actor.transition_mode('cat')
    rt.actor.resources['energy']=100.
    rt.enqueue_action(claw)
    rt.advance_to(0.)
    start=next(e for e in rt.trace if e.kind=='ActionStarted' and e.action_id==claw.id)
    assert start.payload['source_timed_crit_haste_gcd_fraction']==0.
    assert start.payload['source_timed_crit_haste_cast_fraction']==0.
    assert rt.actor.gcd_ready_s==pytest.approx(claw.gcd_s)
