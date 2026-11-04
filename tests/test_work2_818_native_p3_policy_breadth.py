"""Work2 #818: preserve paid-source identity while spending Mage P3 calls on policies."""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    ("prefer_breadth", "expected_calls"),
    [
        (False, [
            ("source-policy", ("spirit", 29.0)),
            ("source-policy", ("spirit", 17.0)),
            ("paid-search-winner", ("spirit", 29.0)),
        ]),
        (True, [
            ("source-policy", ("spirit", 29.0)),
            ("paid-search-winner", ("spirit", 29.0)),
        ]),
    ],
)
def test_opted_in_mage_stat_witness_uses_distinct_paid_policies(
        monkeypatch, prefer_breadth, expected_calls):
    """Skip only the redundant small delta, not either real combat evaluation."""
    import src.game.gear as gear
    import src.v2.source_budgeted_gear as budgeted

    source = SimpleNamespace(
        id="source-policy", provenance={"source": "test"}, rules=())
    winner = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(id="fallback:0", action_id="mage:fireball",
                               conditions=()),))
    ir = SimpleNamespace(id="mage-l30", policies=(source,))
    record = {
        "status": "evaluated", "score_s_per_mob": 10.0,
        "prefix": ["mage:fireball"], "fallback": "mage:fireball",
        "guarded_action": None, "guarded_conditions": [],
        "selected_actions": [{"action_id": "mage:fireball"}],
    }
    assert budgeted.paid_search_winner_baseline(
        winner, record, ("mage:fireball",)) == 10.0

    # The source baseline was already paid while measuring the preceding axis.
    cache = {(id(ir), 30, True, "source-policy", ("mage:fireball",)): 10.0}
    calls = []

    def apply_delta(candidate, stat, delta):
        return SimpleNamespace(id=candidate.id, policies=candidate.policies,
                               delta=(stat, float(delta)))

    def evaluate(candidate, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        delta = getattr(candidate, "delta", None)
        calls.append((policy_override.id, delta))
        seconds = 9.0 if policy_override.id == "paid-search-winner" else 10.0
        return (
            SimpleNamespace(seconds_per_mob=seconds),
            SimpleNamespace(timeline=SimpleNamespace(target_defeated=True),
                            selected_actions=[{"action_id": "mage:fireball"}]),
            {},
        )

    monkeypatch.setattr(gear, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="spirit", level=30, probe_deltas=(29.0, 17.0),
        max_evaluations=4, schedule_incoming_attacks=True,
        baseline_cache=cache, opening_action_ids=("mage:fireball",),
        preferred_policy=winner, baseline_record=record,
        allow_paid_winner_after_nonpositive=True,
        prefer_policy_breadth=prefer_breadth,
    )

    assert calls == expected_calls
    assert result["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
    assert result["policy_source"] == "paid_search_winner"
    assert result["baseline_source"] == "paid_search_winner_record"
    assert result["baseline_reused"] is True
    assert result["paid_evaluations"] == len(expected_calls)
    assert result["baseline_seconds_per_mob"] == 10.0
    assert result["perturbed_seconds_per_mob"] == 9.0
    assert result["delta"] == 29.0
    assert result["weight_s_saved_per_mob_per_unit"] == pytest.approx(1 / 29)
