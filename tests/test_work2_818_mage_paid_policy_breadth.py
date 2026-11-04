"""Work2 #818: budgeted Mage source-policy breadth before verified paid winner.

The production witness still pays every stat probe through the selected scorer.
This tests Forever scheduling and receipts, not Warcraft rules or native validity.
"""
from types import SimpleNamespace

import pytest

import src.game.gear as gear
import src.v2.source_budgeted_gear as budgeted


def test_mage_breadth_reaches_already_paid_winner_under_five_paid_calls(monkeypatch):
    source_a = SimpleNamespace(id="native-source-a", provenance={"source": "fixture"})
    source_b = SimpleNamespace(id="native-source-b", provenance={"source": "fixture"})
    selected = SimpleNamespace(id="search-winner", provenance={"search_performed": True})
    ir = SimpleNamespace(id="mage-l30", policies=(source_a, source_b))
    calls = []

    def apply_delta(ir_arg, stat, delta):
        assert stat == "attack_power"
        return SimpleNamespace(id=ir_arg.id, policies=ir_arg.policies, delta=delta)

    def evaluate(candidate, *, level, policy_override, opening_action_ids,
                 schedule_incoming_attacks):
        assert level == 30 and schedule_incoming_attacks
        delta = getattr(candidate, "delta", None)
        calls.append((policy_override.id, delta))
        score = 9.0 if policy_override.id == "search-winner" and delta else 10.0
        execution = SimpleNamespace(timeline=SimpleNamespace(target_defeated=True))
        return SimpleNamespace(seconds_per_mob=score), execution, {}

    monkeypatch.setattr(gear, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    # The strict record validator has separate regressions; here its accepted
    # output is injected to test the unchanged five-call scheduling contract.
    monkeypatch.setattr(budgeted, "paid_search_winner_baseline",
                        lambda *args: 10.0)

    args = dict(stat="attack_power", level=30, probe_deltas=(20., 5.),
                max_evaluations=5, schedule_incoming_attacks=True,
                preferred_policy=selected, baseline_record={"paid": True},
                allow_paid_winner_after_nonpositive=True)
    found = budgeted.paid_source_policy_stat_witness(
        ir, breadth_first_verified_native_winner=True, **args)
    assert found["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", found
    assert found["policy_source"] == "paid_search_winner"
    assert found["weight_s_saved_per_mob_per_unit"] == 1.0 / 20.
    assert found["paid_evaluations"] == 5
    assert found["attempted_policy_sources"] == [
        "source_ir_policy", "source_ir_policy", "paid_search_winner"]
    assert calls == [
        ("native-source-a", None), ("native-source-a", 20.),
        ("native-source-b", None), ("native-source-b", 20.),
        ("search-winner", 20.),
    ]

    calls.clear()
    unchanged = budgeted.paid_source_policy_stat_witness(
        ir, breadth_first_verified_native_winner=False, **args)
    assert unchanged["status"] == "NO_POSITIVE_SOURCE_POLICY_WITNESS"
    assert unchanged["paid_evaluations"] == 5
    assert ("search-winner", 20.) not in calls


def test_breadth_opt_in_requires_verified_paid_baseline(monkeypatch):
    source = SimpleNamespace(id="source", provenance={"source": "fixture"})
    selected = SimpleNamespace(id="winner", provenance={"search_performed": True})
    ir = SimpleNamespace(id="mage-l30", policies=(source,))
    calls = []
    monkeypatch.setattr(budgeted, "paid_search_winner_baseline",
                        lambda *args: None)

    def evaluate(candidate, *, level, policy_override, opening_action_ids,
                 schedule_incoming_attacks):
        calls.append(policy_override.id)
        result = SimpleNamespace(seconds_per_mob=10.0)
        execution = SimpleNamespace(timeline=SimpleNamespace(target_defeated=True))
        return result, execution, {}

    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    monkeypatch.setattr(gear, "apply_stat_delta",
                        lambda ir_arg, stat, delta: ir_arg)
    row = budgeted.paid_source_policy_stat_witness(
        ir, stat="mp5", level=30, probe_deltas=(20., 5.),
        max_evaluations=3, schedule_incoming_attacks=True,
        preferred_policy=selected, baseline_record={"invalid": True},
        breadth_first_verified_native_winner=True)
    assert row["status"] == "NO_POSITIVE_SOURCE_POLICY_WITNESS", row
    assert row["paid_evaluations"] == 3
    # With no verified reuse, source policy retains both real paid deltas.
    assert calls == ["source", "source", "source"]


@pytest.mark.parametrize("invalid_objective", [
    None, "NATIVE_UNSUPPORTED", "9.0", True,
    float("nan"), float("inf"), 0.0,
])
def test_paid_source_witness_ignores_unusable_native_probe_objective_but_keeps_budget(
        monkeypatch, invalid_objective):
    """Native refusal/invalid objective costs a paid call, not an invented weight."""
    source = SimpleNamespace(id="source-mage", provenance={"source": "fixture"})
    ir = SimpleNamespace(id="mage-l30", policies=(source,))
    calls = []

    def evaluate(candidate, *, level, policy_override, opening_action_ids,
                 schedule_incoming_attacks):
        assert level == 30 and schedule_incoming_attacks
        delta = getattr(candidate, "delta", None)
        calls.append(delta)
        seconds = 10.0 if delta is None else (invalid_objective if delta == 20.0 else 9.0)
        return (SimpleNamespace(seconds_per_mob=seconds),
                SimpleNamespace(timeline=SimpleNamespace(target_defeated=True)), {})

    monkeypatch.setattr(gear, "apply_stat_delta",
                        lambda ir_arg, stat, delta: SimpleNamespace(
                            id=ir_arg.id, policies=ir_arg.policies, delta=delta))
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)

    witness = budgeted.paid_source_policy_stat_witness(
        ir, stat="mp5", level=30, probe_deltas=(20.0, 5.0),
        max_evaluations=3)
    assert calls == [None, 20.0, 5.0]
    assert witness["paid_evaluations"] == 3
    assert witness["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
    assert witness["delta"] == 5.0
    assert witness["baseline_seconds_per_mob"] == 10.0
    assert witness["perturbed_seconds_per_mob"] == 9.0
    assert witness["weight_s_saved_per_mob_per_unit"] == 0.2


@pytest.mark.parametrize("invalid_objective", [
    None, "NATIVE_UNSUPPORTED", "9.0", True,
    float("nan"), float("inf"), 0.0,
])
def test_unusable_paid_source_baseline_is_charged_and_classified(
        monkeypatch, invalid_objective):
    """A source kill with no numerical objective is not a paid stat baseline."""
    source = SimpleNamespace(id="source-mage", provenance={"source": "fixture"})
    ir = SimpleNamespace(id="mage-l30", policies=(source,))
    calls = []

    def evaluate(candidate, *, level, policy_override, opening_action_ids,
                 schedule_incoming_attacks):
        calls.append(policy_override.id)
        return (SimpleNamespace(seconds_per_mob=invalid_objective),
                SimpleNamespace(timeline=SimpleNamespace(target_defeated=True)), {})

    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    witness = budgeted.paid_source_policy_stat_witness(
        ir, stat="spirit", level=30, max_evaluations=2)
    assert calls == ["source-mage"]
    assert witness["status"] == "NO_POSITIVE_SOURCE_POLICY_WITNESS"
    assert witness["paid_evaluations"] == 1
    assert witness["baseline_failures"][0]["reason"] == (
        "BASELINE_NONPOSITIVE_OR_NONFINITE_OBJECTIVE")
    assert witness["attempted_policies"] == []


@pytest.mark.parametrize("invalid_objective", [
    None, "NATIVE_UNSUPPORTED", "9.0", True,
    float("nan"), float("inf"), 0.0,
])
def test_invalid_finished_naked_stat_probe_objective_is_not_measured(
        monkeypatch, invalid_objective):
    """Even a defeated target cannot justify an unscored stat derivative."""
    monkeypatch.setattr(budgeted, "_make_policy", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        budgeted, "_policy_combat_evaluation",
        lambda *args, **kwargs: (
            SimpleNamespace(seconds_per_mob=invalid_objective),
            SimpleNamespace(timeline=SimpleNamespace(target_defeated=True),
                            selected_actions=()), {}))
    result = budgeted._fixed_opening_score(
        SimpleNamespace(), {"fallback": "source-spell", "prefix": ()},
        level=30, incoming=True)
    assert result is None



@pytest.mark.parametrize("invalid_score", [
    None, "NATIVE_UNSUPPORTED", "10.0", True, False,
    float("nan"), float("inf"), float("-inf"), 0.0, -1.0,
])
def test_paid_search_winner_refuses_coerced_baseline_receipt(invalid_score):
    """Only a real numeric paid winner may be reused for stat perturbations."""
    winner = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted",
                    "search_performed": True},
        rules=(SimpleNamespace(id="fallback:0", action_id="mage:fireball",
                               conditions=()),))
    receipt = {
        "status": "evaluated",
        "score_s_per_mob": invalid_score,
        "prefix": ["mage:fireball"],
        "fallback": "mage:fireball",
        "guarded_action": None,
        "guarded_conditions": [],
        "selected_actions": [{"action_id": "mage:fireball"}],
    }
    assert budgeted.paid_search_winner_baseline(
        winner, receipt, ("mage:fireball",)) is None
    # The same exact paid policy and action receipt remains reusable when
    # its genuine measured objective is a finite positive number.
    receipt["score_s_per_mob"] = 10.0
    assert budgeted.paid_search_winner_baseline(
        winner, receipt, ("mage:fireball",)) == 10.0
