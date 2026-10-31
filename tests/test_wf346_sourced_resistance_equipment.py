"""WF346: sourced Rune of Battle effects are used in generic combat, not guessed."""
from dataclasses import replace
import json
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,source_item_l0
from src.game.runtime.state import ActorState,TargetState
from src.game.runtime.events import CombatEvent
from src.game.runtime.simulator import CombatRuntime,expected_incoming_attack
from src.game.model.ir import IncomingAttackDefinition
from src.rulesets.forever.items.runtime_selection import available_items,select_gear
from src.rulesets.forever.items.source_equipment_semantics import (
    apply_equipped_source_effects,source_equipment_semantics,ledger_path,validate_equipped_item_ids)


def _source():
    return build_game_ir_slice(class_key='druid',level=20)


def test_source_pinned_additive_and_biome_effects():
    src=_source();facts=source_equipment_semantics()
    rows={x.item_id:x for x in available_items('druid',20,required_level_policy='observed')}
    for item_id,stat in ((21566,'spell_penetration'),(21568,'resistance_all')):
        assert facts[item_id].equip_semantics=='EQUIPPABLE_TYPED_PASSIVE'
        assert facts[item_id].typed_effects==( ('add_actor_stat',stat,2.), )
        assert facts[item_id].conditional_effects==(
            ('add_actor_stat_if_environment',stat,4.,('forest','grassland')),)
        assert source_item_l0(rows[item_id])['l2_effect_fully_supported']
        baseline=apply_equipped_source_effects(src,class_key='druid',level=20,item_ids=(item_id,))
        forest=apply_equipped_source_effects(src,class_key='druid',level=20,item_ids=(item_id,),environment_tags=('forest',))
        plains=apply_equipped_source_effects(src,class_key='druid',level=20,item_ids=(item_id,),environment_tags=('grassland',))
        assert baseline.actor.base_stats[stat]==pytest.approx(src.actor.base_stats.get(stat,0.)+2.)
        assert forest.actor.base_stats[stat]==pytest.approx(src.actor.base_stats.get(stat,0.)+6.)
        assert plains.actor.base_stats[stat]==pytest.approx(forest.actor.base_stats[stat])
        assert not baseline.provenance['source_environment_conditional_passives'][0]['activated']
        assert forest.provenance['source_environment_conditional_passives'][0]['activated']
    with pytest.raises(ValueError,match='BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP'):
        validate_equipped_item_ids((21566,21568))
    assert checkpoint_item_l0(class_key='druid',level=20)['unknown_effect_item_count']==29
    assert select_gear('druid',20,'druid_feral',required_level_policy='observed',exclude_unknown_item_effects=True)['trinket1'].item_id==21566


def test_outgoing_magic_penetration_changes_real_combat_runtime_only_with_target_resistance():
    def damage(pen,resistance=None,school='arcane'):
        actor=ActorState(id='hero',stats={'spell_penetration':pen},metadata={'level':20})
        metadata={'spell_hit':1.,'melee_hit':1.,'armor':0.,'armor_constant':100.,
                  'armor_reduction_cap':.75,'combat_capture_id':'synthetic_target'}
        if resistance is not None:metadata['resistance_'+school]=resistance
        target=TargetState.with_health('enemy',200.,**metadata)
        runtime=CombatRuntime(actor=actor,target=target)
        runtime.queue.push(CombatEvent(time_s=0,kind='Damage',actor_id='hero',target_id='enemy',
            action_id='synthetic_spell',payload={'amount':100.,'school':school,'resolution':'expected_value'}))
        runtime.advance_to(0.)
        event=next(x for x in runtime.trace if x.kind=='Damage')
        return runtime.total_damage,event.payload
    raw,obs0=damage(0,50)
    boost,obs2=damage(2,50)
    forest,obs6=damage(6,50)
    physical,_=damage(6,50,'physical')
    unsupported,meta=damage(6,None)
    assert raw==pytest.approx(62.5)
    assert boost==pytest.approx(64.0)
    assert forest==pytest.approx(67.0)
    assert physical==pytest.approx(100.0)
    assert unsupported==pytest.approx(100.0)
    assert meta['magic_resistance_context']=='UNSOURCED_TARGET_SCHOOL_RESISTANCE_NOT_APPLIED'
    assert obs6['spell_penetration']==6.
    assert obs2['target_magic_resistance_after']==48.


def test_incoming_magic_resistance_reduces_damage_but_not_physical():
    def attack(school):
        return IncomingAttackDefinition(id='test',name='test',source_actor_id='enemy',
            target_actor_id='hero',school=school,raw_damage=100.,hit_chance=1.,
            health_resource_id='health',provenance=({'source':'synthetic_test'},))
    for school in ('fire','arcane','frost','nature'):
        regular=expected_incoming_attack(attack(school),actor=ActorState(id='hero',stats={'resistance_all':2},metadata={'level':20}))
        forest=expected_incoming_attack(attack(school),actor=ActorState(id='hero',stats={'resistance_all':6},metadata={'level':20}))
        assert regular['post_mitigation_damage']==pytest.approx(98.5)
        assert forest['post_mitigation_damage']==pytest.approx(95.5)
    phys=expected_incoming_attack(attack('physical'),actor=ActorState(id='hero',stats={'resistance_all':6},metadata={'level':20}))
    assert phys['post_mitigation_damage']==pytest.approx(100.)
    with pytest.raises(ValueError,match='INVALID_SOURCED_MAGIC_RESISTANCE_CONTEXT'):
        expected_incoming_attack(attack('fire'),actor=ActorState(id='hero',stats={'resistance_all':6},metadata={}))


def test_tampered_typed_magnitudes_fail_closed(tmp_path,monkeypatch):
    original=ledger_path()
    dst=tmp_path/'typed.sqlite'
    with sqlite3.connect(original) as db,sqlite3.connect(dst) as copy:db.backup(copy)
    with sqlite3.connect(dst) as db:
        row=db.execute('SELECT typed_effects_json FROM source_item_equipment_semantics WHERE item_id=21566').fetchone()[0]
        effects=json.loads(row);effects[0]['amount']=22
        db.execute('UPDATE source_item_equipment_semantics SET typed_effects_json=? WHERE item_id=21566',
            (json.dumps(effects),))
    monkeypatch.setenv('FOREVER_ITEM_EQUIPMENT_SEMANTICS',str(dst))
    with pytest.raises(ValueError,match='SOURCE_ITEM_EFFECT_MAGNITUDE_NOT_PROVEN'):
        source_equipment_semantics()


def test_generic_school_resistance_and_spell_penetration_from_sourced_numeric_extra():
    from src.rulesets.forever.items.source_numeric_extras import (
        modeled_source_numeric_extras, apply_source_numeric_extras)
    rows = {x.item_id:x for x in available_items('druid',20,required_level_policy='observed')}
    # Real source items, generic input schema -- no per-item combat behavior.
    cloak = rows[12979]  # Firebane Cloak, imported fire resistance
    ring = rows[6463]    # Deep Fathom Ring, imported spell penetration
    assert modeled_source_numeric_extras(cloak)['resistance_fire'] == float(cloak.extra_stats['firres'])
    assert modeled_source_numeric_extras(ring)['spell_penetration'] == float(ring.extra_stats['splpen'])
    src = _source()
    equipped = apply_source_numeric_extras(src,class_key='druid',level=20,
                                            item_ids=(12979,6463))
    assert equipped.actor.base_stats['resistance_fire'] == pytest.approx(
        src.actor.base_stats.get('resistance_fire',0.) + cloak.extra_stats['firres'])
    assert equipped.actor.base_stats['spell_penetration'] == pytest.approx(
        src.actor.base_stats.get('spell_penetration',0.) + ring.extra_stats['splpen'])
    actor=ActorState(id='hero',stats={'resistance_fire':cloak.extra_stats['firres']},metadata={'level':20})
    baseline=expected_incoming_attack(IncomingAttackDefinition(id='fire',name='fire',source_actor_id='x',target_actor_id='hero',school='fire',raw_damage=100.,hit_chance=1.,health_resource_id='health'),
        actor=ActorState(id='hero',stats={},metadata={'level':20}))
    protected=expected_incoming_attack(IncomingAttackDefinition(id='fire',name='fire',source_actor_id='x',target_actor_id='hero',school='fire',raw_damage=100.,hit_chance=1.,health_resource_id='health'),actor=actor)
    assert protected['post_mitigation_damage'] < baseline['post_mitigation_damage']
    # Rune of Duty's tooltip-confirmed all-resistance value must not be counted
    # twice because the same item also has maximum-biome numeric columns.
    assert modeled_source_numeric_extras(rows[21568]) == {}
    record = checkpoint_item_l0(class_key='druid',level=20)
    assert record['unknown_effect_item_count'] == 29
    assert source_item_l0(cloak)['l2_effect_fully_supported']
    assert source_item_l0(ring)['l2_effect_fully_supported']
