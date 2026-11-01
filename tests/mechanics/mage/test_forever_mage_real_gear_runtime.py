from __future__ import annotations

import pytest

from src.rulesets.forever.classes.mage import engine as mage
from src.rulesets.forever.classes.mage.real_gear import (
    MageGearItem,
    equipped_items,
    observed_snapshot,
    snapshot,
)


def test_effective_level_priority_required_then_quest_midpoint_then_ilvl():
    assert MageGearItem('req','x',99,required_level=13,quest_min_level=1,quest_gray_level=60).effective_level == 13
    assert MageGearItem('quest','x',99,quest_min_level=18,quest_gray_level=31).effective_level == 25
    assert MageGearItem('ilvl','x',25).effective_level == 20


def test_low_level_named_pool_covers_legacy_body_slots_by_20():
    s=snapshot(20)
    required={'head','neck','shoulder','back','chest','wrist','hands','waist','legs','feet','ring1','ring2','weapon','wand'}
    assert required.issubset(s['slots'])
    assert mage.forever_crafted_gear(20)['fallback_slots'] == []


def test_weapon_offhand_legality_never_equips_offhand_with_two_hand_staff():
    for level in range(11,61):
        s=snapshot(level)
        weapon=s['slots'].get('weapon')
        if weapon and weapon['weapon_hands'] == 2:
            assert 'offhand' not in s['slots']
            assert s['hand_setup'] == '2h'


def test_sql_candidate_pool_can_choose_either_legal_hand_package():
    for level in (13,16,20,40,60):
        s=snapshot(level)
        assert s['hand_setup'] in {'1h','1h_offhand','2h'}
        weapon=s['slots'].get('weapon')
        assert weapon is not None
        if s['hand_setup'] == '2h':
            assert weapon['weapon_hands'] == 2
            assert 'offhand' not in s['slots']


def test_snapshot_is_canonical_sqlite_without_modeled_rows():
    observed=observed_snapshot(40)
    selected=snapshot(40)
    assert selected['provenance'] == 'canonical_sqlite_forever_catalogue'
    assert selected['availability_rule'].startswith('canonical SQLite candidates only')
    assert selected['slots'] == observed['slots']
    assert not any(row['name'].startswith('Modeled ') for row in selected['slots'].values())
    assert all(int(row['effective_level']) <= 40 for row in selected['slots'].values())
    assert all(int(row['item_id']) > 0 for row in selected['slots'].values())


def test_level_60_items_remain_literal_sql_rows_with_true_effective_levels():
    s=snapshot(60)
    assert s['provenance'] == 'canonical_sqlite_forever_catalogue'
    assert all(not row['name'].startswith('Modeled ') for row in s['slots'].values())
    assert all(int(row['effective_level']) <= 60 for row in s['slots'].values())
    assert all(int(row['item_id']) > 0 for row in s['slots'].values())


def test_listener_gear_wand_and_combat_wand_progression_are_aligned_at_checkpoints():
    for level in (5,13,17,22,29,46,56,60):
        shown=snapshot(level)['slots']['wand']
        combat=mage.best_wand(level)
        assert shown['name'] == combat.name
        assert shown['wand_dps'] == pytest.approx(combat.dps, abs=.02)


def test_selected_sql_mp5_is_live_in_passive_regen_when_present():
    level=next((l for l in range(10,61) if snapshot(l)['totals']['mp5'] > 0.0), None)
    assert level is not None
    stats=mage.player_stats(level,mage.Talents())
    assert stats.mp5 == pytest.approx(snapshot(level)['totals']['mp5'])
    no_mp5=mage.replace(stats,mp5=0.0)
    cfg=mage.SimConfig()
    state=mage.State(t=0.0,hp=100.0,mana=0.0,max_mana=stats.max_mana,distance=30.0,last_mana_spend=-100.0)
    assert mage._mana_wait_seconds(state,100.0,level,mage.Talents(),stats,cfg) < mage._mana_wait_seconds(state,100.0,level,mage.Talents(),no_mp5,cfg)


def test_real_gear_snapshot_and_runtime_share_int_spi_sp_totals_when_no_fallback():
    level=20
    snap=snapshot(level)
    g=mage.forever_crafted_gear(level)
    assert g['fallback_slots'] == []
    assert g['bonus_intellect'] == pytest.approx(snap['totals']['intellect'])
    assert g['bonus_spirit'] == pytest.approx(snap['totals']['spirit'])
    assert g['spell_power_floor'] == pytest.approx(snap['totals']['spell_power'])
