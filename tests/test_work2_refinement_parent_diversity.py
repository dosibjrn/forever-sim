"""Regression for Work2 source-paid cold refinement parent diversity.

A short fixed budget should not pay the same talent neighborhood repeatedly
because gear/policy variants with identical talent ranks monopolize the top N.
"""
from src.v2.source_bounded_joint_frontier import _select_refinement_parents


def _entry(rank, talent, gear):
    row = {
        "allocation": talent,
        "equipped_gear": {"slots": {"weapon": {"item_id": gear}}},
        "screen_s_per_mob": float(rank),
        "gear_move": f"gear:{gear}",
        "policy": "retained_apl",
        "policy_signature": "same-apl",
        "recovery": "always",
    }
    return (row, object(), object())


def test_first_parent_is_fastest_but_beam_explores_distinct_talent_allocations():
    rows = [
        _entry(10, {"legal_a": 5}, 1),
        _entry(11, {"legal_a": 5}, 2),
        _entry(12, {"legal_a": 5}, 3),
        _entry(13, {"legal_b": 5}, 1),
        _entry(14, {"legal_c": 5}, 1),
    ]
    selected = _select_refinement_parents(rows, 3)
    assert [row["screen_s_per_mob"] for row, _, _ in selected] == [10., 13., 14.]
    assert [row["allocation"] for row, _, _ in selected] == [
        {"legal_a": 5}, {"legal_b": 5}, {"legal_c": 5}
    ]
    assert _select_refinement_parents(rows, 1)[0] is rows[0]


def test_when_all_talents_match_fill_spare_parent_slots_from_paid_ranked_gear():
    rows = [_entry(10+i, {"same": 3}, i+1) for i in range(4)]
    selected = _select_refinement_parents(rows, 3)
    assert [row["screen_s_per_mob"] for row, _, _ in selected] == [10., 11., 12.]
    assert _select_refinement_parents(rows, 0) == []
    assert _select_refinement_parents([], 3) == []


def test_parent_allocation_diversity_does_not_mutate_input_or_generate_builds():
    rows = [_entry(10, {"a": 3}, 1), _entry(11, {"a": 3}, 2),
            _entry(12, {"b": 3}, 3)]
    before = [dict(row) for row, _, _ in rows]
    selected = _select_refinement_parents(rows, 2)
    assert len(selected) == 2
    assert all(any(chosen is original for original in rows) for chosen in selected)
    assert [row for row, _, _ in rows] == before
