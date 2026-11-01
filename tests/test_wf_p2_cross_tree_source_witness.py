"""Real source GameIR regression: a spec constraint must not hide off-tree ranks.

This is a source-backed candidate-generation test, not a P2 gate certificate.
"""
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import validate_talent_selection
from src.v2.source_bounded_joint_frontier import (
    _executable_rank_prefix,
    _source_unlock_full_point_allocation,
    source_spec_talent_frontier,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/forever/staged_druid_l30_talents_70338.sqlite"


def test_real_druid_source_spec_keeps_off_tree_exact_rank_witness():
    ir = build_game_ir_slice(class_key="druid", level=30, ability_db_path=SOURCE)
    compiled, _ = compile_talent_runtime(ir)
    budget, required = 21, 5
    definitions = {t.id: t for t in compiled.talents}

    # Find an actual executable off-tree rank, not a synthetic talent ID.
    witness = None
    for talent in sorted(compiled.talents, key=lambda t: t.id):
        if talent.tree_key == "balance" or _executable_rank_prefix(talent) < 1:
            continue
        candidate = _source_unlock_full_point_allocation(
            compiled, talent, level=30, target_rank=1,
            preferred_tree="balance", minimum_tree_points=required)
        if candidate is not None:
            witness = (talent, candidate)
            break
    assert witness is not None, "source has no executable cross-tree witness"
    talent, allocation = witness
    assert sum(allocation.values()) == budget
    assert allocation[talent.id] == 1
    assert sum(rank for tid, rank in allocation.items()
               if definitions[tid].tree_key == "balance") >= required
    validate_talent_selection(compiled, allocation, level=30)

    frontier, evidence = source_spec_talent_frontier(
        compiled, (), tree_key="balance", minimum_points=required,
        level=30, bonus_talent_points=0, max_frontier=256)
    assert evidence["source_spec_population"] == len(frontier)
    assert any(a.get(talent.id) == 1 for a in frontier)
    for a in frontier:
        assert sum(a.values()) == budget
        assert sum(rank for tid, rank in a.items()
                   if definitions[tid].tree_key == "balance") >= required
        validate_talent_selection(compiled, a, level=30)


def test_cross_tree_witness_rejects_impossible_source_point_constraint():
    ir = build_game_ir_slice(class_key="druid", level=30, ability_db_path=SOURCE)
    compiled, _ = compile_talent_runtime(ir)
    talent = next(t for t in compiled.talents if _executable_rank_prefix(t) > 0)
    assert _source_unlock_full_point_allocation(
        compiled, talent, level=30, preferred_tree="balance",
        minimum_tree_points=22) is None
    assert _source_unlock_full_point_allocation(
        compiled, talent, level=30, preferred_tree="unknown_tree",
        minimum_tree_points=1) is None
