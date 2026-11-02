"""P2 exact-rank full-point witnesses must not silently rank up the target.

The synthetic roster exercises the real canonical talent validator; the real
Druid SQLite check below guards against class-specific fixture assumptions.
Neither is a formal P2 PASS claim. This regression is branch-scoped.
"""
from pathlib import Path
from types import SimpleNamespace

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import validate_talent_selection
from src.v2.source_bounded_joint_frontier import (
    _executable_rank_prefix,
    _source_unlock_full_point_allocation,
)


def _synthetic_ir():
    def talent(tid, tree):
        return SimpleNamespace(
            id=tid, tree_key=tree, metadata={"row": 0},
            max_rank=5, prerequisite=None,
            ranks=tuple(SimpleNamespace(rank=n, modifiers=(object(),))
                        for n in range(1, 6)),
        )
    return SimpleNamespace(
        talents=tuple([talent("a_target", "balance")]
                      + [talent(f"b_filler_{i}", "balance") for i in range(7)]
                      + [talent(f"c_filler_{i}", "restoration") for i in range(6)]),
        provenance={"talent_tree_rules": {"points_per_row": 5}},
    )


def test_exact_rank_survives_full_budget_and_spec_fill():
    ir = _synthetic_ir()
    target = ir.talents[0]
    for rank in (1, 2, 3, 4, 5):
        allocation = _source_unlock_full_point_allocation(
            ir, target, level=60, target_rank=rank,
            preferred_tree="balance", minimum_tree_points=31)
        assert allocation is not None, f"no legal full build for rank {rank}"
        assert allocation[target.id] == rank, "full-budget filler overranked target"
        assert sum(allocation.values()) == 51
        assert sum(value for tid, value in allocation.items()
                   if tid == "a_target" or tid.startswith("b_filler_")) >= 31
        validate_talent_selection(ir, allocation, level=60)


def test_invalid_target_rank_never_fabricates_witness():
    ir = _synthetic_ir()
    for invalid in (0, -1, 6, True):
        assert _source_unlock_full_point_allocation(
            ir, ir.talents[0], level=60, target_rank=invalid,
            preferred_tree="balance", minimum_tree_points=31) is None


def test_real_druid_source_exact_rank_witness_when_constructible():
    source = Path(__file__).resolve().parents[1] / "data/forever/staged_druid_l30_talents_70338.sqlite"
    ir = build_game_ir_slice(class_key="druid", level=30, ability_db_path=source)
    compiled, _ = compile_talent_runtime(ir)
    examined = 0
    for talent in compiled.talents:
        if _executable_rank_prefix(talent) < 2:
            continue
        allocation = _source_unlock_full_point_allocation(
            compiled, talent, level=30, target_rank=1,
            preferred_tree="balance", minimum_tree_points=5)
        if allocation is None:
            continue
        examined += 1
        assert allocation[talent.id] == 1
        assert sum(allocation.values()) == 21
        validate_talent_selection(compiled, allocation, level=30)
    assert examined > 0, "source fixture did not produce an exact-rank candidate"
