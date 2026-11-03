"""Transitional GameIR talent-enumeration and budget regression."""
from pathlib import Path
from types import SimpleNamespace
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



def test_large_source_talent_space_fails_closed_without_exhaustive_claim():
    # Class-neutral synthetic ranks preserve the budget regression without
    # depending on the retired staged Druid L30/P2 SQLite snapshot.
    rank=SimpleNamespace(rank=1,modifiers=(object(),))
    talents=tuple(
        SimpleNamespace(id=f"synthetic_druid_{index}",ranks=(rank,),
                        metadata={"row":0},tree_key="feral")
        for index in range(10)
    )
    compiled=SimpleNamespace(
        talents=talents,
        provenance={"talent_tree_rules":{"points_per_row":1}},
    )
    allocations,proof=enumerate_executable_allocations(
        compiled,level=30,max_enumerations=1000
    )
    assert allocations==[]
    assert proof['raw_combinations']==1024
    assert proof['max_enumerations']==1000
    assert proof['status']=='BLOCKED_EXACT_SUBSPACE_ENUMERATION_BUDGET'
    assert not proof['complete_supported_subspace']

