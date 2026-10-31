"""A named source wand replaces, rather than augments, a scenario wand proxy."""
from dataclasses import replace
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection, executable_gear_stats, apply_stat_delta

ROOT = Path(__file__).resolve().parents[1]
ABILITY = ROOT / 'data/forever/staged_mage_l30_talent_positions_70374.sqlite'


def mage_ir():
    return build_game_ir_slice(class_key='mage', level=30, ability_db_path=ABILITY)


def test_named_wand_is_executable_stat_and_replaces_qualified_proxy():
    ir = mage_ir()
    assert 'wand_dps' in executable_gear_stats(ir, db_path=ABILITY)
    assert ir.actor.base_stats['wand_dps'] != 23.0
    wand = {'slot':'wand', 'item_id':99991, 'weapon_dps':23.0, 'weapon_speed':2.0}
    geared, applied = apply_gear_selection(ir, aggregate_stats={'wand_dps':23.0},
        selected_items=(wand,), db_path=ABILITY)
    assert 'wand_dps' not in applied.unsupported_stats
    assert geared.actor.base_stats['wand_dps'] == pytest.approx(23.0)
    assert geared.auto_attacks[0].damage_source.dps_stat_id == 'wand_dps'
    assert geared.provenance['equipped_stat_dps_replacement'][0]['item_id'] == 99991


def test_named_wand_replacement_changes_with_source_item_not_base_proxy():
    ir=mage_ir()
    w1={'slot':'wand','item_id':99991,'weapon_dps':11.0,'weapon_speed':2.0}
    w2={'slot':'wand','item_id':99992,'weapon_dps':27.0,'weapon_speed':2.0}
    for wand in (w1,w2):
        out,_=apply_gear_selection(ir,aggregate_stats={'wand_dps':wand['weapon_dps']},
            selected_items=(wand,),db_path=ABILITY)
        assert out.actor.base_stats['wand_dps']==pytest.approx(wand['weapon_dps'])
        assert out.auto_attacks[0].swing_time_s==pytest.approx(2.0)


def test_synthetic_wand_sensitivity_remains_additive_without_named_equipment():
    ir=mage_ir()
    changed=apply_stat_delta(ir,'wand_dps',3.0,db_path=ABILITY)
    assert changed.actor.base_stats['wand_dps']==pytest.approx(ir.actor.base_stats['wand_dps']+3.)
    assert 'equipped_stat_dps_replacement' not in changed.provenance


def test_named_wand_missing_or_ambiguous_item_fails_closed():
    ir=mage_ir()
    for items in ((),({'slot':'weapon','item_id':3,'weapon_dps':22.},),
                  ({'slot':'wand','item_id':1,'weapon_dps':22.},
                   {'slot':'wand','item_id':2,'weapon_dps':20.})):
        with pytest.raises(ValueError,match='named equipped stat DPS'):
            apply_gear_selection(ir,aggregate_stats={'wand_dps':22.},
                selected_items=items,db_path=ABILITY)
