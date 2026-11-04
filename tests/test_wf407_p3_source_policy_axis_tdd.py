"""Source-bound P3 policy semantics and no false FAIL from irrelevant axes."""
from types import SimpleNamespace
import pytest
from src.game.checkpoint_p3_smoke import (fast_p3_smoke,
    fast_p3_smoke_for_policy, policy_uses_weapon_damage)
from src.rulesets.forever.items.catalogue import ItemRecord


def test_unused_unsupported_axis_does_not_fail_ordinary_item_smoke(monkeypatch):
    armor=ItemRecord(301,'Armor','chest',item_level=20,required_level=10,
                     armor=70,stamina=3)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**k:(armor,))
    r=fast_p3_smoke(class_key='druid',level=20,
                    weights={'armor':0.01,'stamina':0.02,'wand_dps':None},
                    weight_evidence_kind='MEASURED_SOURCE_CONTEXT',
                    weapon_damage_dependent=False)
    assert r['p3_pass'] is True
    assert not any('wand_dps' in b for b in r['blockers'])


def test_source_policy_automatically_requires_mean_hit_weight(monkeypatch):
    weapon=ItemRecord(302,'Mace','two_hand',item_level=20,required_level=10,
                      weapon_min_damage=11,weapon_max_damage=19,weapon_dps=6)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**k:(weapon,))
    action=SimpleNamespace(id='strike',effects=(SimpleNamespace(effect_type='weapon_damage'),))
    ir=SimpleNamespace(id='real_source_ir',actions=(action,))
    policy=SimpleNamespace(id='generated',rules=(SimpleNamespace(action_id='strike'),))
    r=fast_p3_smoke_for_policy(class_key='druid',level=20,
        weights={'weapon_dps':1.,'mean_weapon_hit_damage':None},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',source_ir=ir,policy=policy)
    assert r['weapon_damage_dependent'] is True
    assert 'MISSING_WEIGHT:mean_weapon_hit_damage' in r['blockers']
    assert r['source_policy']['source_ir_id']=='real_source_ir'


def test_unknown_action_cannot_silently_exempt_mean_hit_rule():
    ir=SimpleNamespace(id='ir',actions=())
    policy=SimpleNamespace(id='policy',rules=(SimpleNamespace(action_id='missing'),))
    with pytest.raises(ValueError,match='P3_POLICY_ACTION_NOT_IN_SOURCE_IR'):
        policy_uses_weapon_damage(ir,policy)


def test_ordinary_extra_weight_can_be_zero_but_named_stamina_must_be_positive(monkeypatch):
    item=ItemRecord(303,'Cloak','back',item_level=20,required_level=10,
                    stamina=5,extra_stats={'arcres':7})
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**k:(item,))
    result=fast_p3_smoke(class_key='druid',level=20,
                         weights={'stamina':0.02,'resistance_arcane':0.0},
                         weight_evidence_kind='MEASURED_SOURCE_CONTEXT',
                         weapon_damage_dependent=False)
    assert result['p3_pass'] is True
    assert result['slots']['back']['items'][0]['contributions']['resistance_arcane']==0.0
    negative=fast_p3_smoke(class_key='druid',level=20,
                           weights={'stamina':0.0,'resistance_arcane':0.0},
                           weight_evidence_kind='MEASURED_SOURCE_CONTEXT',
                           weapon_damage_dependent=False)
    assert 'NONPOSITIVE_RELEVANT_WEIGHT:stamina' in negative['blockers']


def test_source_policy_missing_optional_requirements_keeps_caster_defensive_zero(monkeypatch):
    # Source-action projections/fixtures may omit the optional requirements
    # field. This must not turn the P3 smoke into an AttributeError.
    item = ItemRecord(304, 'Caster chest', 'chest', item_level=20,
                      required_level=10, armor=70, stamina=3)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',
                        lambda *a, **k: (item,))
    action = SimpleNamespace(id='bolt',
                             effects=(SimpleNamespace(effect_type='direct_damage'),))
    ir = SimpleNamespace(id='real_source_ir', actions=(action,), modes=(),
                         auto_attacks=())
    policy = SimpleNamespace(id='caster', rules=(SimpleNamespace(action_id='bolt'),))
    report = fast_p3_smoke_for_policy(class_key='druid', level=20,
        source_ir=ir, policy=policy, weights={'armor': 0., 'stamina': 0.},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT')
    assert report['p3_pass'] is True
    assert report['source_policy']['defensive_positive_required'] is False
    assert report['verified_stat_assertions'] == report['tested_stat_assertions']


def test_source_policy_missing_optional_requirements_does_not_exempt_bear(monkeypatch):
    # The optional field is not a backdoor to remove selected Bear relevance.
    item = ItemRecord(305, 'Bear chest', 'chest', item_level=20,
                      required_level=10, armor=70, stamina=3)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',
                        lambda *a, **k: (item,))
    shift = SimpleNamespace(id='shift', effects=(
        SimpleNamespace(effect_type='mode_change', target_mode_id='bear'),))
    ir = SimpleNamespace(id='real_source_ir', actions=(shift,), modes=(),
                         auto_attacks=())
    policy = SimpleNamespace(id='bear', rules=(SimpleNamespace(action_id='shift'),))
    report = fast_p3_smoke_for_policy(class_key='druid', level=20,
        source_ir=ir, policy=policy, weights={'armor': 0., 'stamina': 0.},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT')
    assert report['source_policy']['defensive_positive_required'] is True
    assert report['p3_pass'] is False
    assert 'NONPOSITIVE_RELEVANT_WEIGHT:armor' in report['blockers']



def test_p3_report_preserves_raw_stat_values_for_paid_witness(monkeypatch):
    item = ItemRecord(306, 'Caster robe', 'chest', item_level=30,
                      required_level=20, spell_power=17)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',
                        lambda *a, **k: (item,))
    report = fast_p3_smoke(
        class_key='mage', level=30, weights={'spell_power': 0.0},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT',
        weapon_damage_dependent=False,
    )
    row = report['slots']['chest']['items'][0]
    assert row['stat_values'] == {'spell_power': 17.0}
    assert row['contributions']['spell_power'] == 0.0
