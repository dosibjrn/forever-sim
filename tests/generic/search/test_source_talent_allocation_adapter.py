"""Bounded source-talent allocation adapter used by the joint-frontier optimizer."""

from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talent_subset_search import enumerate_executable_allocations


ROOT = Path(__file__).resolve().parents[3]
MAGE = ROOT / "data/forever/staged_mage_l30_talent_positions_70374.sqlite"


def test_mage_source_allocation_enumeration_uses_executable_ranks_only():
    ir = build_game_ir_slice(class_key="mage", level=30, ability_db_path=MAGE)
    compiled, coverage = compile_talent_runtime(ir)
    allocations, proof = enumerate_executable_allocations(compiled, level=30)

    assert coverage["status"] == "PARTIAL_RUNTIME_COVERAGE"
    assert coverage["rank_with_modifiers"] > 0
    assert proof["status"] == "COMPLETE_SUPPORTED_SUBSPACE_ENUMERATION"
    assert proof["legal_allocations"] == 21
    assert proof["points"] == 21
    assert proof["all_source_talent_ranks_covered"] is False
    assert allocations
    assert all(sum(allocation.values()) == 21 for allocation in allocations)
    assert all(
        all(1 <= rank <= 4 for rank in allocation.values())
        for allocation in allocations
    )


def test_source_allocation_adapter_fails_closed_at_cartesian_budget():
    ir = build_game_ir_slice(class_key="mage", level=30, ability_db_path=MAGE)
    compiled, _coverage = compile_talent_runtime(ir)
    allocations, proof = enumerate_executable_allocations(
        compiled, level=30, max_enumerations=1
    )

    assert allocations == []
    assert proof["raw_combinations"] > 1
    assert proof["max_enumerations"] == 1
    assert proof["status"] == "BLOCKED_EXACT_SUBSPACE_ENUMERATION_BUDGET"
    assert proof["complete_supported_subspace"] is False
