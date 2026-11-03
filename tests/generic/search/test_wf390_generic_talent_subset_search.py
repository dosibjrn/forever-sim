"""Transitional Mage source-backed talent-enumeration regression."""
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talent_subset_search import enumerate_executable_allocations

ROOT=Path(__file__).resolve().parents[3]
MAGE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'


def test_mage_auto_discovers_all_21_source_executable_allocations_and_no_26():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    compiled,coverage=compile_talent_runtime(ir)
    all_21,proof=enumerate_executable_allocations(compiled,level=30)
    assert proof['complete_supported_subspace']
    assert len(all_21)==21
    assert all(sum(a.values())==21 for a in all_21)
    legacy,proof=enumerate_executable_allocations(compiled,level=30,bonus_talent_points=5)
    assert proof['complete_supported_subspace']
    assert legacy==[]  # 26 legal source talents require currently unexecuted ranks.

