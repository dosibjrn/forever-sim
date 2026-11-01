from __future__ import annotations
from src.game.checkpoint_p3_smoke import fast_p3_smoke
from src.rulesets.forever.items.catalogue import ItemRecord
from src.rulesets.forever.items.runtime_selection import item_score


def _item(item_id,slot,**kwargs):
    return ItemRecord(item_id,'test',slot,item_level=25,required_level=20,**kwargs)


def test_real_gear_scorer_includes_raw_combat_axes_and_source_hp5(monkeypatch):
    import src.rulesets.forever.items.source_equipment_semantics as sem
    monkeypatch.setattr(sem,'semantic_for_item',lambda _:None)
    x=_item(99001,'ranged',weapon_type='bow',weapon_dps=12,hit=10,crit=3,dodge=5,
            extra_stats={'healthrgn':6})
    weights={'ranged_weapon_dps':2,'hit':1,'crit':1,'dodge':1,
             'health_regeneration_per_5s':1}
    assert item_score(x,weights)==24+10+3+5+6
    assert item_score(x,{'weapon_dps':1})==0.
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *args,**kw:(x,))
    r=fast_p3_smoke(class_key='hunter',level=20,weights=weights,
                    weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=False)
    assert r['p3_pass'],r['blockers']
    assert r['slots']['ranged']['items'][0]['score']==48


def test_dps_channels_are_alternatives_not_three_simultaneous_requirements(monkeypatch):
    wand=_item(99002,'ranged',weapon_type='wand',weapon_dps=20)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**kw:(wand,))
    r=fast_p3_smoke(class_key='mage',level=20,weights={'wand_dps':2},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=False)
    assert r['p3_pass'],r['blockers']
    r2=fast_p3_smoke(class_key='mage',level=20,weights={'weapon_dps':2},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=False)
    assert 'MISSING_APPLICABLE_DPS_WEIGHT' in r2['blockers']


def test_proc_only_item_needs_no_invented_weight(monkeypatch):
    trinket=_item(99003,'trinket')
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**kw:(trinket,))
    r=fast_p3_smoke(class_key='druid',level=20,weights={},
        weight_evidence_kind='SOURCE_FORMULA_CONTEXT',weapon_damage_dependent=False)
    assert r['p3_pass'],r['blockers']


def test_zero_resistance_allowed_but_negative_stat_forbidden(monkeypatch):
    item=_item(99004,'back',stamina=5,extra_stats={'arcres':7})
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**kw:(item,))
    okay=fast_p3_smoke(class_key='druid',level=20,
        weights={'stamina':1,'resistance_arcane':0},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=False)
    assert okay['p3_pass'],okay['blockers']
    bad=fast_p3_smoke(class_key='druid',level=20,
        weights={'stamina':1,'resistance_arcane':-1},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=False)
    assert 'NEGATIVE_WEIGHT:resistance_arcane' in bad['blockers']


def test_parry_raw_rating_and_ranged_ap_ordinary_axes(monkeypatch):
    item=_item(99005,'finger',extra_stats={'parryrtng':4,'rgdatkpwr':15})
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**kw:(item,))
    weights={'parry':3,'ranged_attack_power':2}
    assert item_score(item,weights)==42.
    r=fast_p3_smoke(class_key='hunter',level=20,weights=weights,
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=False)
    assert r['p3_pass'],r['blockers']


def test_weapon_mean_hit_requires_rotation_damage_not_class(monkeypatch):
    item=_item(99006,'one_hand',weapon_dps=15,weapon_min_damage=10,weapon_max_damage=20)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**kw:(item,))
    okay=fast_p3_smoke(class_key='paladin',level=20,weights={'weapon_dps':1},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=False)
    assert okay['p3_pass'],okay['blockers']
    bad=fast_p3_smoke(class_key='paladin',level=20,weights={'weapon_dps':1},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=True)
    assert 'MISSING_WEIGHT:mean_weapon_hit_damage' in bad['blockers']
