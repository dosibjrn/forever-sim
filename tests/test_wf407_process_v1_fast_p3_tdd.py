"""Approved PROCESS v1: P3 is a fast top-five-by-ilvl scorer smoke, not full source attestation."""
from types import SimpleNamespace
from pathlib import Path

from src.game.checkpoint_p3_smoke import fast_p3_smoke, policy_uses_weapon_damage
from src.game.checkpoint_onepass import run_preflight
from src.rulesets.forever.items.catalogue import ItemRecord
from src.rulesets.forever.items.runtime_selection import available_items, _DEFAULT_DB


# Synthetic positive vectors are ONLY used to test the validator's semantics,
# not evidence of a genuine build-context P3 PASS.
TEST_WEIGHTS = {k: 1.0 for k in (
    'armor','stamina','spirit','agility','strength','intellect','attack_power',
    'spell_power','crit','hit','dodge','parry','mp5','health_regeneration_per_5s',
    'weapon_dps','wand_dps','ranged_weapon_dps','mean_weapon_hit_damage',
    'healing','defense','resistance_arcane','resistance_fire','resistance_frost',
    'resistance_holy','resistance_nature','spell_penetration','weapon_speed')}


def test_real_druid20_selects_exactly_top5_ilvl_not_score_and_needs_real_weights():
    rows=available_items('druid',20)
    report=fast_p3_smoke(class_key='druid',level=20,weights=TEST_WEIGHTS,
                         weight_evidence_kind='TEST_ONLY',weapon_damage_dependent=False)
    assert report['legal_item_count']==len(rows)>1000
    assert report['p3_pass'] is False
    assert 'UNVERIFIED_CONTEXT_WEIGHTS' in report['blockers']
    for slot, section in report['slots'].items():
        expected=sorted([r for r in rows if slot in __import__(
            'src.game.data.forever.source_checkpoint_p3',fromlist=['source_item_slots']).source_item_slots(r)],
            key=lambda r:(-(r.item_level if r.item_level is not None else -1),r.item_id))[:5]
        assert section['selected_ids']==[r.item_id for r in expected]
        assert len(section['selected_ids'])==min(5,section['legal_count'])
        assert all(x['score'] is not None for x in section['items'])


def test_negative_zero_and_missing_context_weights_fail_without_clipping(monkeypatch):
    item=ItemRecord(101,'Armor with stats','chest',item_level=10,required_level=1,
                    armor=50,stamina=5,agility=2)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**k:(item,))
    for change, expected in [({'armor':-1},'NEGATIVE_WEIGHT:armor'),
                             ({'stamina':0},'NONPOSITIVE_RELEVANT_WEIGHT:stamina'),
                             ({'agility':None},'MISSING_WEIGHT:agility')]:
        weights={**TEST_WEIGHTS,**change}
        report=fast_p3_smoke(class_key='druid',level=20,weights=weights,
                             weight_evidence_kind='MEASURED_SOURCE_CONTEXT',
                             weapon_damage_dependent=False)
        assert report['p3_pass'] is False
        assert expected in report['blockers']
        assert not any('CLIPPED' in s for s in report['blockers'])


def test_mean_weapon_hit_only_when_source_policy_executes_weapon_damage():
    weapon=SimpleNamespace(effect_type='weapon_damage')
    direct=SimpleNamespace(effect_type='direct_damage')
    ir=SimpleNamespace(actions=(SimpleNamespace(id='slash',effects=(weapon,)),
                                SimpleNamespace(id='bolt',effects=(direct,))))
    policy=lambda aid:SimpleNamespace(rules=(SimpleNamespace(action_id=aid),))
    assert policy_uses_weapon_damage(ir,policy('slash')) is True
    assert policy_uses_weapon_damage(ir,policy('bolt')) is False
    import pytest
    with pytest.raises(ValueError,match='P3_POLICY_ACTION_NOT_IN_SOURCE_IR'):
        policy_uses_weapon_damage(ir,policy('missing'))


def test_mean_hit_weight_must_be_positive_if_policy_uses_it(monkeypatch):
    weapon=ItemRecord(201,'Mace','two_hand',item_level=14,required_level=1,
                      weapon_min_damage=10,weapon_max_damage=20,weapon_dps=6)
    monkeypatch.setattr('src.game.checkpoint_p3_smoke.available_items',lambda *a,**k:(weapon,))
    bad=fast_p3_smoke(class_key='druid',level=20,weights={**TEST_WEIGHTS,'mean_weapon_hit_damage':0},
                      weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=True)
    assert 'NONPOSITIVE_RELEVANT_WEIGHT:mean_weapon_hit_damage' in bad['blockers']
    good=fast_p3_smoke(class_key='druid',level=20,weights=TEST_WEIGHTS,
                       weight_evidence_kind='MEASURED_SOURCE_CONTEXT',weapon_damage_dependent=True)
    assert good['slots']['weapon']['items'][0]['contributions']['mean_weapon_hit_damage']==15.0


def test_p3_preflight_no_longer_requires_complete_1_255_wowhead_capture(tmp_path):
    report=run_preflight('druid:L20:unrestricted',item_db=Path(_DEFAULT_DB),certificate_dir=tmp_path)
    assert report['source_item_verified'] is False  # true source status stays honest
    assert report['gate_status']['P3']=='NEEDS_CONTEXTUAL_TOP5_ILVL_SMOKE'
    assert report['accepted'] is False
    assert report['gate_status']['P4']=='BLOCKED_BY_P3_SMOKE_NOT_RUN'
