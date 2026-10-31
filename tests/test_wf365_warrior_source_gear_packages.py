"""Warrior L30 P3: source-profile gear packages and provisional shield recovery.

A smoke/legality test, NOT a P3 acceptance or a source membership proof.
"""
from __future__ import annotations
import os, sqlite3
from pathlib import Path
import pytest
from src.rulesets.forever.items.runtime_selection import (
    available_items, select_gear, gear_overrides, clear_runtime_item_cache,
)
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0, source_item_l0
from tools.wf363_warrior_l30_gear_stage import stage

@pytest.fixture(scope='module')
def staged(tmp_path_factory):
    path=tmp_path_factory.mktemp('wf365')/'warrior.sqlite'
    result=stage(output=path,provisional=True)
    assert not result['membership_verified_complete']
    return path

@pytest.fixture(autouse=True)
def profile_db(monkeypatch,staged):
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE',str(staged))
    clear_runtime_item_cache()
    yield
    clear_runtime_item_cache()


def test_provisional_source_shield_gap_is_repaired_without_false_acceptance(staged):
    with sqlite3.connect(staged) as db:
        shields=db.execute('''SELECT count(*) FROM item_class_eligibility e
            JOIN items i ON i.item_id=e.item_id
            WHERE e.class_id=1 AND i.armor_type='shield' ''').fetchone()[0]
        assert shields>0
    rows=available_items('warrior',30,required_level_policy='observed')
    assert sum(i.armor_type=='shield' for i in rows)>0
    cert=checkpoint_item_l0(class_key='warrior',level=30)
    assert cert['l0_assessed_count']==cert['legal_item_count']>2800
    assert len(cert['slot_frontiers'])==18
    assert not cert['source_membership_verified'] and not cert['p3_pass']


@pytest.mark.parametrize('role,weapon_hands,offhand',[
    ('warrior_arms',2,None),
    ('warrior_fury',1,'one_hand'),
    ('warrior_protection',1,'shield'),
    ('warrior_unrestricted',1,'one_hand'),
])
def test_three_source_profile_weapon_packages(role,weapon_hands,offhand):
    gear=select_gear('warrior',30,role,required_level_policy='observed',
                     exclude_unknown_item_effects=True)
    assert gear['weapon'].weapon_hands==weapon_hands
    assert gear['ranged'].weapon_type in {'bow','crossbow','gun','thrown'}
    if offhand is None:
        assert 'offhand' not in gear
    elif offhand=='shield':
        assert gear['offhand'].armor_type=='shield'
    else:
        assert gear['offhand'].slot=='one_hand'
        assert gear['offhand'].item_id!=gear['weapon'].item_id
    assert all(not source_item_l0(item)['unresolved_effects'] for item in gear.values())
    assert len({i.item_id for i in gear.values()})==len(gear)


def test_offhand_override_rejects_two_hand_weapon():
    arms=select_gear('warrior',30,'warrior_arms',required_level_policy='observed',
                     exclude_unknown_item_effects=True)
    with gear_overrides({'offhand':arms['weapon'].item_id}):
        with pytest.raises(ValueError,match='offhand-equippable'):
            select_gear('warrior',30,'warrior_arms',required_level_policy='observed')


def test_override_rejects_two_hand_plus_shield():
    arms=select_gear('warrior',30,'warrior_arms',required_level_policy='observed')
    prot=select_gear('warrior',30,'warrior_protection',required_level_policy='observed')
    with gear_overrides({'weapon':arms['weapon'].item_id}):
        with pytest.raises(ValueError,match='TWO_HAND_AND_OFFHAND'):
            select_gear('warrior',30,'warrior_protection',required_level_policy='observed')


def test_unrestricted_is_not_talent_spec_locked():
    from src.rulesets.forever.items.runtime_selection import _source_class_profile
    roles=_source_class_profile('warrior')['gear_selection_roles']
    assert set(roles)=={'warrior_arms','warrior_fury','warrior_protection','warrior_unrestricted'}
    assert all(len(r['proxy_weights'])>=5 for r in roles.values())
    assert all(r['weapon_package'] in {'two_hand','dual_wield','one_hand_shield','best_package'} for r in roles.values())


def test_provisional_role_top5_is_explicitly_uncalibrated_and_never_promoted():
    from tools.wf365_warrior_l30_p3_role_probe import run
    result=run()
    assert result['p3']['status']=='FAIL'
    assert result['p3']['legal_denominator'] is None
    assert result['p3']['provisional_shields']>0
    for role,data in result['roles'].items():
        assert data['slots']['weapon']['heuristic_top5']
        assert data['slots']['ranged']['heuristic_top5']
        if role!='warrior_arms':
            assert data['slots']['offhand']['heuristic_top5']
        for section in data['slots'].values():
            for candidate in section['heuristic_top5']:
                assert candidate['proxy_uncertainty'].startswith('UNCALIBRATED')
                assert candidate['source_url'].startswith('https://')
                assert candidate['stat_contributions'] or section['provisional_items']>0
