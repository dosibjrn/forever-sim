"""Source spell batches, executable effects, and explicit geometry search."""
import json
import sqlite3
from dataclasses import replace
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_ability_semantics import source_ability_actions
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import CombatRuntime, action_eligibility, ActionNotEligibleError
from src.v2.source_policy_search import synthesize_source_policies


def _action(ir, family):
    return next(a for a in ir.actions if a.family_key == family)


def test_20_new_verified_rank_facts_and_level_selection():
    with sqlite3.connect(DEFAULT_DB) as conn:
        rows = conn.execute("SELECT semantic_type,COUNT(*) FROM ability_semantic_source_facts GROUP BY semantic_type").fetchall()
        assert dict(rows)['weapon_combo_position'] == 5
        assert dict(rows)['periodic_control'] == 6
        assert dict(rows)['direct_periodic_heal'] == 9
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    for level,expected in ((20,('source_spell:1062','source_spell:8938',None)),
                           (24,('source_spell:1062','source_spell:8939','source_spell:5221')),
                           (30,('source_spell:5195','source_spell:8940','source_spell:6800')),
                           (60,('source_spell:9853','source_spell:9858','source_spell:9830'))):
        ir=build_game_ir_slice(class_key='druid',level=level)
        for family,sid in zip(('entangling_roots','regrowth','shred'),expected):
            if sid is None:
                assert not any(a.family_key==family for a in ir.actions)
            else:
                assert _action(ir,family).id==sid


def test_shred_rejects_unknown_or_front_and_scores_behind_with_combo():
    ir=build_game_ir_slice(class_key='druid',level=24)
    action=_action(ir,'shred')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('cat')
    actor.resources['energy']=100
    target=TargetState.with_health('mob',1000)
    runtime=CombatRuntime(actor=actor,target=target)
    assert not action_eligibility(action=action,actor=actor,target=target).eligible
    with pytest.raises(ActionNotEligibleError,match='relative position'):
        runtime.schedule_action(action)
    target.metadata['attacker_relative_position']='front'
    with pytest.raises(ActionNotEligibleError,match='relative position'):
        runtime.schedule_action(action)
    target.metadata['attacker_relative_position']='behind'
    assert action_eligibility(action=action,actor=actor,target=target).eligible
    runtime.schedule_action(action)
    assert target.health<1000
    assert target.resources['combo_points']==pytest.approx(1)
    assert actor.resources['energy']<=40


def test_root_control_dot_and_no_invented_melee_immunity():
    ir=build_game_ir_slice(class_key='druid',level=20)
    action=_action(ir,'entangling_roots')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    target=TargetState.with_health('mob',1000)
    runtime=CombatRuntime(actor=actor,target=target,spell_power=0)
    runtime.schedule_action(action)
    runtime.advance_to(17)
    assert target.health==pytest.approx(955) # 45 over 15s
    assert not target.active_controls
    assert sum(e.kind=='Damage' and e.action_id==action.id for e in runtime.trace)==5
    assert 'root_break_on_damage_or_heartbeat' in str(action.effects)


def test_regrowth_direct_and_periodic_heal_same_combat_clock():
    ir=build_game_ir_slice(class_key='druid',level=24)
    action=_action(ir,'regrowth')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resources['health']=0
    target=TargetState.with_health('mob',1000)
    runtime=CombatRuntime(actor=actor,target=target,spell_power=0)
    runtime.schedule_action(action)
    runtime.advance_to(23)
    assert actor.resources['health']==pytest.approx((235+266)/2+224)
    assert actor.resources['mana']<actor.resource_initial_amount['mana']
    assert any(e.kind=='Heal' and e.action_id==action.id for e in runtime.trace)
    assert len([e for e in runtime.trace if e.kind=='Heal' and e.payload.get('periodic')])==7


def test_position_search_envelope_never_invents_rear_geometry():
    ir=build_game_ir_slice(class_key='druid',level=24)
    default=synthesize_source_policies(ir,level=24,max_policies=256,
        include_auto_resource_fallback=True,mode_id='cat')
    assert 'source_spell:5221' not in default['eligible_buttons']
    assert any(x['id']=='source_spell:5221' and x['reason']=='position_not_established' for x in default['excluded'])
    rear=synthesize_source_policies(ir,level=24,max_policies=1024,
        include_auto_resource_fallback=True,mode_id='cat',attacker_relative_position='behind')
    assert 'source_spell:5221' in rear['eligible_buttons']
    assert rear['candidate_count']>default['candidate_count']


def test_bad_root_source_text_fails_closed(tmp_path):
    import shutil
    db=tmp_path/'db.sqlite';shutil.copy2(DEFAULT_DB,db)
    with sqlite3.connect(db) as conn:
        row=conn.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1062 AND kind="abilities"').fetchone()
        payload=json.loads(row[0]);payload['envChange']['after']['text']='This spell does anything'
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=1062 AND kind="abilities"',(json.dumps(payload),))
    ir=build_game_ir_slice(class_key='druid',level=20)
    ir=replace(ir,actions=tuple(a for a in ir.actions if a.family_key!='entangling_roots'),
               modes=tuple(replace(m,enabled_action_ids=tuple(a for a in m.enabled_action_ids if a!='source_spell:1062')) for m in ir.modes))
    result=source_ability_actions(ir,class_key='druid',level=20,db_path=db)
    assert not any(a.family_key=='entangling_roots' for a in result.actions)
    assert any(x['spell_id']==1062 for x in result.provenance['source_ability_ingest']['unparsed_semantic_rows'])


def test_actual_rear_scenario_policy_search_uses_shred():
    from src.v2.source_mode_search import evaluate_discovered_mode_search
    r=evaluate_discovered_mode_search(class_key='druid',level=24,
        schedule_incoming_attacks=True,max_policies_per_path=1024,
        attacker_relative_position='behind')
    assert any(a['action_id']=='source_spell:5221' for a in r['winner']['selected_actions'])
    # WF241: the same Shred policy now optimizes actual HoT/food/water overlap.
    assert r['winner']['seconds_per_mob']==pytest.approx(23.58512931034483)
    assert r['winner']['recovery_s'] < 9.46703687975696


def test_compound_heal_does_not_masquerade_as_instant_recovery_option():
    from src.game.recovery import _direct_heal_options
    ir=build_game_ir_slice(class_key='druid',level=24)
    options=_direct_heal_options(ir.actions,healing_power=0)
    assert any(a.family_key=='healing_touch' for a,_ in options)
    assert all(a.family_key!='regrowth' for a,_ in options)
