"""Timed aura + on-swing proc + non-consuming Judgement, source to score."""
from __future__ import annotations
from dataclasses import replace
import sqlite3
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_timed_auras import source_enrich_timed_auras
from src.game.runtime import ActorState,CombatRuntime,TargetState,action_eligibility
from src.game.multi_pull import evaluate_repeated_pulls
from src.v2.source_policy_search import synthesize_source_policies
from src.shared.leveling.objective import representative_hp
from tools.wf253_ingest_seal import ingest


def paladin(level=20):return build_game_ir_slice(class_key='paladin',level=level)


def test_canonical_rank_and_consumer_level_selection():
    for level,rank in ((10,20287),(17,20287),(18,20288),(20,20288)):
        ir=paladin(level)
        seal=[a for a in ir.actions if a.family_key=='seal_of_righteousness']
        judge=[a for a in ir.actions if a.family_key=='judgement']
        assert len(seal)==len(judge)==1
        assert seal[0].id.endswith(str(rank))
        assert len([t for t in ir.triggers if t.required_aura_id=='seal:righteousness'])==2
        assert {t.required_aura_id for t in ir.triggers}=={'seal:righteousness','seal:fury','seal:crusader'}
        assert seal[0].provenance[0]['client_build']=='1.60.1.70338'
        assert judge[0].gcd_s==0 and judge[0].cooldown_s==10


def test_seal_swing_and_judgement_damage_and_nonconsumption():
    ir=paladin()
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('dummy',10000),
                          auto_attacks=ir.auto_attacks,triggers=ir.triggers)
    seal=next(a for a in ir.actions if a.family_key=='seal_of_righteousness')
    judge=next(a for a in ir.actions if a.family_key=='judgement')
    assert not action_eligibility(action=judge,actor=actor).eligible
    runtime.schedule_action(seal)
    assert 'seal:righteousness' in actor.active_auras
    runtime.advance_to(3.0)
    swings=[e for e in runtime.trace if e.kind=='Damage' and ':swing:' in str(e.action_id)]
    assert len(swings)==1 and swings[0].payload['amount']>0
    # The client tooltip leaves speed scaling server-side: current qualified
    # legacy 2.4s reference is explicit, not silently treated as exact.
    expected=((4.04598+14.08)/2.0)*(ir.auto_attacks[0].swing_time_s/2.4)
    assert swings[0].payload['amount']==pytest.approx(expected)
    runtime.schedule_action(judge)
    judged=[e for e in runtime.trace if e.kind=='Damage' and ':judgement:' in str(e.action_id)]
    assert len(judged)==1 and judged[0].payload['amount']>=41
    assert 'seal:righteousness' in actor.active_auras
    assert actor.cooldown_ready_s[judge.id]==13.0
    runtime.advance_to(30.1)
    assert 'seal:righteousness' not in actor.active_auras
    assert not action_eligibility(action=judge,actor=actor).eligible


def test_source_policy_search_actually_includes_linked_seal_and_judge():
    ir=paladin()
    env=synthesize_source_policies(ir,level=20,max_policies=32,
                                   include_auto_resource_fallback=True,budget_mode='balanced_frontier')
    assert not any(x['id'].startswith('seal_of_righteousness') for x in env['excluded'])
    both=[p for p in env['policies'] if
          any(r.action_id.startswith('seal_of_righteousness') for r in p.rules) and
          any(r.action_id.startswith('judgement') for r in p.rules)]
    assert both
    scored=evaluate_repeated_pulls(ir_slice=ir,policy=both[0],level=20,
        target_health=representative_hp(20),count=3,apply_target_defense=True)
    assert len(scored.pulls)==3 and scored.seconds_per_mob>0
    assert any(a['action_id'].startswith('judgement') for p in scored.pulls for a in p['selected_actions'])


def test_source_aura_procs_even_without_incoming_enemy_attacks():
    ir=paladin()
    p=next(p for p in synthesize_source_policies(ir,level=20,max_policies=32,
        include_auto_resource_fallback=True,budget_mode='balanced_frontier')['policies']
        if any(r.action_id.startswith('seal_of_righteousness') for r in p.rules)
        and any(r.action_id.startswith('judgement') for r in p.rules))
    with_incoming=evaluate_repeated_pulls(ir_slice=ir,policy=p,level=20,
        target_health=representative_hp(20),count=3,schedule_incoming_attacks=True)
    without_incoming=evaluate_repeated_pulls(ir_slice=ir,policy=p,level=20,
        target_health=representative_hp(20),count=3,schedule_incoming_attacks=False)
    assert with_incoming.seconds_per_mob>0 and without_incoming.seconds_per_mob>0
    assert without_incoming.seconds_per_mob<=with_incoming.seconds_per_mob


def test_negative_corrupt_rank_and_capture_rejected(tmp_path):
    tmp=tmp_path/'bad.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(tmp) as dest:src.backup(dest)
    with sqlite3.connect(tmp) as db:
        db.execute('UPDATE sourced_timed_aura_actions SET proc_reference_speed_s=-2 WHERE spell_id=20288')
    # Pass the native slice after removing new aura/action IR.
    full=paladin()
    plain=replace(full,actions=tuple(a for a in full.actions if a.family_key not in ('seal_of_righteousness','judgement')),
        triggers=(),source_facts=tuple(f for f in full.source_facts if f.get('family')!='source_timed_aura_trigger'))
    with pytest.raises(ValueError,match='invalid canonical timed aura rank'):
        source_enrich_timed_auras(plain,db_path=tmp)
    capture=tmp_path/'bad.json'
    capture.write_text('{"source_url":"http://unverified","client_build":"?"}')
    with pytest.raises(ValueError,match='source authority'):
        ingest(db_path=tmp,capture_path=capture)


def test_idempotent_ingest_and_other_class_unchanged():
    with sqlite3.connect(DEFAULT_DB) as db:
        before=db.execute('SELECT COUNT(*) FROM sourced_timed_aura_actions').fetchone()[0]
    assert ingest()['aura_rank_rows']==3
    with sqlite3.connect(DEFAULT_DB) as db:
        assert db.execute('SELECT COUNT(*) FROM sourced_timed_aura_actions').fetchone()[0]==before==17
    for cls in ('hunter','mage','druid'):
        ir=build_game_ir_slice(class_key=cls,level=20)
        assert ir is not None and not any(a.family_key=='seal_of_righteousness' for a in ir.actions)
