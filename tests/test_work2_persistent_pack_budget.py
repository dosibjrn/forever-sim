"""Work2: real multi-pack evaluator must enforce its candidate wall/CPU budget.

These are focused runtime regressions, not P4/P5 acceptance or 100-mob proof.
"""
from types import SimpleNamespace

import pytest

from src.game.runtime.simulator import ComputeDeadlineExceeded
from src.v2 import source_persistent_joint_finalists as finalists


def test_2d_pack_passes_candidate_deadlines_to_existing_paid_runtime(monkeypatch):
    from src.game import multi_pull
    observed = {}

    def paid_runtime(**kwargs):
        observed.update(kwargs)
        raise ComputeDeadlineExceeded(2, "CPU")

    monkeypatch.setattr(multi_pull, "evaluate_repeated_pulls", paid_runtime)
    candidate = SimpleNamespace(
        ir=SimpleNamespace(provenance={}), policy=object(), opening=())
    result = finalists.evaluate_persistent_candidate(
        candidate, level=30, mobs=2, pack_size=2,
        max_cpu_s=1.25, max_wall_s=2.5, max_total_events=10)
    assert observed["max_total_events"] == 10
    assert observed["count"] == 2
    assert observed["pack_size"] == 2
    assert observed["max_cpu_s"] == 1.25
    assert observed["max_wall_s"] == 2.5
    assert result["status"] == "BLOCKED_EVALUATION_COMPUTE_BUDGET"
    assert result["mob_completed"] == 0
    assert result["reason"] == "BUDGET_CPU_DEADLINE"


@pytest.mark.parametrize("limit,expected", [
    ({"max_cpu_s": 1e-20}, "BUDGET_CPU_DEADLINE"),
    ({"max_wall_s": 1e-20}, "BUDGET_WALL_DEADLINE"),
])
def test_real_source_pack_stops_before_first_pull_on_exhausted_budget(limit, expected):
    from src.game.data.forever import build_game_ir_slice
    from src.game.model import PolicyDefinition, PolicyRuleDefinition
    from src.game.multi_pull import evaluate_repeated_pulls

    ir = build_game_ir_slice(class_key="druid", level=30)
    wrath = next(a for a in ir.actions if a.family_key == "wrath")
    policy = PolicyDefinition(
        id="work2:budget:wrath", label="Source Wrath",
        rules=(PolicyRuleDefinition(
            id="work2:budget:rule", action_id=wrath.id),))
    with pytest.raises(ComputeDeadlineExceeded, match=expected):
        evaluate_repeated_pulls(
            ir_slice=ir, policy=policy, level=30,
            target_health=20., count=2, pack_size=2,
            schedule_incoming_attacks=False, **limit)


def test_real_source_two_mob_pack_still_completes_with_ample_budget():
    from src.game.data.forever import build_game_ir_slice
    from src.game.model import PolicyDefinition, PolicyRuleDefinition
    from src.game.multi_pull import evaluate_repeated_pulls

    ir = build_game_ir_slice(class_key="druid", level=30)
    wrath = next(a for a in ir.actions if a.family_key == "wrath")
    policy = PolicyDefinition(
        id="work2:budget:positive", label="Source Wrath",
        rules=(PolicyRuleDefinition(
            id="work2:budget:positive:rule", action_id=wrath.id),))
    result = evaluate_repeated_pulls(
        ir_slice=ir, policy=policy, level=30,
        target_health=20., count=2, pack_size=2,
        schedule_incoming_attacks=False, max_cpu_s=20., max_wall_s=20.)
    assert sum(p["mob_count"] for p in result.pulls) == 2
    assert all(p["pack_all_defeated"] for p in result.pulls)
    assert result.seconds_per_mob > 0


def test_real_pack_rejects_deadline_exhausted_after_last_pack(monkeypatch):
    """Even post-pack state accounting cannot return an over-budget winner."""
    from src.game import multi_pull, recovery
    from src.game.data.forever import build_game_ir_slice
    from src.game.model import PolicyDefinition, PolicyRuleDefinition
    from src.game.runtime import simulator

    # The first three boundary checks are within budget: deadline creation,
    # pack start, and pack completion. Only the final result check expires.
    clock = iter((0, 0, 0, 2_000_000_000))
    monkeypatch.setattr(multi_pull, "monotonic_ns", lambda: next(clock))
    monkeypatch.setattr(simulator, "monotonic_ns", lambda: 0)
    monkeypatch.setattr(recovery, "monotonic_ns", lambda: 0)

    ir = build_game_ir_slice(class_key="druid", level=30)
    wrath = next(a for a in ir.actions if a.family_key == "wrath")
    policy = PolicyDefinition(
        id="work2:budget:final", label="Source Wrath",
        rules=(PolicyRuleDefinition(
            id="work2:budget:final:rule", action_id=wrath.id),))
    with pytest.raises(ComputeDeadlineExceeded, match="BUDGET_WALL_DEADLINE"):
        multi_pull.evaluate_repeated_pulls(
            ir_slice=ir, policy=policy, level=30,
            target_health=20., count=2, pack_size=2,
            schedule_incoming_attacks=False, max_wall_s=1.)


def test_real_source_pack_event_budget_interrupts_combat_not_only_posthoc():
    """The already-supported finalist event ceiling reaches real CombatRuntime."""
    from src.game.data.forever import build_game_ir_slice
    from src.game.model import PolicyDefinition, PolicyRuleDefinition
    from src.game.multi_pull import evaluate_repeated_pulls
    from src.game.runtime.simulator import EventTransitionBudgetExceeded

    ir = build_game_ir_slice(class_key="druid", level=30)
    wrath = next(a for a in ir.actions if a.family_key == "wrath")
    policy = PolicyDefinition(
        id="work2:events:wrath", label="Source Wrath",
        rules=(PolicyRuleDefinition(
            id="work2:events:rule", action_id=wrath.id),))
    # Previously the concurrent finalist received max_total_events but did
    # not pass it to its real paid pack runtime. This must now interrupt the
    # first pack before it can complete, rather than rejecting a 100-mob
    # candidate after every event has already executed.
    with pytest.raises(EventTransitionBudgetExceeded, match="BUDGET_EVENT_TRANSITIONS"):
        evaluate_repeated_pulls(
            ir_slice=ir, policy=policy, level=30,
            target_health=20., count=2, pack_size=2,
            schedule_incoming_attacks=False, max_total_events=1)
    # Same sourced policy still completes when the real event budget permits.
    result = evaluate_repeated_pulls(
        ir_slice=ir, policy=policy, level=30,
        target_health=20., count=2, pack_size=2,
        schedule_incoming_attacks=False, max_total_events=100000)
    assert sum(p["mob_count"] for p in result.pulls) == 2
    assert all(p["pack_all_defeated"] for p in result.pulls)
