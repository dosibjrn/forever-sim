"""Druid L20 Bash 5211, sourced observation -> canonical stage -> real L2 events.

Does NOT certify complete source coverage, client build or 1/148.
"""
from __future__ import annotations
import copy,hashlib,json,shutil,sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.simulator import CombatRuntime,ActionNotEligibleError
from tools.wf321_ingest_control_observations import ingest

OBS=Path('evidence/wf321/druid_l20_control_observations.json')

@pytest.fixture
def stage(tmp_path,monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    p=tmp_path/'source.sqlite'
    shutil.copy2(DEFAULT_DB,p)
    ingest(p,OBS)
    return p


def _ir(stage,level=20):
    return build_game_ir_slice(class_key='druid',level=level,ability_db_path=stage)


def _combat(ir,with_stun,*,rage=10.0):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('bear')
    actor.resources['rage']=rage
    target=TargetState.with_health('enemy',1_000_000)
    runtime=CombatRuntime(actor=actor,target=target,incoming_attacks=ir.incoming_attacks,
                          mitigation_rules=ir.mitigation_rules)
    if with_stun:
        action=next(x for x in ir.actions if x.id=='source_control:5211')
        runtime.schedule_action(action,at_time_s=1)
    runtime.advance_to(5)
    return runtime


def test_bash_full_source_to_l2_stun_suppresses_enemy_damage_and_rage(stage):
    ir=_ir(stage)
    action=next(x for x in ir.actions if x.id=='source_control:5211')
    assert action.costs[0].amount==10
    assert action.cooldown_s==60 and action.effects[0].duration_s==2
    assert action.requirements==({'kind':'minimum_level','value':14},{'kind':'mode_is','value':'bear'})
    without=_combat(ir,False)
    with_bash=_combat(ir,True)
    suppress=[x for x in with_bash.trace if x.kind=='IncomingAttackSuppressed']
    assert len(suppress)==1 and suppress[0].time_s==2
    assert suppress[0].payload['health_damage_applied']==0
    actual=[x for x in with_bash.trace if x.kind=='IncomingAttackResolved']
    assert len(actual)==1 and actual[0].time_s==4
    assert len([x for x in without.trace if x.kind=='IncomingAttackResolved'])==2
    assert with_bash.actor.resources['health'] > without.actor.resources['health']
    # Actual Rage cost (10) and absence of damage-taken Rage at t=2.
    assert with_bash.actor.resources['rage'] < without.actor.resources['rage']
    assert not any(x.kind=='DamageTaken' and x.time_s==2 for x in with_bash.trace)
    assert not with_bash.target.active_controls


def test_bash_requires_level_bear_rage_and_cooldown(stage):
    assert not any(x.id=='source_control:5211' for x in _ir(stage,13).actions)
    ir=_ir(stage)
    a=next(x for x in ir.actions if x.id=='source_control:5211')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',100000))
    with pytest.raises(ActionNotEligibleError,match='(requires mode|action disabled by active mode)'):
        rt.schedule_action(a)
    actor.transition_mode('bear')
    with pytest.raises(ActionNotEligibleError,match='insufficient rage'):
        rt.schedule_action(a)
    actor.resources['rage']=20
    rt.schedule_action(a)
    assert actor.resources['rage']==10
    assert rt.target.active_controls['stun']==2
    with pytest.raises(ActionNotEligibleError,match='cooldown'):
        rt.schedule_action(a,at_time_s=3)
    # Stun is a status on the enemy, and does not arbitrarily disable the
    # player's form, rage regen, other actions or timed GCD mechanism.
    assert 'stun' not in rt.target.active_controls  # expired while advancing to t=3


def test_root_is_not_melee_immunity_and_stun_expiry_boundary(stage):
    ir=_ir(stage)
    rt=_combat(ir,True)
    rt.target.active_controls['root']=10
    before=rt.actor.resources['health']
    rt.advance_to(6)
    assert rt.actor.resources['health']<before  # t=6 lands even when rooted
    assert any(x.kind=='IncomingAttackResolved' and x.time_s==6 for x in rt.trace)
    # Exactly at expiry t=3, the stun itself is no longer active.
    assert rt.target.active_controls.get('stun',0)<=3


def test_source_only_duration_edit_changes_actual_incoming_damage(stage,tmp_path):
    source=json.loads(OBS.read_text())
    source['observations'][0]['effect_text']='Stuns the target for 5 sec.'
    obs2=tmp_path/'longer.json';obs2.write_text(json.dumps(source))
    base=_ir(stage)
    baseline=_combat(base,True)
    ingest(stage,obs2)
    changed=_ir(stage)
    action=next(x for x in changed.actions if x.id=='source_control:5211')
    assert action.effects[0].duration_s==5
    longer=_combat(changed,True)
    assert longer.actor.resources['health'] > baseline.actor.resources['health']
    assert [x.time_s for x in longer.trace if x.kind=='IncomingAttackSuppressed']==[2,4]
    assert all(x.time_s!=4 for x in longer.trace if x.kind=='DamageTaken')


def test_observation_index_and_fact_tampering_fail_closed(stage):
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE source_control_action_observations SET duration_s=8 WHERE spell_id=5211")
    with pytest.raises(ValueError,match='STORED_FACT_DIFFERS'):
        _ir(stage)
    ingest(stage,OBS)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE spell_index SET name='Bash Broken' WHERE spell_id=5211 AND class_key='druid'")
    with pytest.raises(ValueError,match='INDEX_IDENTITY_DRIFT'):
        _ir(stage)


def test_observation_not_silently_current_for_historical_build(stage,monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-02')
    assert not any(x.id=='source_control:5211' for x in _ir(stage).actions)
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    assert any(x.id=='source_control:5211' for x in _ir(stage).actions)


def test_bash_is_legally_discoverable_with_resource_enabler_in_mode(stage):
    from src.v2.source_budgeted_prefix import source_prefix_envelope
    from src.v2.source_button_discovery import discover_source_combat_buttons
    from src.v2.source_policy_search import _rule_options
    ir=_ir(stage)
    bear=discover_source_combat_buttons(ir,level=20,mode_id='bear',include_resource_actions=True)
    assert 'source_control:5211' in bear['action_ids']
    assert 'enrage:5229' in bear['action_ids']
    env=source_prefix_envelope(ir,level=20)
    bear_path=next(x for x in env['mode_paths'] if x['entry']=='bear_form:5487')
    assert {'enrage:5229','source_control:5211'}.issubset(bear_path['actions'])
    assert any(x[0].kind=='target_control_missing' and x[0].value=='stun'
               for x in _rule_options(next(a for a in ir.actions if a.id=='source_control:5211')))
    # Enrage is not free: it must be an explicit action following the
    # sourced legal transition, before the Rage-consuming Bash.
    assert not any(x.id=='source_control:5211' for x in _ir(stage,level=13).actions)


def test_real_paid_l2_search_executes_enrage_bash_and_checks_suppression(stage):
    from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
    ir=_ir(stage)
    outcome=run_source_stateful_budgeted(
        class_key='druid',level=20,ir_slice=ir,max_l2_attempts=120,
        max_event_transitions=15000,max_prefix_length=4,use_l1=False,
        search_guarded_continuations=True,search_mode_paths=True,
        family_budget_mode='measured_balanced')
    sequence=['bear_form:5487','enrage:5229','source_control:5211']
    assert sequence in outcome['source_mode_resource_dependencies']
    observed=[x for x in outcome['observations']
              if x.get('prefix')==sequence and x.get('status')=='FULL_L2_VERIFIED']
    assert observed and observed[0]['score_s_per_mob']>0
    assert outcome['l2_attempts']<=120
    assert outcome['event_transitions']<=15000
    assert outcome['complete_search'] is False


def test_precombat_source_maintenance_obeys_one_event_hard_budget():
    """L2 cannot silently process 8 prebuff events under a cap of one."""
    from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
    outcome=run_source_stateful_budgeted(
        class_key='druid',level=20,max_l2_attempts=12,
        max_event_transitions=1,use_l1=False,
        search_mode_paths=True,family_budget_mode='measured_balanced')
    assert outcome['event_transitions']<=1
    assert outcome['l2_attempts']<=12
    assert outcome['winner'] is None
