"""Work2 #885: exact paid Paladin P3 winner before an unexecutable seed.

These are Forever-owned scheduling/record-identity regressions, not P3 acceptance.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


PREFIX = ("seal_of_fury:1311656", "judgement:20271")


def _winner_record():
    return {
        "status": "evaluated",
        "score_s_per_mob": 10.0,
        "prefix": list(PREFIX),
        "selected_actions": [{"action_id": action} for action in PREFIX],
        "fallback": "judgement:20271",
        "guarded_action": None,
        "guarded_conditions": [],
    }


def _paladin_policy(ir):
    from src.v2.source_stateful_budgeted import _make_policy
    return _make_policy(ir, "judgement:20271")


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(status="blocked"),
    lambda r: r.update(score_s_per_mob=0.0),
    lambda r: r["selected_actions"][0].update(action_id="wrong"),
    lambda r: r.update(prefix=list(reversed(PREFIX))),
    lambda r: r.update(fallback="wrong"),
    lambda r: r.update(guarded_action="seal_of_fury:1311656"),
])
def test_paladin_paid_baseline_refuses_mismatched_record(mutation):
    from src.v2.source_budgeted_gear import paid_search_winner_baseline

    ir = SimpleNamespace(id="paladin-l20")
    policy = _paladin_policy(ir)
    record = deepcopy(_winner_record())
    mutation(record)
    assert paid_search_winner_baseline(policy, record, PREFIX) is None


def test_paladin_verified_winner_gets_first_and_only_paid_probe(monkeypatch):
    """One remaining evaluation must not be lost on the failed source baseline."""
    import src.game.gear as gear
    import src.v2.source_budgeted_gear as budgeted

    source_policy = SimpleNamespace(
        id="paladin:source_seed", provenance={"source": "fixture"}, rules=())
    ir = SimpleNamespace(id="paladin-l20", policies=(source_policy,))
    winner = _paladin_policy(ir)
    record = _winner_record()
    calls = []

    def apply_delta(source_ir, stat, amount):
        assert source_ir is ir
        return SimpleNamespace(
            id=ir.id, policies=ir.policies, delta=(stat, float(amount)))

    def evaluate(source_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        calls.append((policy_override.id, tuple(opening_action_ids),
                      getattr(source_ir, "delta", None)))
        if policy_override.id == "paladin:source_seed":
            raise AssertionError("the unexecutable seed must not be paid first")
        return (
            SimpleNamespace(seconds_per_mob=9.0),
            SimpleNamespace(
                timeline=SimpleNamespace(target_defeated=True),
                selected_actions=[{"action_id": x} for x in PREFIX]),
            {},
        )

    monkeypatch.setattr(gear, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="agility", level=20, probe_deltas=(23.0, 15.0),
        max_evaluations=1, schedule_incoming_attacks=True,
        opening_action_ids=PREFIX, preferred_policy=winner,
        baseline_record=record, prefer_verified_paid_winner_first=True)

    assert result["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert result["policy_source"] == "paid_search_winner"
    assert result["baseline_source"] == "paid_search_winner_record"
    assert result["baseline_reused"] is True
    assert result["baseline_seconds_per_mob"] == 10.0
    assert result["perturbed_seconds_per_mob"] == 9.0
    assert result["delta"] == 23.0
    assert result["paid_evaluations"] == 1
    assert result["attempted_policy_sources"] == ["paid_search_winner"]
    assert calls == [(winner.id, PREFIX, ("agility", 23.0))]


def test_unverified_winner_cannot_preempt_or_consume_budget(monkeypatch):
    import src.v2.source_budgeted_gear as budgeted

    ir = SimpleNamespace(id="paladin-l20", policies=())
    winner = _paladin_policy(ir)
    record = _winner_record()
    record["selected_actions"][1]["action_id"] = "not-judgement"

    def unexpected(*args, **kwargs):
        raise AssertionError("unverified paid policy must not execute")

    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", unexpected)
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="agility", level=20, probe_deltas=(23.0,),
        max_evaluations=1, opening_action_ids=PREFIX,
        preferred_policy=winner, baseline_record=record,
        prefer_verified_paid_winner_first=True)
    assert result["status"] == "NO_POSITIVE_SOURCE_POLICY_WITNESS"
    assert result["paid_evaluations"] == 0


def test_paladin_live_p3_wires_native_item_deltas_and_paid_winner_first(
        monkeypatch):
    """Paladin uses item-sized Agility and never guesses a mana recovery slope."""
    import tools.wf_gate_p3_live as p3
    import src.game.data.forever.registry as registry
    import src.game.checkpoint_p3_smoke as smoke
    import src.game.native_p3_player_context as native_context
    import src.v2.source_budgeted_gear as budgeted

    ir = SimpleNamespace(
        id="paladin-l20", policies=(),
        actor=SimpleNamespace(metadata={"class_key": "paladin", "level": 20,
                                        "base_stats_are_zero_proxy": False}),
        actions=(SimpleNamespace(id="judgement:20271", cooldown_s=0),),
        auto_attacks=())
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-native")
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **kwargs: ir)
    monkeypatch.setattr(p3, "_source_profile_build_ir", lambda *args:
                        (ir, {"profile": "unrestricted"}))
    monkeypatch.setattr(p3, "_p3_stat_witness_priority", lambda *args:
                        ("agility", "intellect"))
    monkeypatch.setattr(native_context, "query_native_player_context",
                        lambda *args: {"source_context_id": "selected-paladin"})
    monkeypatch.setattr(native_context, "apply_native_player_context",
                        lambda ir_arg, context: ir_arg)

    record = _winner_record()
    search = {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [
            {"stage": "source_naked", "values": {"agility": 0.0, "intellect": 0.0}}],
        "attempted": 40, "evaluated": 40,
        "status": "EVALUATED_BOUNDED", "source_context_sha256": "fixture",
    }
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear",
                        lambda **kwargs: search)

    item_calls = []
    def item_smoke(**kwargs):
        item_calls.append(kwargs)
        gained = kwargs["weights"].get("agility", 0.0) > 0
        return {
            "blockers": (["NONPOSITIVE_RELEVANT_WEIGHT:intellect"]
                         if gained else [
                             "NONPOSITIVE_RELEVANT_WEIGHT:agility",
                             "NONPOSITIVE_RELEVANT_WEIGHT:intellect"]),
            "slots": {
                "chest": {"items": [{
                    "item_id": 101, "name": "Native chest",
                    "stat_values": {"agility": 15.0, "intellect": 7.0}}]},
                "ring": {"items": [{
                    "item_id": 102, "name": "Native ring",
                    "stat_values": {"agility": 8.0, "intellect": 6.0}}]},
            },
            "legal_item_count": 2, "tested_item_count": 2, "slot_count": 2,
            "tested_stat_assertions": 210,
            "verified_stat_assertions": 155 if gained else 154,
            "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
        }
    monkeypatch.setattr(smoke, "fast_p3_smoke_for_policy", item_smoke)

    calls = []
    def witness(source_ir, **kwargs):
        calls.append(kwargs)
        assert source_ir is ir
        assert kwargs["stat"] == "agility"
        assert kwargs["probe_deltas"] == (23.0, 15.0)
        assert kwargs["max_evaluations"] == 4
        assert kwargs["prefer_verified_paid_winner_first"] is True
        assert kwargs["baseline_record"] == record
        assert kwargs["preferred_policy"].id.endswith("judgement:20271")
        return {
            "status": "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS",
            "paid_evaluations": 1,
            "weight_s_saved_per_mob_per_unit": 1.0 / 23.0,
        }
    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)

    result = p3.run_live(Path("."), "paladin", 20)
    assert result["status"] == "FAIL"  # Intellect remains unsatisfied.
    assert result["real_source_search_evaluated"] == 41
    assert result["pass_count"] == 155
    assert result["reachability_count"] == 210
    assert len(calls) == 1  # Intellect needs an evidenced combat mana constraint.
    assert calls[0]["probe_deltas"] == (23.0, 15.0)
    assert result["source_policy_stat_witnesses"][0]["probe_delta_sources"][0][
        "items"][0]["item_id"] == 101
    assert len(item_calls) == 2
