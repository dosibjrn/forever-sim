"""Bounded class-neutral 100mob optimizer contract, not an acceptance port."""
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talent_subset_search import enumerate_executable_allocations,search_executable_talent_subspace

ROOT=Path(__file__).resolve().parents[1]
MAGE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'
DRUID=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'


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


def test_druid_large_space_fails_closed_instead_of_false_exhaustive_claim():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DRUID)
    compiled,coverage=compile_talent_runtime(ir)
    allocations,proof=enumerate_executable_allocations(compiled,level=30,max_enumerations=1000)
    assert allocations==[]
    assert proof['status']=='BLOCKED_EXACT_SUBSPACE_ENUMERATION_BUDGET'
    assert not proof['complete_supported_subspace']


def test_actual_100mob_crosses_all_boundaries_and_keeps_acceptance_false():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    result=search_executable_talent_subspace(ir=ir,level=30,max_policies=1,max_wall_s=5)
    assert result['enumeration']['legal_allocations']==21
    assert result['attempted_runs']>=1
    assert result['completed_100mob_runs']>=1
    assert result['winner']['mobs_killed']==100
    assert result['source_enemy']['hp']==955
    assert not result['eligible_for_checkpoint_acceptance']
    assert not result['complete_gear_talent_apl_recovery_optimum']
