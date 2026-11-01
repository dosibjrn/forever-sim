"""A source rank witness must survive an already-populated optimizer seed queue.

Real Druid L30 SQLite -> GameIR -> canonical talent compiler/frontier.
This is candidate admission, not P2 checkpoint certification.
"""
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import validate_talent_selection
from src.v2.source_bounded_joint_frontier import source_spec_talent_frontier

SOURCE = Path(__file__).resolve().parents[1] / "data/forever/staged_druid_l30_talents_70338.sqlite"


def test_source_rank_witness_is_not_crowded_out_by_input_seed():
    ir = build_game_ir_slice(class_key="druid", level=30, ability_db_path=SOURCE)
    compiled, _ = compile_talent_runtime(ir)
    options = dict(tree_key="balance", minimum_points=5, level=30,
                   bonus_talent_points=0)
    sourced, _ = source_spec_talent_frontier(
        compiled, (), max_frontier=16, **options)
    assert len(sourced) >= 2, "source did not yield distinct legal allocations"
    first_source_witness = sourced[0]
    competing_seed = next(allocation for allocation in sourced
                          if allocation != first_source_witness)
    validate_talent_selection(compiled, competing_seed, level=30)

    # Before the fix, the sole output was competing_seed because input
    # candidates occupied the bounded population before source witnesses.
    frontier, evidence = source_spec_talent_frontier(
        compiled, (competing_seed,), max_frontier=1, **options)
    assert frontier == [first_source_witness]
    assert evidence["source_spec_population"] == 1
    validate_talent_selection(compiled, frontier[0], level=30)
