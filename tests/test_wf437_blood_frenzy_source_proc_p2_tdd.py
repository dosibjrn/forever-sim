"""WF437 P2 RED->GREEN->REFACTOR: sourced compound critical resource proc.

Later-build flat resource awards are deliberately NOT target-build-certified.
The full P2 gate must remain RED even when both proc branches execute.
"""
from dataclasses import replace
from pathlib import Path
import shutil,sqlite3,json
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState,TargetState,CombatRuntime
from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from tools.wf437_ingest_critical_resource_source import ingest

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'
SOURCE=Path(__file__).resolve().parents[1]/'evidence/wf437/BLOOD_FRENZY_RESOURCE_SOURCE_UNVERIFIED_BRIDGE.json'
FILL={'ferocity':5,'heart_of_the_wild':5,'feral_swiftness':2,
      'feral_instinct':3,'thick_hide':3,'shredding_attacks':3,
      'savage_fury':2,'sharpened_claws':2}

def root(db=DB):
    return build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)

def compiled(db=DB):
    return compile_talent_runtime(root(db))[0]

def selected(rank):
    sel={**FILL,'blood_frenzy':rank}
    sel['feral_instinct']-=rank-1
    assert sum(sel.values())==26
    return apply_talent_selection(compiled(),sel,level=30,bonus_talent_points=5)[0]

def live(rank,form,*,crit=1.0,action='claw'):
    ir=selected(rank)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode(form)
    actor.stats['melee_crit_chance']=crit
    target=TargetState.with_health('enemy',1000000.)
    if form=='cat':
        actor.resources['energy']=100.
        rt=CombatRuntime(actor=actor,target=target)
        button=next(a for a in ir.actions if a.family_key==action and a.id.endswith(':28'))
        rt.schedule_action(button);rt.advance_to(3)
    else:
        actor.resources['rage']=50.
        rt=CombatRuntime(actor=actor,target=target,auto_attacks=ir.auto_attacks)
        rt.advance_to(4)
    return rt


def test_two_rank_proc_rules_compiled_as_indivisible_source_pair():
    ir=compiled();talent=next(t for t in ir.talents if t.id=='blood_frenzy')
    assert [len(r.modifiers) for r in talent.ranks]==[2,2]
    for rank in talent.ranks:
        assert {m.target_id for m in rank.modifiers}=={'rage','combo_points'}
        assert all(m.provenance['unsupported_build_bridge'] for m in rank.modifiers)
        assert all(m.provenance['source_build']=='1.60.1.70338' for m in rank.modifiers)
        assert all(m.provenance['resource_amount_source_build']=='1.60.1.70374'
                   for m in rank.modifiers)
    assert [m.value for m in talent.ranks[0].modifiers]==[.5,.5]
    assert [m.value for m in talent.ranks[1].modifiers]==[1.,1.]


def test_bear_expected_critical_proc_ranks_are_2_5_and_5_rage():
    one=live(1,'bear');two=live(2,'bear')
    assert one.actor.resources['rage']==pytest.approx(52.5)
    assert two.actor.resources['rage']==pytest.approx(55.)
    assert next(e.payload['gained'] for e in one.trace if e.kind=='ResourceEventGain')==pytest.approx(2.5)
    assert next(e.payload['gained'] for e in two.trace if e.kind=='ResourceEventGain')==pytest.approx(5.)


def test_cat_expected_critical_combo_points_are_target_scoped_and_generator_only():
    one=live(1,'cat');two=live(2,'cat')
    assert one.target.resources['combo_points']==pytest.approx(1.5)
    assert two.target.resources['combo_points']==pytest.approx(2.)
    assert not 'combo_points' in one.actor.resources
    for rt in (one,two):
        assert any(e.kind=='ResourceEventGain' and e.target_id=='enemy' for e in rt.trace)
    # A Cat auto-attack is a crit but NOT a combo-generating action.
    ir=selected(2)
    a=ActorState.from_ir(ir.actor,ir.resources,ir.modes);a.transition_mode('cat')
    a.stats['melee_crit_chance']=1.
    rt=CombatRuntime(actor=a,target=TargetState.with_health('enemy',1000000.),auto_attacks=ir.auto_attacks)
    rt.advance_to(3)
    assert not [e for e in rt.trace if e.kind=='ResourceEventGain'
                and e.payload.get('resource_id')=='combo_points']


def test_zero_crit_probability_cannot_trigger_fictitious_proc():
    rt=live(2,'cat',crit=0.)
    assert rt.target.resources['combo_points']==pytest.approx(1.)
    assert not [e for e in rt.trace if e.kind=='ResourceEventGain'
                and e.payload.get('resource_id')=='combo_points']


def test_no_partial_source_rank_accepted_when_other_clause_corrupted():
    ir=root()
    changed=[]
    for t in ir.talents:
        if t.id!='blood_frenzy':changed.append(t);continue
        ranks=[]
        for rank in t.ranks:
            raw=dict(rank.provenance['checkpoint_source_l0'])
            raw['additional_target']='wrong_resource_context'
            ranks.append(replace(rank,provenance={**rank.provenance,'checkpoint_source_l0':raw}))
        changed.append(replace(t,ranks=tuple(ranks)))
    promoted,_=promote_atomic_source_talent_effects(replace(ir,talents=tuple(changed)))
    assert not any(r.modifiers for r in next(t for t in promoted.talents if t.id=='blood_frenzy').ranks)


def test_new_db_facts_mutate_resource_award_not_engine_magic_number(tmp_path):
    db=tmp_path/'source.sqlite';shutil.copy2(DB,db)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE sourced_critical_resource_talent_facts SET bear_amount=9 WHERE talent_id='blood_frenzy'")
    ir=compile_talent_runtime(root(db))[0]
    rule=next(r for r in apply_talent_selection(ir,{**FILL,'blood_frenzy':2,'feral_instinct':2},
                level=30,bonus_talent_points=5)[0].resources if r.id=='rage')
    assert next(r.multiplier for r in rule.event_gain_rules if 'critical_gain' in r.id)==pytest.approx(9.)
    invalid=json.loads(SOURCE.read_text());invalid['records'][0]['resource_bridge_verified']=True
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(invalid))
    with pytest.raises(ValueError,match='UNVERIFIED_CROSS_BUILD'):
        ingest(db,bad)


def test_full_gate_remains_red_with_version_bridge_and_actual_26point_witness():
    j=audit_checkpoint_p2_executor(root(),db_path=DB,
        checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),
        bonus_talent_points=5)
    # WF438 adds 3 new source-backed resource action ranks; historical WF437 bound.
    assert j['reachable_without_executor']<=13
    assert j['rank_application_failure_count']<=16
    for row in j['structural_witnesses']:
        if row['talent_id']=='blood_frenzy':
            assert row['status']=='SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS'
            assert row['application']['status']=='APPLIED_IN_GAME_IR'
            assert 'RESOURCE_AMOUNT_SOURCE_BUILD_BRIDGE_UNVERIFIED' in row['partial_semantics']
    assert not j['green'] and j['partial_runtime_semantics_count']>=3


def test_100mob_real_cat_source_proc_execution():
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    from src.game.multi_pull import evaluate_repeated_pulls
    ir=selected(2)
    claw=next(a for a in ir.actions if a.id=='claw:28')
    enter=next(a for a in ir.actions if a.family_key=='cat_form')
    exit_action=next(a for a in ir.actions if a.family_key=='cancel_mode' and a.id.endswith(':cat'))
    policy=PolicyDefinition('source_bf2','cat claw plus source critical proc',
        rules=(PolicyRuleDefinition('claw',claw.id),))
    result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,target_health=180.,count=100,
        schedule_incoming_attacks=True,pre_combat_action_ids=(enter.id,),
        post_combat_action_ids=(exit_action.id,),recovery_mode='always',max_actions=128)
    assert len(result.pulls)==100 and all(p['pack_all_defeated'] for p in result.pulls)
    assert result.seconds_per_mob>0
