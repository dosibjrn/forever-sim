"""Sourced outgoing hit/Armor/debuff, positive + fail-closed cases."""
from dataclasses import replace
import sqlite3
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.target_combat_source import target_combat_metadata, source_enrich_target_combat
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.model import PolicyDefinition, PolicyRuleDefinition, PolicyCondition
from src.game.policy import execute_priority_policy
from src.v2.source_policy_search import synthesize_source_policies


def source_runtime(level=20, *, class_key='druid', defense=True):
    ir=build_game_ir_slice(class_key=class_key,level=level)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    target=TargetState.with_health('enemy',10000.,**(target_combat_metadata(ir) if defense else {}))
    return ir,actor,target,CombatRuntime(actor=actor,target=target,auto_attacks=ir.auto_attacks)


def test_canonical_60_level_enemy_armor_and_all_faerie_ranks():
    for level, expected_id, armor in ((20,'source_spell:770',836.),
                                      (30,'source_spell:778',1179.),
                                      (42,'source_spell:9749',2218.),
                                      (54,'source_spell:9907',3180.),
                                      (60,'source_spell:9907',3750.)):
        ir=build_game_ir_slice(class_key='druid',level=level)
        assert target_combat_metadata(ir)['armor']==armor
        if level==60:
            assert target_combat_metadata(ir)['armor_constant']==pytest.approx(5882.5)
        ff=[a for a in ir.actions if a.family_key=='faerie_fire']
        assert len(ff)==1 and ff[0].id==expected_id
        assert all(ff[0].id in (m.enabled_action_ids or ()) for m in ir.modes)
        assert ff[0].provenance[0]['source_url'].startswith('https://foreverdb.net/spell/')
    mage=build_game_ir_slice(class_key='mage',level=20)
    assert target_combat_metadata(mage)['armor']==836
    assert not any(a.family_key=='faerie_fire' for a in mage.actions)


def test_outgoing_physical_armor_and_hit_spell_hit_and_bleed_bypass():
    ir,actor,target,r=source_runtime()
    r.schedule_action(next(a for a in ir.actions if a.family_key=='wrath'))
    r.advance_to(3.0)
    spell=[e for e in r.trace if e.kind=='Damage']
    assert spell and spell[-1].payload['source_base_hit']==pytest.approx(.96)
    assert spell[-1].payload['target_armor_reduction']==0
    # A sourced Cat auto attack must pay physical hit and armor, not 100% hit.
    ir,actor,target,r=source_runtime()
    r.schedule_action(next(a for a in ir.actions if a.family_key=='cat_form'))
    r.advance_to(3.0)
    auto=[e for e in r.trace if e.kind=='Damage' and e.payload.get('auto_attack')]
    assert auto and auto[0].payload['source_base_hit']==pytest.approx(.95)
    assert auto[0].payload['target_armor']==836
    assert 0<auto[0].payload['target_armor_reduction']<.75


def test_faerie_source_effect_refresh_and_expiry_on_same_clock():
    ir,actor,target,r=source_runtime()
    ff=next(a for a in ir.actions if a.family_key=='faerie_fire')
    r.schedule_action(ff);r.advance_to(2.0)
    assert target.effective_stat('armor')==pytest.approx(836-175*.96)
    assert any(e.kind=='TargetStatDebuffApplied' for e in r.trace)
    r.advance_to(42.0)
    assert target.effective_stat('armor')==836
    assert not target.active_stat_modifiers


def test_missing_target_source_fails_closed_and_invalid_profile_fails_closed(tmp_path):
    ir,actor,target,r=source_runtime(defense=False)
    ff=next(a for a in ir.actions if a.family_key=='faerie_fire')
    with pytest.raises(ValueError,match='requires sourced target stat'):
        r.schedule_action(ff)
    db=tmp_path/'copy.sqlite'
    source=__import__('src.game.data.forever.sqlite_talents',fromlist=['DEFAULT_DB']).DEFAULT_DB
    src=sqlite3.connect(source);dst=sqlite3.connect(db);src.backup(dst);src.close();dst.close()
    with sqlite3.connect(db) as c:
        c.execute("UPDATE outgoing_combat_profile_source_facts SET melee_hit=2 WHERE level=20")
    with pytest.raises(ValueError,match='invalid sourced target combat profile'):
        source_enrich_target_combat(replace(ir,provenance={}),db_path=db)


def test_source_policy_actually_includes_debuff_without_class_specific_hint():
    ir=build_game_ir_slice(class_key='druid',level=20)
    result=synthesize_source_policies(ir,level=20,max_policies=24,
        mode_id='cat',include_auto_resource_fallback=True,budget_mode='balanced_frontier')
    candidates=[p for p in result['policies'] if any(r.action_id=='source_spell:770' for r in p.rules)]
    assert candidates
    assert any(any(c.kind=='aura_missing' for c in r.conditions)
               for p in candidates for r in p.rules if r.action_id=='source_spell:770')


def test_physical_bleed_bypasses_armor_but_direct_physical_does_not():
    ir,actor,target,r=source_runtime(level=24)
    r.schedule_action(next(a for a in ir.actions if a.family_key=='cat_form'))
    r.advance_to(5.0)
    rake=next(a for a in ir.actions if a.family_key=='rake')
    r.schedule_action(rake);r.advance_to(18.0)
    damage=[e for e in r.trace if e.kind=='Damage' and e.action_id==rake.id]
    assert any(not e.payload['periodic'] and e.payload['target_armor_reduction']>0 for e in damage)
    assert any(e.payload['periodic'] and e.payload['target_armor_reduction']==0 for e in damage)
    assert all(e.payload['source_base_hit']==pytest.approx(.95) for e in damage)
