"""Paid persistent 2D event receipts must include every charged runtime phase.

The source-backed combat is real; the travel-only event injection isolates the
previously omitted receipt term. This is not P4/P5/P6 acceptance evidence.
"""
from src.game.data.forever import build_game_ir_slice
from src.game.model import PolicyDefinition, PolicyRuleDefinition
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.runtime import CombatRuntime


def _source_wrath():
    ir = build_game_ir_slice(class_key="druid", level=30)
    wrath = next(action for action in ir.actions if action.family_key == "wrath")
    policy = PolicyDefinition(
        id="work2:travel:accounting", label="Source Wrath",
        rules=(PolicyRuleDefinition(
            id="work2:travel:accounting:rule", action_id=wrath.id),))
    return ir, policy


def test_paid_travel_transitions_are_included_in_complete_two_pull_receipt(monkeypatch):
    ir, policy = _source_wrath()
    original_advance = CombatRuntime.advance_to
    travel_calls = []

    def inject_travel_transitions(self, next_time_s):
        result = original_advance(self, next_time_s)
        if self.target.id == "travel":
            # Isolate a real runtime phase whose transitions were charged to
            # paid_events but omitted from the per-pack receipt.
            self.event_transitions += 3
            travel_calls.append(self.target.id)
        return result

    monkeypatch.setattr(CombatRuntime, "advance_to", inject_travel_transitions)
    result = evaluate_repeated_pulls(
        ir_slice=ir, policy=policy, level=30,
        target_health=20., count=2, pack_size=1,
        schedule_incoming_attacks=False, travel_time_s=1.,
        max_total_events=100000)
    assert len(result.pulls) == 2
    assert travel_calls == ["travel"]
    assert result.pulls[0]["travel_runtime_events"] >= 3
    assert result.pulls[1]["travel_runtime_events"] == 0
    for pull in result.pulls:
        assert pull["event_transitions"] == sum(pull[key] for key in (
            "combat_runtime_events", "maintenance_runtime_events",
            "between_pull_runtime_events", "mode_exit_runtime_events",
            "travel_runtime_events"))
    assert result.pulls[0]["event_transitions"] >= (
        result.pulls[0]["combat_runtime_events"] + 3)


def test_source_two_mob_pack_has_exact_runtime_event_breakdown():
    ir, policy = _source_wrath()
    result = evaluate_repeated_pulls(
        ir_slice=ir, policy=policy, level=30,
        target_health=20., count=2, pack_size=2,
        schedule_incoming_attacks=False, max_total_events=100000)
    assert sum(p["mob_count"] for p in result.pulls) == 2
    assert all(p["pack_all_defeated"] for p in result.pulls)
    for pull in result.pulls:
        assert pull["event_transitions"] == sum(pull[key] for key in (
            "combat_runtime_events", "maintenance_runtime_events",
            "between_pull_runtime_events", "mode_exit_runtime_events",
            "travel_runtime_events"))
