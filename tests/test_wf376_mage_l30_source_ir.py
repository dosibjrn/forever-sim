"""WF376: Mage L30 source IR and range-aware rank promotion regression."""
from __future__ import annotations
import json
import sqlite3
from src.game.data.forever.registry import build_game_ir_slice, generic_source_level_bounds
from src.game.data.forever.sqlite_talents import DEFAULT_DB


def _source_range(spell_id):
    with sqlite3.connect(DEFAULT_DB) as db:
        row=db.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='mage' AND spell_id=?",(spell_id,)).fetchone()
    assert row is not None
    return float(json.loads(row[0])['envChange']['after']['range'].split()[0])


def test_mage_l30_constructs_source_ir_and_keeps_level20_compatibility():
    assert generic_source_level_bounds('mage') == (10,30)
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DEFAULT_DB,use_runes=False)
    assert ir is not None
    assert ir.actor.metadata['level']==30
    assert {'mana','health'} <= {r.id for r in ir.resources}
    assert ir.policies and ir.auto_attacks
    older=build_game_ir_slice(class_key='mage',level=20,ability_db_path=DEFAULT_DB,use_runes=False)
    assert older is not None and older.actor.metadata['level']==20


def test_mage_l30_source_promoted_frost_fire_ranks_and_ranges():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DEFAULT_DB,use_runes=False)
    assert ir is not None
    actions={a.family_key:a for a in ir.actions if a.family_key in ('fireball','frostbolt','fire_blast')}
    expected={'fireball':8401,'frostbolt':8406,'fire_blast':8412}
    assert set(actions)==set(expected)
    for family,spell_id in expected.items():
        action=actions[family]
        assert action.id.endswith(':'+str(spell_id)),(family,action.id)
        assert action.metadata['range_yards']==_source_range(spell_id)
        assert action.metadata['rank_source']['spell_id']==spell_id
        assert any(x.get('kind')=='minimum_level' for x in action.requirements)
    assert actions['fireball'].costs[0].amount==185
    assert actions['frostbolt'].costs[0].amount==100
    assert actions['fire_blast'].costs[0].amount==165
    assert any('source_rank_movement_slow_unmodeled'==x.get('code') for x in ir.unsupported_semantics)


def test_mage_l30_frost_nova_source_rank_preserves_root_and_frozen():
    from src.game.model.ir import ControlEffect
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DEFAULT_DB,use_runes=False)
    assert ir is not None
    nova=next(a for a in ir.actions if a.family_key=='frost_nova')
    assert nova.id=='frost_nova:865'
    assert nova.costs[0].amount==85
    assert nova.cooldown_s==25
    controls=[e for e in nova.effects if isinstance(e,ControlEffect)]
    assert len(controls)==2
    assert {e.control_id for e in controls}=={'root','frozen'}
    assert all(e.duration_s==8 for e in controls)
    assert nova.metadata['rank_source']['spell_id']==865


def test_rank_control_parser_does_not_invent_freeze_from_unrelated_tooltip():
    from src.game.data.forever.source_rank_overlay import _parsed_effect
    from src.game.model.ir import ControlEffect
    root=ControlEffect('control','root','enemy',8.)
    assert _parsed_effect(root,'Deals 34 frost damage to the target.',{}) is None


def test_rank_promotion_uncertainty_references_selected_exact_source_spell():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DEFAULT_DB,use_runes=False)
    assert ir is not None
    for action in ir.actions:
        source=action.metadata.get('rank_source')
        if not source:
            continue
        for blocker in ir.unsupported_semantics:
            if blocker.get('family') != action.family_key:
                continue
            if blocker.get('code') in ('source_rank_spell_power_coefficient_unverified',
                                       'source_rank_movement_slow_unmodeled',
                                       'source_rank_periodic_scaling_unverified'):
                assert blocker['spell_id']==source['spell_id'],(action.id,blocker)
