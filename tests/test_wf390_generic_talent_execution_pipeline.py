from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime,compile_talent_candidate

ROOT=Path(__file__).resolve().parents[1]
MAGE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'


def test_retained_mage_source_talent_compiler_reports_coverage():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
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
