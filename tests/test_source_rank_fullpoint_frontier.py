"""Active optimizer frontier preserves the requested exact talent rank."""
from types import SimpleNamespace

from src.v2.source_bounded_joint_frontier import (
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


def test_invalid_target_rank_never_fabricates_witness():
    ir = _synthetic_ir()
    for invalid in (0, -1, 6, True):
        assert _source_unlock_full_point_allocation(
            ir, ir.talents[0], level=60, target_rank=invalid,
            preferred_tree="balance", minimum_tree_points=31) is None


