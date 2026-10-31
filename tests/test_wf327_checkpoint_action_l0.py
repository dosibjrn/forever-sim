"""Checkpoint source scope, no legal rank quietly assigned zero utility."""
from collections import Counter
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier


def test_druid20_source_rows_are_exhaustively_accounted_for():
    ir=build_game_ir_slice(class_key='druid',level=20)
    r=action_frontier(ir,class_key='druid',level=20)
    assert r['source_index_rows_all_levels']==r['within_level_rows']+r['out_of_level_rows']
    assert sum(r['index_scope_by_type'].values())==len(r['records'])
    assert r['potentially_legal_positive_ranks']>0
    assert r['potential_ranks_with_numeric_or_ir_proxy']>0
    assert r['potential_ranks_without_quantified_effect']>0
    assert r['complete_legal_spell_universe_proven'] is False
    assert r['PASS1'] is False


def test_druid20_legal_universe_excludes_above_level_and_keeps_downranks():
    ir=build_game_ir_slice(class_key='druid',level=20)
    r=action_frontier(ir,class_key='druid',level=20)
    rows={x['spell_id']:x for x in r['records'] if 'spell_id' in x}
    assert rows[5176]['source_rank_hint']==1
    assert rows[5177]['source_rank_hint']==2
    assert rows[5176]['index_features']['direct_damage']>0
    assert rows[5176]['l0_disposition']=='INDEX_NUMERIC_PROXY_UNCERTAIN'
    assert 5179 not in rows  # above the actor level
    assert rows[5176]['legal_combat_spell_proven'] is False
    assert rows[5176]['exploration_priority']=='UNCERTAIN_NOT_ZERO'


def test_druid20_rune_setup_and_talents_not_lumped_into_combat_buttons():
    ir=build_game_ir_slice(class_key='druid',level=20)
    r=action_frontier(ir,class_key='druid',level=20)
    assert r['use_runes'] is False
    assert r['index_scope_by_type']['RUNE_ENGRAVING_DISABLED_BY_DEFAULT']>0
    assert r['index_scope_by_type']['PASSIVE_OR_TALENT_UNRESOLVED']>0
    assert all('l0_disposition' in x for x in r['records'])
    assert all(x['exploration_priority'] != 'ZERO_ASSUMED' for x in r['records'])


def test_checkpoint_parameters_must_match_and_spec_cannot_silently_pass():
    ir=build_game_ir_slice(class_key='druid',level=20)
    with pytest.raises(ValueError,match='MISMATCH'):
        action_frontier(ir,class_key='druid',level=30)
    with pytest.raises(ValueError,match='MISMATCH'):
        action_frontier(ir,class_key='mage',level=20)
    r=action_frontier(ir,class_key='druid',level=20,profile='feral')
    assert r['profile_constraint_applied'] is False
    assert r['PASS1'] is False


def test_source_spell_url_join_recovers_enrage_without_name_fuzzing():
    from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
    ir=build_game_ir_slice(class_key='druid',level=20)
    enrage=next(a for a in ir.actions if a.id=='enrage:5229')
    assert 5229 in _source_spell_ids(enrage)
    r=action_frontier(ir,class_key='druid',level=20)
    enrage_row=next(x for x in r['records'] if x.get('spell_id')==5229)
    assert 'enrage:5229' in enrage_row['ir_action_ids']
