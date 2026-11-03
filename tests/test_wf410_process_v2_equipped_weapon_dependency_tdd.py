"""PROCESS v2: only source-effect dependency on equipped weapon stats mandates weapon weights."""
from types import SimpleNamespace
from src.game.checkpoint_p3_smoke import (
    fast_p3_smoke_for_policy, policy_uses_weapon_damage,
    policy_uses_equipped_weapon_damage, policy_uses_equipped_weapon_mean_hit,
)
from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.mage import build_source_slice as build_mage_source_slice
from src.game.data.forever.priest import build_source_slice as build_priest_source_slice
from src.rulesets.forever.items.catalogue import ItemRecord


def _policy(action_id):
    return SimpleNamespace(id='source:' + action_id,
                           rules=(SimpleNamespace(action_id=action_id),))


def test_real_druid_l20_claw_feral_weapon_effect_is_not_equipped_weapon_stat():
    ir = build_source_slice(20)
    claw = next(a for a in ir.actions if a.family_key == 'claw')
    p = _policy(claw.id)
    assert policy_uses_weapon_damage(ir, p) is True
    effect = next(e for e in claw.effects if e.effect_type == 'weapon_damage')
    assert effect.damage_source.flat_dps > 0
    assert effect.damage_source.dps_stat_id is None
    assert policy_uses_equipped_weapon_damage(ir, p) is False


def test_source_druid_claw_allows_zero_gear_weapon_dps_and_mean_hit(monkeypatch):
    weapon = ItemRecord(94001,'Feral stat mace','two_hand',item_level=21,
                        required_level=19,stamina=5,weapon_dps=10,
                        weapon_min_damage=11,weapon_max_damage=29)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',
                        lambda *args, **kwargs:(weapon,))
    ir = build_source_slice(20)
    claw = next(a for a in ir.actions if a.family_key=='claw')
    result=fast_p3_smoke_for_policy(source_ir=ir,policy=_policy(claw.id),
        class_key='druid',level=20,weights={'stamina':0.1,'weapon_dps':0},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT')
    assert result['p3_pass'],result['blockers']
    assert result['weapon_damage_dependent'] is False
    assert result['equipped_weapon_dps_relevant'] is False
    assert result['slots']['weapon']['items'][0]['score']==0.5


def test_equipped_weapon_dependent_action_requires_both_weights(monkeypatch):
    weapon = ItemRecord(94002,'Strike axe','two_hand',item_level=20,
                        required_level=19,stamina=5,weapon_dps=10,
                        weapon_min_damage=11,weapon_max_damage=29)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',
                        lambda *a,**kw:(weapon,))
    action=SimpleNamespace(id='strike',
        requirements=({'kind':'mode_is','value':'human'},),
        effects=(SimpleNamespace(effect_type='weapon_damage',
            damage_source=SimpleNamespace(kind='equipped_weapon',
                dps_stat_id='weapon_dps',flat_dps=0)),))
    ir=SimpleNamespace(id='melee-ir',
        actor=SimpleNamespace(metadata={'class_key':'warrior'}),
        actions=(action,),auto_attacks=())
    fact=SimpleNamespace(mode_label='Human',source_stat='weapon_dps',
        damage_source_kind='equipped_weapon',weapon_speed_semantics='equipped')
    monkeypatch.setattr('src.game.checkpoint_p3_smoke._weapon_facts_for_ir',
                        lambda _ir:((fact,'human'),))
    p=_policy('strike')
    assert policy_uses_equipped_weapon_damage(ir,p) is True
    assert policy_uses_equipped_weapon_mean_hit(ir,p) is True
    result=fast_p3_smoke_for_policy(source_ir=ir,policy=p,class_key='warrior',
        level=20,weights={'stamina':1,'weapon_dps':0},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT')
    assert 'MISSING_APPLICABLE_DPS_WEIGHT' in result['blockers']
    assert 'MISSING_WEIGHT:mean_weapon_hit_damage' in result['blockers']


def test_caster_wrath_is_not_equipped_weapon_dependent():
    ir=build_source_slice(20)
    wrath=next(a for a in ir.actions if a.family_key=='wrath')
    assert not policy_uses_equipped_weapon_damage(ir,_policy(wrath.id))


def test_negative_weight_still_fails_feral_exception(monkeypatch):
    item=ItemRecord(94003,'Cloak','back',item_level=20,required_level=1,stamina=3)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',
                        lambda *a,**kw:(item,))
    ir=build_source_slice(20)
    claw=next(a for a in ir.actions if a.family_key=='claw')
    result=fast_p3_smoke_for_policy(source_ir=ir,policy=_policy(claw.id),
        class_key='druid',level=20,weights={'stamina':-0.1},
        weight_evidence_kind='MEASURED_SOURCE_CONTEXT')
    assert 'NEGATIVE_WEIGHT:stamina' in result['blockers']


def test_mode_free_auto_attack_without_source_fact_is_not_equipped_weapon_dependency():
    auto=SimpleNamespace(id='war:auto',required_mode_id=None,
        damage_source=SimpleNamespace(kind='qualified_wand_dps_proxy',
                                      dps_stat_id='wand_dps'))
    ir=SimpleNamespace(id='ir',actions=(SimpleNamespace(id='rally',effects=()),),
                       auto_attacks=(auto,))
    assert policy_uses_equipped_weapon_damage(ir,_policy('rally')) is False


def test_mode_free_auto_attack_with_matching_source_fact_is_equipped_weapon_dependency(monkeypatch):
    auto=SimpleNamespace(id='war:auto',required_mode_id=None,
        damage_source=SimpleNamespace(kind='equipped_weapon',dps_stat_id='weapon_dps'))
    ir=SimpleNamespace(id='ir',actor=SimpleNamespace(metadata={'class_key':'warrior'}),
        actions=(SimpleNamespace(id='rally',effects=()),),auto_attacks=(auto,))
    fact=SimpleNamespace(mode_label='*',source_stat='weapon_dps',
        damage_source_kind='equipped_weapon',weapon_speed_semantics='equipped')
    monkeypatch.setattr('src.game.checkpoint_p3_smoke._weapon_facts_for_ir',
                        lambda _ir:((fact,None),))
    p=_policy('rally')
    assert policy_uses_equipped_weapon_damage(ir,p) is True
    assert policy_uses_equipped_weapon_mean_hit(ir,p) is True


def test_qualified_mage_and_priest_wand_proxies_are_not_equipped_weapon_dependencies():
    for ir in (build_mage_source_slice(20),build_priest_source_slice(20)):
        assert ir is not None
        policy=ir.policies[0]
        assert policy_uses_equipped_weapon_damage(ir,policy) is False
        assert policy_uses_equipped_weapon_mean_hit(ir,policy) is False


def test_source_weapon_effect_without_damage_source_fails_closed():
    import pytest
    ir=SimpleNamespace(id='ir',actions=(SimpleNamespace(id='strike',effects=(
        SimpleNamespace(effect_type='weapon_damage',damage_source=None),)),),auto_attacks=())
    with pytest.raises(ValueError,match='P3_UNRESOLVED_WEAPON_DAMAGE_SOURCE'):
        policy_uses_equipped_weapon_damage(ir,_policy('strike'))


def test_mode_bound_equipped_auto_cannot_force_caster_policy_weapon_weight():
    ir=SimpleNamespace(id='ir',actions=(SimpleNamespace(id='bolt',effects=()),),
                       auto_attacks=(SimpleNamespace(id='cat-auto',required_mode_id='cat',
                           damage_source=SimpleNamespace(dps_stat_id='weapon_dps')),))
    assert policy_uses_equipped_weapon_damage(ir,_policy('bolt')) is False
