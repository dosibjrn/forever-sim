"""Source-index rank promotion + verified Mage talent -> actual combat integration."""
from dataclasses import replace
import sqlite3
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_rank_overlay import _parse_rank
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_legal_beam import search_source_legal_beam


def test_mage_l20_promotes_latest_sourced_rank_and_disambiguates_variant():
    ir = build_game_ir_slice(class_key='mage', level=20)
    ids = {a.family_key:a for a in ir.actions}
    assert ids['frostbolt'].id == 'frostbolt:7322'
    assert ids['frostbolt'].effects[0].base_min == 69.6103
    assert ids['frostbolt'].effects[0].base_max == 76.7897
    assert ids['frostbolt'].cast_time_s == 2.6
    assert ids['frostbolt'].effects[0].spell_power_coefficient == 0.706
    assert ids['fireball'].effects[0].spell_power_coefficient == 0.857
    assert ids['fire_blast'].effects[0].spell_power_coefficient == 0.429
    assert ids['fireball'].id == 'fireball:3140'
    assert ids['fireball'].effects[1].total_base_damage == 12
    assert ids['fireball'].effects[1].duration_s == 8
    assert ids['fire_blast'].id == 'fire_blast:2137'  # not variant 400619
    assert ids['fire_blast'].cooldown_s == 8
    assert ir.policies[0].rules[1].action_id == 'fire_blast:2137'
    assert ir.policies[0].rules[2].action_id == 'frostbolt:7322'


def test_cross_class_source_rank_promotion_and_full_index_visibility():
    mage = build_game_ir_slice(class_key='mage', level=20)
    assert len(mage.talents) == 54
    assert sum(bool(t.ranks and t.ranks[0].modifiers) for t in mage.talents) == 4
    assert len([t for t in mage.talents if not t.ranks]) == 50
    assert {a.id for a in build_game_ir_slice(class_key='priest',level=20).actions} >= {'smite:598','shadow_word_pain:970'}
    assert 'lightning_bolt:915' in {a.id for a in build_game_ir_slice(class_key='shaman',level=20).actions}
    assert 'shadow_bolt:1088' in {a.id for a in build_game_ir_slice(class_key='warlock',level=20).actions}
    assert len(build_game_ir_slice(class_key='druid',level=20).talents) == 52


def test_mage_source_rank_facts_are_canonical_versioned_sqlite():
    with sqlite3.connect(DEFAULT_DB) as conn:
        r=conn.execute('select tooltip_text,source_url,source_build,captured_at from verified_spell_rank_facts where spell_id=7322').fetchone()
        assert r and '69.6103' in r[0] and 'wowhead.com/forever' in r[1]
        assert r[2] and r[3]
        assert conn.execute('select count(*) from verified_talent_rank_facts where class_key="mage"').fetchone()[0] == 16
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_ice_lance_requires_sourced_tier_points_and_is_not_default_action():
    ir=build_game_ir_slice(class_key='mage',level=20)
    assert not any(a.family_key=='ice_lance' for a in ir.actions)
    with pytest.raises(ValueError,match='tier gate'):
        validate_talent_selection(ir,{'ice_lance':1},level=20)
    selection={'improved_frostbolt':5,'elemental_precision':5,'ice_lance':1}
    changed,application=apply_talent_selection(ir,selection,level=20)
    assert application.spent_points==11
    assert any(a.id=='ice_lance:1312002' for a in changed.actions)
    assert next(a for a in changed.actions if a.family_key=='frostbolt').cast_time_s==2.1
    assert next(a for a in changed.actions if a.family_key=='frostbolt').metadata['outgoing_hit_bonus']==0.05
    with pytest.raises(ValueError,match='talent points exceed'):
        validate_talent_selection(ir,{**selection,'improved_fireball':1},level=20)


def test_ice_lance_generic_conditional_damage_real_runtime():
    ir=build_game_ir_slice(class_key='mage',level=20)
    ir,_=apply_talent_selection(ir,{'improved_frostbolt':5,'elemental_precision':5,'ice_lance':1},level=20)
    action=next(a for a in ir.actions if a.family_key=='ice_lance')
    def damage(frozen):
        actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
        target=TargetState.with_health('test',10000)
        if frozen:
            target.active_controls['frozen']=10.
        rt=CombatRuntime(actor=actor,target=target)
        rt.schedule_action(action)
        rt.advance_to(1.5)
        return next(e for e in rt.result().events if e.kind=='Damage').payload
    normal=damage(False); frozen=damage(True)
    assert normal['amount']==30.
    assert frozen['amount']==120.
    assert frozen['conditional_control_active'] is True
    assert normal['conditional_control_active'] is False


def test_missing_granted_action_source_fails_closed():
    ir=build_game_ir_slice(class_key='mage',level=20)
    ir=replace(ir,source_facts=tuple(f for f in ir.source_facts if f.get('family')!='talent_granted_action_facts'))
    with pytest.raises(ValueError,match='granted action absent'):
        apply_talent_selection(ir,{'improved_frostbolt':5,'elemental_precision':5,'ice_lance':1},level=20)


def test_unverified_rank_cannot_promote_from_unchanged_index():
    ir=build_game_ir_slice(class_key='mage',level=20)
    action=next(a for a in ir.actions if a.family_key=='frostbolt')
    row=(999999,99,20,'batch','https://www.wowhead.com/forever/spell=999999',
         '{"envChange":{"status":"unchanged"}}')
    assert _parse_rank(action,row)[1]=='rank_tooltip_missing'


def test_mage_l20_source_legal_joint_search_executes_full_recovery():
    r=search_source_legal_beam(class_key='mage',level=20,max_allocations=24,
        screening_gear_count=1,finalists=2,policy_cap=4,beam_width=2)
    w=r['independent_winner']
    assert r['total_independent_evaluated_allocations']>=10
    assert w['seconds_per_mob']>0 and len(w['gear_slots'])>=10
    assert len(w['best_policy']['pulls'])==3
    assert sum(x['recovery_s'] for x in w['best_policy']['pulls'])>0
    assert r['source_coverage_complete'] is False


def test_real_frost_nova_freeze_then_ice_lance_bonus_and_expiry():
    ir=build_game_ir_slice(class_key='mage',level=20)
    ir,_=apply_talent_selection(ir,{'improved_frostbolt':5,'elemental_precision':5,'ice_lance':1},level=20)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    target=TargetState.with_health('test',10000)
    rt=CombatRuntime(actor=actor,target=target)
    nova=next(a for a in ir.actions if a.family_key=='frost_nova')
    lance=next(a for a in ir.actions if a.family_key=='ice_lance')
    rt.schedule_action(nova);rt.advance_to(1.5)
    assert target.active_controls['frozen']==8.0
    rt.schedule_action(lance);rt.advance_to(3.0)
    event=next(e for e in rt.result().events if e.kind=='Damage' and e.action_id==lance.id)
    assert event.payload['conditional_multiplier_applied']==4.0
    assert event.payload['amount']==120.0
    rt.advance_to(8.5)
    assert 'frozen' not in target.active_controls
    rt.schedule_action(lance);rt.advance_to(10.0)
    lance_damage=[e.payload['amount'] for e in rt.result().events if e.kind=='Damage' and e.action_id==lance.id]
    assert lance_damage == [120.0,30.0]


def test_source_only_tier_corridor_reaches_unseeded_granted_ability():
    from src.v2.source_legal_beam import source_tier_unlock_corridors
    ir=build_game_ir_slice(class_key='mage',level=20)
    corridors=source_tier_unlock_corridors(ir,level=20)
    assert corridors and any(x.get('ice_lance')==1 for x in corridors)
    for allocation in corridors:
        validate_talent_selection(ir,allocation,level=20)
