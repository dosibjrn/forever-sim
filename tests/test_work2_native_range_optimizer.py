"""Forever transport and route-scoring tests; no MythicSim rules revalidated."""
from __future__ import annotations

import pytest

from src.v2.native_range_optimizer import optimize, sampled_levels


ENGINE = "b" * 64


def receipt(level, mob_count, label, seconds, parent=None, recovery=1.0):
    source = (f"{level:02x}{ord(label):02x}" + "a" * 60)
    return {
        "status": "measured_native_world", "level": level, "mob_count": mob_count,
        "targets_killed": mob_count, "rng_mode": "balanced", "iterations": 1,
        "native_prepared": True, "native_world_ack": True,
        "native_full_recovery_paid": True, "recover_to_full": True,
        "terminal_hp": 100.0, "terminal_max_hp": 100.0,
        "terminal_mana": 200.0, "terminal_max_mana": 200.0,
        "elapsed_seconds": seconds, "terminal_recovery_seconds": recovery,
        "source_request_sha256": source, "engine_binary_sha256": ENGINE,
        "native_parent_source_sha256": (
            parent["source_request_sha256"] if parent else None
        ),
        "native_continuity_ack": True if parent else None,
        "native_continuity_from_level": parent["level"] if parent else None,
        "native_intermediate_levels_verified": True,
        "talents": label,
    }


def test_one_invocation_scores_five_levels_and_later_fast_path_beats_first():
    calls = []

    def evaluator(*, level, parent, mob_count, budget, rng_mode, iterations,
                  recover_to_full):
        calls.append((level, parent and parent["talents"], mob_count, budget,
                      rng_mode, iterations, recover_to_full))
        if parent is None:
            # A is first prepared but slower at L20; it wins the cumulative route.
            return [receipt(level, mob_count, "A", 6.0),
                    receipt(level, mob_count, "B", 3.0)]
        return [receipt(level, mob_count, parent["talents"],
                        1.0 if parent["talents"] == "A" else 9.0,
                        parent, recovery=0.5)]

    result = optimize(20, 60, 10, 3, 100, evaluate=evaluator, beam_width=2)
    assert result["status"] == "SAMPLED_NATIVE_PATH_RANKED"
    assert result["sampled_levels_requested"] == [20, 30, 40, 50, 60]
    assert result["sampled_levels_completed"] == [20, 30, 40, 50, 60]
    assert len(calls) == 9  # one high-level call, two continuing source paths
    assert all(c[2] == 3 and c[4:] == ("balanced", 1, True) for c in calls)
    assert len(result["ranked_alternatives"]) == 2
    assert [s["talents"] for s in result["ranked_alternatives"][0]["steps"]] == ["A"] * 5
    assert result["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 10.0
    assert result["ranked_alternatives"][1]["sampled_cumulative_seconds"] == 39.0
    assert result["full_10_60_continuous_leveling_route_proven"] is False
    assert result["native_candidates_examined"] == 10


def test_same_optimizer_accepts_dense_resolution_as_only_arguments():
    observed = []

    def single(*, level, parent, mob_count, budget, rng_mode, iterations,
               recover_to_full):
        observed.append((level, mob_count))
        return [receipt(level, mob_count, "A", 1.0, parent)]

    sparse = optimize(20, 60, 10, 3, 100, evaluate=single)
    assert sparse["sampled_levels_completed"] == [20, 30, 40, 50, 60]
    assert observed == [(x, 3) for x in (20, 30, 40, 50, 60)]
    observed.clear()
    dense = optimize(10, 60, 1, 100, 100, evaluate=single)
    assert dense["sampled_levels_completed"] == list(range(10, 61))
    assert observed == [(level, 100) for level in range(10, 61)]
    assert sampled_levels(20, 59, 10) == (20, 30, 40, 50, 59)


def test_native_paid_full_resource_terminal_time_changes_winner():
    def variants(*, level, parent, mob_count, **kwargs):
        # Fast combat with unpaid debt costs 25 seconds to restore both bars.
        return [receipt(level, mob_count, "A", 30.0, recovery=25.0),
                receipt(level, mob_count, "B", 14.0, recovery=2.0)]

    result = optimize(20, 20, 1, 3, 2, evaluate=variants)
    assert result["ranked_alternatives"][0]["steps"][0]["talents"] == "B"
    assert result["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 14.0
    assert result["ranked_alternatives"][0]["steps"][0]["terminal_recovery_seconds"] == 2.0


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(native_full_recovery_paid=False),
    lambda r: r.update(terminal_mana=199.0),
    lambda r: r.update(terminal_hp=99.0),
    lambda r: r.update(terminal_recovery_seconds=None),
    lambda r: r.update(native_world_ack=False),
    lambda r: r.update(targets_killed=2),
    lambda r: r.update(engine_binary_sha256=None),
    lambda r: r.update(elapsed_seconds=float("nan")),
])
def test_incomplete_or_unpaid_native_receipt_never_scores(mutate):
    def scorer(*, level, parent, mob_count, **kwargs):
        row = receipt(level, mob_count, "A", 10.0)
        mutate(row)
        return [row]

    result = optimize(20, 20, 1, 3, 1, evaluate=scorer)
    assert result["status"] == "NO_COMPARABLE_NATIVE_PATH"
    assert result["sampled_levels_completed"] == []
    assert result["rejected_native_attempts"]
    assert result["native_candidates_examined"] == 1


@pytest.mark.parametrize("field,value", [
    ("native_continuity_ack", False),
    ("native_parent_source_sha256", "f" * 64),
    ("native_intermediate_levels_verified", False),
    ("engine_binary_sha256", "c" * 64),
])
def test_sparse_path_rejects_unobserved_respec_or_cross_binary(field, value):
    def evaluator(*, level, parent, mob_count, **kwargs):
        row = receipt(level, mob_count, "A", 10.0, parent)
        if parent:
            row[field] = value
        return [row]

    result = optimize(20, 30, 10, 3, 2, evaluate=evaluator)
    assert result["status"] == "SAMPLED_NATIVE_PREFIX_ONLY"
    assert result["sampled_levels_completed"] == [20]
    assert len(result["rejected_native_attempts"]) == 1


def test_respects_global_native_candidate_budget_without_overrun():
    invoked = []
    def evaluator(*, level, parent, mob_count, budget, **kwargs):
        invoked.append((level, budget))
        return [receipt(level, mob_count, "A", 10.0, parent)]
    result = optimize(20, 60, 10, 3, 2, evaluate=evaluator)
    assert invoked == [(20, 2), (30, 1)]
    assert result["native_candidates_examined"] == 2
    assert result["sampled_levels_completed"] == [20, 30]


def test_native_evaluator_cannot_override_budget_or_disable_full_recovery():
    def too_many(*, level, parent, mob_count, **kwargs):
        return [receipt(level, mob_count, "A", 10.0),
                receipt(level, mob_count, "B", 10.0)]
    with pytest.raises(ValueError, match="exceeded candidate budget"):
        optimize(20, 20, 1, 3, 1, evaluate=too_many)
    with pytest.raises(ValueError, match="terminal recovery invalid"):
        optimize(20, 20, 1, 3, 1, evaluate=too_many, recover_to_full=False)
