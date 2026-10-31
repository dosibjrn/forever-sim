from dataclasses import replace
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime,compile_talent_candidate
from src.game.checkpoint_pipeline import checkpoint_preflight

ROOT=Path(__file__).resolve().parents[1]
MAGE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'
DRUID=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'


def test_same_compiler_understands_mage_and_druid_source_shapes():
    for cls, db in [('mage',MAGE),('druid',DRUID)]:
        ir=build_game_ir_slice(class_key=cls,level=30,ability_db_path=db)
        compiled,coverage=compile_talent_runtime(ir)
        assert len(compiled.talents)==coverage['talent_count']
        assert coverage['rank_count'] == coverage['rank_with_modifiers']+coverage['rank_missing_executor']
        assert coverage['rank_count'] >= 100
        assert coverage['eligible_for_checkpoint_acceptance'] is False
        assert coverage['full_talent_execution_certified'] is False
    assert coverage['rank_with_modifiers'] > 0


def test_actual_complete_21_point_source_build_executable_but_not_optimum():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    allocation={'improved_frostbolt':5,'elemental_precision':5,'ice_shards':5,
                'piercing_ice':3,'frost_channeling':3}
    selected,result=compile_talent_candidate(ir,selection=allocation,level=30)
    assert selected is not None
    assert result['spent_points']==21
    assert result['status']=='EXECUTABLE_CANDIDATE_DIAGNOSTIC'
    assert result['eligible_for_checkpoint_acceptance'] is False
    assert next(a for a in selected.actions if a.family_key=='frostbolt').cast_time_s == pytest.approx(2.5)


def test_26_point_legal_but_unexecuted_ranks_are_explicitly_blocked():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    selection={'improved_frostbolt':5,'elemental_precision':5,'ice_shards':5,
               'piercing_ice':3,'frost_channeling':3,'frostbite':3,'permafrost':2}
    selected,report=compile_talent_candidate(ir,selection=selection,level=30,bonus_talent_points=5)
    assert selected is None
    assert report['status']=='BLOCKED_SELECTED_TALENT_RANK_UNEXECUTABLE'
    assert {r['talent_id'] for r in report['missing']}=={'frostbite','permafrost'}


def test_class_neutral_semantics_compile_nature_scope_without_druid_switch():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DRUID)
    # Synthetic semantic-fidelity test only: not a source observation or scorer.
    t=next(t for t in ir.talents if t.ranks)
    r=t.ranks[0]
    rank=replace(r,modifiers=(),provenance={'checkpoint_source_l0':{
        'expected_clause_count':1,'effects':[{'domain':'nature_damage_bonus_pct',
        'target':'nature_spells','condition':'nature_spell_damage',
        'sourced_value':3.0,'source':'https://example.org/synthetic-test'}]}})
    with_rank=replace(ir,talents=tuple(replace(x,ranks=(rank,*x.ranks[1:])) if x.id==t.id else x for x in ir.talents))
    altered,report=compile_talent_runtime(with_rank)
    assert next(x for x in altered.talents if x.id==t.id).ranks[0].modifiers[0].kind=='effect_damage_pct'


def test_preflight_reports_actual_cross_class_missing_rank_counts():
    for cls,db in [('mage',MAGE),('druid',DRUID)]:
        ir=build_game_ir_slice(class_key=cls,level=30,ability_db_path=db)
        pre=checkpoint_preflight(class_key=cls,level=30,ir=ir)
        coverage=pre['talent_execution_coverage']
        assert coverage['rank_count']>0
        assert coverage['rank_missing_executor']>=0
        assert any(b['scope']=='talents' and 'ranks_missing_executor' in b for b in pre['blockers'])
