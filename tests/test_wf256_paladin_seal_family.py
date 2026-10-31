"""WF256 source-versioned Crusader/Fury ranks through shared runtime and scorer."""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_timed_auras import source_enrich_timed_auras
from src.game.data.forever.gear import select_named_gear
from src.game.gear import apply_gear_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
from src.game.multi_pull import evaluate_repeated_pulls
from src.v2.source_policy_search import synthesize_source_policies
from tools.wf256_ingest_seals import ingest,CAPTURE

def source(level=20):return build_game_ir_slice(class_key='paladin',level=level)
def button(ir,family):return next(a for a in ir.actions if a.family_key==family)
def runtime(ir,health=10000):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    return CombatRuntime(actor=actor,target=TargetState.with_health('enemy',health),
                         auto_attacks=ir.auto_attacks,triggers=ir.triggers)

def test_current_build_rank_identity_and_source():
    assert ingest()['sourced_aura_ranks']==13
    assert ingest()['sourced_aura_ranks']==13
    with sqlite3.connect(DEFAULT_DB) as db:
        rows=db.execute('SELECT family_key,COUNT(*),COUNT(DISTINCT client_build) FROM sourced_timed_aura_actions GROUP BY family_key').fetchall()
        assert ('seal_of_fury',7,1) in rows
        assert ('seal_of_the_crusader',6,1) in rows
    for level,cru,fury in ((10,21082,1311649),(12,20162,1311649),(18,20162,1311656),(20,20162,1311656)):
        ir=source(level)
        assert button(ir,'seal_of_the_crusader').id.endswith(str(cru))
        assert button(ir,'seal_of_fury').id.endswith(str(fury))
        assert button(ir,'seal_of_fury').provenance[0]['client_build']=='1.60.1.70338'
        fury_proc=next(t for t in ir.triggers if t.id.startswith('seal_of_fury:swing'))
        fury_judge=next(t for t in ir.triggers if t.id.startswith('seal_of_fury:judgement'))
        assert fury_proc.effects[0].spell_power_coefficient==pytest.approx(.1)
        assert fury_judge.effects[0].spell_power_coefficient==pytest.approx(.45)

def test_crusader_attack_power_haste_replace_expire_and_judgement_target_bonus():
    ir=source();rt=runtime(ir);actor=rt.actor
    crusader=button(ir,'seal_of_the_crusader');right=button(ir,'seal_of_righteousness');judge=button(ir,'judgement')
    base_ap=float(actor.stats.get('attack_power',0))
    base_speed=rt._effective_auto_swing_s(ir.auto_attacks[0])
    rt.schedule_action(crusader)
    assert actor.stats['attack_power']==pytest.approx(base_ap+51)
    assert rt._effective_auto_swing_s(ir.auto_attacks[0])==pytest.approx(base_speed/1.4)
    rt.advance_to(1.5);rt.schedule_action(judge)
    assert rt.target.active_school_power['judgement:seal_of_the_crusader'][1]==pytest.approx(35)
    rt.schedule_action(right)
    assert actor.stats['attack_power']==pytest.approx(base_ap)
    assert rt._effective_auto_swing_s(ir.auto_attacks[0])==pytest.approx(base_speed)
    rt.advance_to(5.0)
    proc=[e for e in rt.trace if e.kind=='Damage' and 'seal_of_righteousness:swing' in str(e.action_id)]
    assert proc and proc[-1].payload['target_school_power_applied']==pytest.approx(3.5)
    # A different Judgement removes the old one-judgement-per-caster debuff.
    rt.advance_to(11.5);rt.schedule_action(judge)
    assert not rt.target.active_school_power
    rt.advance_to(32)
    assert 'seal:righteousness' not in actor.active_auras

def test_fury_shield_actual_incoming_and_no_shield_negative():
    ir=source()
    tank=select_named_gear(class_key='paladin',level=20,stat_weights={'armor':1,'weapon_dps':1},
                           role='paladin_tank',required_level_policy='observed')
    assert tank.slots['offhand']['armor_type']=='shield'
    geared,_=apply_gear_selection(ir,aggregate_stats=tank.aggregate_stats,
                                  selected_items=tuple(tank.slots.values()))
    rt=runtime(geared);assert rt.actor.stats['equipped_shield']==1
    rt.schedule_action(button(geared,'seal_of_fury'));rt.advance_to(5)
    assert rt.actor.absorb_shields.get('fury_holy_shield',0)>0
    hp_before=rt.actor.resource_amount('health')
    assert geared.incoming_attacks
    attack=geared.incoming_attacks[0]
    result=rt.resolve_incoming_attack(attack,mitigation_rules=geared.mitigation_rules)
    assert result['absorbed_damage']>0
    assert rt.actor.resource_amount('health')==pytest.approx(hp_before-result['health_damage_applied'])
    ret=select_named_gear(class_key='paladin',level=20,stat_weights={'weapon_dps':1},
                          role='paladin_ret',required_level_policy='observed')
    no_shield,_=apply_gear_selection(ir,aggregate_stats=ret.aggregate_stats,
                                     selected_items=tuple(ret.slots.values()))
    rt2=runtime(no_shield);rt2.schedule_action(button(no_shield,'seal_of_fury'));rt2.advance_to(5)
    assert rt2.actor.stats['equipped_shield']==0
    assert not rt2.actor.absorb_shields

def test_generic_source_graph_linked_policy_and_three_pull_score():
    ir=source()
    env=synthesize_source_policies(ir,level=20,max_policies=32,
            include_auto_resource_fallback=True,budget_mode='balanced_frontier')
    assert env['source_graph_linked_candidates_admitted']>=6
    assert not {'seal_of_fury:1311656','seal_of_the_crusader:20162','seal_of_righteousness:20288'} & set(env['supported_actions_not_represented'])
    combos=[p for p in env['policies'] if {'seal_of_the_crusader','seal_of_righteousness','judgement'} <=
            {r.action_id.split(':')[0] for r in p.rules}]
    assert combos
    score=evaluate_repeated_pulls(ir_slice=ir,policy=combos[0],level=20,
                                   target_health=400,count=3,apply_target_defense=True)
    assert score.seconds_per_mob>0 and len(score.pulls)==3
    assert any(a['action_id'].startswith('seal_of_the_crusader') for pull in score.pulls for a in pull['selected_actions'])

def test_negative_unverified_mechanic_and_capture(tmp_path):
    p=json.loads(CAPTURE.read_text());p['client_build']='?'
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(p))
    with pytest.raises(ValueError,match='capture version'):
        ingest(capture_path=bad)
    p=json.loads(CAPTURE.read_text());p['families'][0]['ranks'][0]['spell_id']=999999
    bad.write_text(json.dumps(p))
    with pytest.raises(ValueError,match='canonical spell'):
        ingest(capture_path=bad)
    db=tmp_path/'bad.sqlite'
    with sqlite3.connect(DEFAULT_DB) as a,sqlite3.connect(db) as b:a.backup(b)
    with sqlite3.connect(db) as b:
        b.execute("UPDATE sourced_timed_aura_actions SET mechanic_kind='unknown' WHERE spell_id=20162")
    with pytest.raises(ValueError,match='invalid canonical timed aura rank'):
        source_enrich_timed_auras(source(),db_path=db)

def test_druid_hunter_mage_do_not_receive_paladin_auras():
    for cls in ('druid','hunter','mage'):
        ir=build_game_ir_slice(class_key=cls,level=20)
        assert ir and not any(a.family_key.startswith('seal_of_') for a in ir.actions)
        assert not any(t.required_aura_id and t.required_aura_id.startswith('seal:') for t in ir.triggers)

def test_policy_guard_excludes_expired_but_unprocessed_aura():
    from src.game.policy import condition_matches
    ir=source();rt=runtime(ir)
    seal=button(ir,'seal_of_the_crusader')
    rt.schedule_action(seal)
    aura=rt.actor.active_auras['seal:crusader']
    assert aura.expires_at_s==30.0
    # Simulate the exact boundary before the expiry event is drained. A stale
    # aura must never authorize a Judgement or block a replacement cast.
    rt.actor.current_time_s=30.0
    present=PolicyCondition('aura_present',scope='actor',aura_id='seal:crusader')
    missing=PolicyCondition('aura_missing',scope='actor',aura_id='seal:crusader')
    assert not condition_matches(present,action=seal,runtime=rt)
    assert condition_matches(missing,action=seal,runtime=rt)

def test_crusader_actor_stat_and_haste_expire_across_recovery_boundary():
    ir=source();rt=runtime(ir);actor=rt.actor
    base_ap=actor.stats['attack_power']
    rt.schedule_action(button(ir,'seal_of_the_crusader'))
    assert actor.stats['attack_power']==base_ap+51
    # Combat queue ended on mob death; recovery advanced clock beyond 30s
    # without carrying a status aura expiry event.
    actor.current_time_s=35.0
    new=CombatRuntime(actor=actor,target=TargetState.with_health('next-mob',500),
                      auto_attacks=ir.auto_attacks,triggers=ir.triggers)
    assert 'seal:crusader' not in actor.active_auras
    assert actor.stats['attack_power']==pytest.approx(base_ap)
    assert not actor.aura_attack_speed_multipliers
    assert new._effective_auto_swing_s(ir.auto_attacks[0])==pytest.approx(ir.auto_attacks[0].swing_time_s)

def test_three_pull_crusader_does_not_keep_ap_past_expiry():
    ir=source();cru=button(ir,'seal_of_the_crusader');strike=button(ir,'holy_strike')
    policy=PolicyDefinition(id='source_crusader_repeated',label='source_crusader_repeated',rules=(
        PolicyRuleDefinition('a',cru.id,conditions=(PolicyCondition('aura_missing',scope='actor',aura_id='seal:crusader'),)),
        PolicyRuleDefinition('b',strike.id)))
    score=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=20,
                                   target_health=400,count=3,apply_target_defense=True)
    assert score.end_time_s>90
    assert score.actor.stats['attack_power']==pytest.approx(ir.actor.base_stats['attack_power'])
    assert not score.actor.aura_attack_speed_multipliers
