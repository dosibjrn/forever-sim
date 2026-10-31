from __future__ import annotations
from dataclasses import replace
import json, sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice,registered_class_keys
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.native_source_provider import build_source_slice
from src.game.data.forever.source_incoming_world import source_enrich_incoming_world
from src.game.gear import apply_gear_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.model.ir import DamageEffect, HealEffect, PeriodicEffect, WeaponDamageEffect
from src.game.runtime.simulator import expected_weapon_damage, ActorState
from src.shared.leveling.objective import representative_hp
from src.v2.source_joint_discovery import _gear_envelope
from tools.wf251_ingest_two_classes import ingest,CAPTURE


def ir(cls,level=20):return build_game_ir_slice(class_key=cls,level=level)

def gear(cls):
    source=ir(cls)
    selection=_gear_envelope(cls,20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)[0]['selection']
    equipped,app=apply_gear_selection(source,aggregate_stats=selection.aggregate_stats,
        selected_items=tuple(selection.slots.values()),source='canonical_named_test')
    return equipped,app,selection


def test_all_nine_registered_without_false_level_authority():
    assert len(registered_class_keys())==9
    assert ir('hunter',9) is None and ir('hunter',21) is None
    assert ir('paladin',9) is None and ir('paladin',21) is not None
    assert ir('paladin',31) is None
    for key in ('hunter','paladin'):
        assert ir(key,10).provenance['source_coverage_complete'] is False


@pytest.mark.parametrize('level,hunter_shot,hunter_sting,paladin_strike,paladin_heal',[
    (10,3044,13549,679,639),(14,14281,13549,678,647),(20,14282,13550,1866,647)])
def test_source_ranks_are_level_legal(level,hunter_shot,hunter_sting,paladin_strike,paladin_heal):
    h=ir('hunter',level);p=ir('paladin',level)
    assert {a.id for a in h.actions if a.owner_actor_id==h.actor.id}=={f'arcane_shot:{hunter_shot}',f'serpent_sting:{hunter_sting}'}
    assert {a.id for a in p.actions if a.family_key in ('holy_strike','holy_light')}=={f'holy_strike:{paladin_strike}',f'holy_light:{paladin_heal}'}
    assert all(a.provenance[0]['source_url'].startswith('https://www.wowhead.com/forever/spell=') for a in (*h.actions,*(a for a in p.actions if a.family_key in ('holy_strike','holy_light'))))


def test_real_spell_effects_and_spell_power():
    h=ir('hunter');p=ir('paladin')
    sting=next(a for a in h.actions if a.family_key=='serpent_sting')
    shot=next(a for a in h.actions if a.family_key=='arcane_shot')
    heal=next(a for a in p.actions if a.family_key=='holy_light')
    strike=next(a for a in p.actions if a.family_key=='holy_strike')
    assert isinstance(sting.effects[0],PeriodicEffect)
    assert sting.effects[0].total_base_damage==60
    assert sting.effects[0].tick_interval_s==3
    assert shot.effects[0].base_min==39 and shot.costs[0].amount==50
    assert isinstance(heal.effects[0],HealEffect) and heal.effects[0].base_max==176
    assert isinstance(strike.effects[0],WeaponDamageEffect)
    assert isinstance(strike.effects[1],DamageEffect)
    assert strike.effects[1].spell_power_coefficient==pytest.approx(.429)
    assert strike.effects[0].weapon_damage_multiplier==pytest.approx(.32)


def test_named_hunter_ranged_weapon_not_summed_with_melee_weapon():
    h,app,selection=gear('hunter')
    assert selection.slots['weapon']['weapon_dps']>0
    assert selection.slots['ranged']['weapon_dps']>0
    assert app.aggregate_stats['weapon_dps']>selection.slots['ranged']['weapon_dps']
    assert h.auto_attacks[0].damage_source.flat_dps==selection.slots['ranged']['weapon_dps']
    assert h.auto_attacks[0].damage_source.flat_dps!=app.aggregate_stats['weapon_dps']


def test_named_paladin_weapon_ap_spell_and_health_delta():
    p,app,selection=gear('paladin')
    assert p.auto_attacks[0].damage_source.flat_dps==selection.slots['weapon']['weapon_dps']
    assert p.actor.base_stats['attack_power']>=2*app.applied_stats['strength']
    assert p.resources[0].capacity>ir('paladin').resources[0].capacity
    assert p.actor.base_stats['armor']>=app.applied_stats['armor']
    strike=next(a for a in p.actions if a.family_key=='holy_strike')
    state=ActorState.from_ir(p.actor,p.resources,p.modes)
    assert expected_weapon_damage(strike.effects[0],actor=state)['expected_damage']>0


def test_world_incoming_applies_to_other_classes_but_not_druid_twice():
    d=ir('druid');m=ir('mage');h=ir('hunter')
    assert len(d.incoming_attacks)==1 and d.incoming_attacks[0].id.startswith('forever:ordinary')
    assert len(m.incoming_attacks)==len(h.incoming_attacks)==1
    assert len(source_enrich_incoming_world(m).incoming_attacks)==1
    assert 'qualified_classic_proxy' in h.incoming_attacks[0].provenance[0]['scenario_status']


def test_paladin_repeated_pulls_take_incoming_and_recover():
    p=ir('paladin')
    result=evaluate_repeated_pulls(ir_slice=p,policy=p.policies[0],level=20,
        target_health=representative_hp(20),count=3,
        schedule_incoming_attacks=True,apply_target_defense=True)
    assert result.seconds_per_mob>0
    assert result.pulls[0]['recovery_s']>0
    assert result.pulls[0]['health_after_recovery']==p.resources[0].capacity


def test_naked_hunter_without_pet_is_not_falsely_successful():
    h=ir('hunter')
    no_pet=replace(h,companions=(),actor_links=(),
        actions=tuple(a for a in h.actions if a.owner_actor_id==h.actor.id),
        auto_attacks=tuple(a for a in h.auto_attacks if a.owner_actor_id==h.actor.id),
        policies=tuple(p for p in h.policies if not p.provenance.get('companion_policy')))
    with pytest.raises(ValueError,match='actor_died'):
        evaluate_repeated_pulls(ir_slice=no_pet,policy=no_pet.policies[0],level=20,
            target_health=representative_hp(20),count=3,
            schedule_incoming_attacks=True,apply_target_defense=True)


def test_bad_source_spell_level_rejected(tmp_path):
    tmp=tmp_path/'abilities.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(tmp) as dst:src.backup(dst)
    data=json.loads(CAPTURE.read_text())
    data['classes'][0]['actions'][0]['min_level']=999
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='source index does not corroborate'):
        ingest(tmp,bad)


def test_missing_named_ranged_item_rejected():
    h=ir('hunter')
    with pytest.raises(ValueError,match='missing named equipped weapon'):
        apply_gear_selection(h,aggregate_stats={'weapon_dps':20},
            selected_items=({'slot':'weapon','weapon_dps':20,'item_id':1},),source='bad')


def test_source_ingestion_is_idempotent():
    before=sqlite3.connect(DEFAULT_DB).execute('SELECT COUNT(*) FROM verified_native_class_actions').fetchone()[0]
    assert ingest()=={'hunter':6,'paladin':5}
    after=sqlite3.connect(DEFAULT_DB).execute('SELECT COUNT(*) FROM verified_native_class_actions').fetchone()[0]
    assert before==after==13
