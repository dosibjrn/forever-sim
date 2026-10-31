"""P1 checks source-backed stealth behavior, not an aura-only placeholder."""
import json
import sqlite3
from pathlib import Path
from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.runtime import ActorState,TargetState,CombatRuntime,action_eligibility,ActionNotEligibleError
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_stealth_actions import source_stealth_actions
from tools.wf474_ingest_stealth import ingest

ROOT=Path(__file__).resolve().parents[1]

def setup():
    ir=build_game_ir_slice(class_key='druid',level=20)
    action=next(a for a in ir.actions if a.id=='source_spell:5215')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.metadata['level']=20
    actor.transition_mode('cat')
    return ir,actor,action

def pack(actor):
    return CombatRuntime(actor=actor,target=TargetState.with_health('one',100000),
        other_targets=(TargetState.with_health('two',100000),),
        spatial_positions_yards={'one':(15.,0.),'two':(22.,0.)})

def test_source_compilation_and_ineligibility():
    ir,actor,action=setup()
    assert action.metadata['source_spell_id']==5215
    assert action.gcd_s == 0 and action.cooldown_s == 0
    assert {'minimum_level','mode_is','out_of_combat','aura_missing'} == {r['kind'] for r in action.requirements}
    assert next(x for x in action.effects if x.stealth).movement_speed_multiplier == .6
    assert action.id in next(m for m in ir.modes if m.id=='cat').enabled_action_ids
    assert action.id not in next(m for m in ir.modes if m.id=='bear').enabled_action_ids
    assert build_game_ir_slice(class_key='druid',level=19) and all(a.id!='source_spell:5215' for a in build_game_ir_slice(class_key='druid',level=19).actions)
    actor.transition_mode('bear')
    assert not action_eligibility(action=action,actor=actor).eligible
    actor.transition_mode('cat')
    actor.metadata['in_combat']=True
    assert not action_eligibility(action=action,actor=actor).eligible


def test_stealth_slows_movement_and_avoids_proximity_aggro():
    ir,actor,action=setup()
    runtime=pack(actor)
    runtime.schedule_action(action)
    assert runtime._active_stealth()
    assert not runtime._engaged_targets
    assert not action_eligibility(action=action,actor=actor).eligible  # no infinite Prowl spam
    arrival=runtime.begin_player_move((8,0))
    assert arrival == pytest.approx(8./(7.*.6))
    runtime.advance_to(arrival)
    assert runtime.player_position_yards == pytest.approx((8.,0.))
    assert not runtime._engaged_targets  # 7 yards from the first mob; normal aggro radius 10
    # At the conservative scenario detection radius the character is seen.
    arrival=runtime.begin_player_move((10.5,0))
    runtime.advance_to(arrival)
    assert 'one' in runtime._engaged_targets
    assert runtime._active_stealth() is None
    assert any(e.kind=='StealthBroken' and e.payload['reason']=='detected_by_enemy' for e in runtime.trace)
    assert actor.cooldown_ready_s[action.id] >= next(e.time_s for e in runtime.trace if e.kind=='StealthBroken') + 9.9
    assert not action_eligibility(action=action,actor=actor).eligible


def test_hostile_action_breaks_stealth_and_stealth_state_survives_pull():
    ir,actor,prowl=setup()
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',100000))
    runtime.schedule_action(prowl)
    assert prowl.effects[0].aura_id in actor.active_auras
    # New pull receives carried stealth state even without explicit re-cast.
    next_pull=pack(actor)
    assert next_pull._active_stealth()
    assert next_pull.begin_player_move((5.,0)) == pytest.approx(actor.current_time_s+5/(7*.6))
    # Sourced Cat attack removes stealth; no passive aura auto-attacks until then.
    direct=next(a for a in ir.actions if a.family_key in ('claw','rake') and any(e.effect_type in ('direct_damage','weapon_damage') for e in a.effects))
    actor.resources['energy']=actor.resource_capacity['energy']
    runtime.schedule_action(direct)
    assert runtime._active_stealth() is None
    assert 'stealth:5215' not in actor.active_auras
    assert any(e.kind=='StealthBroken' and e.action_id==direct.id for e in runtime.trace)
    assert actor.cooldown_ready_s[prowl.id] >= actor.current_time_s + 9.9
    with pytest.raises(ActionNotEligibleError):
        runtime.schedule_action(prowl)  # Combat + 10s fade cooldown


def test_source_observation_fails_closed_on_identity_drift(tmp_path):
    path=tmp_path/'source.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src, sqlite3.connect(path) as dest:src.backup(dest)
    from src.game.data.forever.source_stealth_actions import source_stealth_actions
    ir=build_game_ir_slice(class_key='druid',level=20)
    ingest(path,ROOT/'evidence/wf474_stealth_source_observations.json')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE spell_index SET name='different' WHERE class_key='druid' AND spell_id=5215")
    with pytest.raises(ValueError,match='STEALTH_SOURCE_INDEX_DRIFT'):
        source_stealth_actions(ir,class_key='druid',level=20,db_path=path)


def test_leaving_stealth_mode_removes_aura_and_starts_fade_cooldown():
    ir,actor,prowl=setup()
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('enemy',100000))
    rt.schedule_action(prowl)
    assert rt._active_stealth()
    cancel=next(a for a in ir.actions if a.id=='cancel_mode:cat')
    rt.schedule_action(cancel)
    assert actor.current_mode_id=='caster'
    assert not rt._active_stealth()
    assert 'stealth:5215' not in actor.active_auras
    assert actor.cooldown_ready_s[prowl.id]>=actor.current_time_s+9.99
    assert any(e.kind=='StealthBroken' and e.payload['reason']=='form_change' for e in rt.trace)


def test_scratch_candidate_is_genuine_prepull_action_not_combat_spam():
    from src.game.policy_evolution import scratch_policies
    ir,_,_ = setup()
    policies = scratch_policies(ir,max_candidates=256)
    prowl = [rule for policy in policies for rule in policy.rules if rule.action_id=='source_spell:5215']
    assert prowl
    assert all(rule.phase=='prepull' for rule in prowl)
