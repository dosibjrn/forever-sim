"""Regression for source-backed P3 stat relevance across legal policies.

Production IR, canonical Forever SQLite, real gsim CombatRuntime/recovery,
and the unchanged gear stat applicator: no mock scores or fabricated epsilon.
"""
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_gear import paid_source_policy_stat_witness
from tools.wf_gate_p3_live import _source_profile_build_ir, run_live


ROOT = Path(__file__).resolve().parents[1]


def test_real_balance_caster_source_policy_proves_sp_positive():
    original = build_game_ir_slice(class_key="druid", level=60)
    selected, context = _source_profile_build_ir(
        ROOT, original, "druid", 60, "balance")
    assert sum(context["full_point_source_allocation"].values()) == 51

    witness = paid_source_policy_stat_witness(
        selected, stat="spell_power", level=60, probe_deltas=(5., 20.),
        max_evaluations=4, schedule_incoming_attacks=True)
    assert witness["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
    assert witness["weight_s_saved_per_mob_per_unit"] > 0
    assert witness["baseline_seconds_per_mob"] > witness["perturbed_seconds_per_mob"]
    assert witness["paid_evaluations"] <= 4
    assert witness["policy_id"] in {p.id for p in selected.policies}


def test_real_p3_balance_uses_paid_sp_witness_not_epsilon():
    result = run_live(ROOT, "druid", 60, spec="balance")
    assert result["status"] == "PASS", result
    assert result["pass_count"] == result["reachability_count"], result
    witnesses = result["source_policy_stat_witnesses"]
    assert any(w["stat"] == "spell_power"
               and w["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
               and w["weight_s_saved_per_mob_per_unit"] > 0
               for w in witnesses), result
    assert result["real_measured_stat_weights"]["spell_power"] > 0
    assert result["behavior_probes_executed"] <= 44


def test_real_unrestricted_l40_p3_reuses_baseline_to_measure_spirit():
    result = run_live(ROOT, "druid", 40, spec="unrestricted")
    assert result["status"] == "PASS", result
    assert result["real_measured_stat_weights"]["spirit"] > 0, result
    spirit = next(
        witness for witness in result["source_policy_stat_witnesses"]
        if witness["stat"] == "spirit"
    )
    assert spirit["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert spirit["baseline_reused"] is True, result
    assert result["behavior_probes_executed"] <= 44, result


def test_source_policy_witness_retries_with_opening_prefix_and_caches_it(monkeypatch):
    from types import SimpleNamespace
    import src.game.gear as gear_module
    import src.v2.source_budgeted_gear as budgeted

    policy = SimpleNamespace(id="mage-source-policy", provenance={"source": "fixture"})
    ir = SimpleNamespace(id="mage-l30-source", policies=(policy,))
    calls = []

    def apply_delta(candidate_ir, stat, delta):
        return SimpleNamespace(
            id=candidate_ir.id, policies=candidate_ir.policies,
            delta=(stat, float(delta)))

    def evaluate(candidate_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        prefix = tuple(opening_action_ids)
        delta = getattr(candidate_ir, "delta", None)
        calls.append((policy_override.id, prefix, delta))
        if delta is None and not prefix:
            seconds, defeated = 10.0, False
        elif delta is None:
            seconds, defeated = 10.0, True
        else:
            seconds, defeated = 9.0, True
        execution = SimpleNamespace(
            timeline=SimpleNamespace(target_defeated=defeated),
            selected_actions=[{"action_id": action_id} for action_id in prefix],
        )
        return SimpleNamespace(seconds_per_mob=seconds), execution, {}

    monkeypatch.setattr(gear_module, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    cache = {}

    first = budgeted.paid_source_policy_stat_witness(
        ir, stat="spell_power", level=30, probe_deltas=(5., 20.),
        max_evaluations=3, schedule_incoming_attacks=True,
        baseline_cache=cache, opening_action_ids=("mage:fireball",))
    assert first["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", first
    assert first["baseline_reused"] is False
    assert first["baseline_source"] == "paid_policy_baseline"
    assert first["opening_action_ids"] == ["mage:fireball"]
    assert first["attempted_policies"] == ["mage-source-policy"]
    assert first["attempted_policy_sources"] == ["source_ir_policy"]
    assert first["baseline_failures"][0]["reason"] == "BASELINE_TARGET_NOT_DEFEATED"
    assert first["paid_evaluations"] == 3
    assert calls == [
        ("mage-source-policy", (), None),
        ("mage-source-policy", ("mage:fireball",), None),
        ("mage-source-policy", ("mage:fireball",), ("spell_power", 5.0)),
    ]

    second = budgeted.paid_source_policy_stat_witness(
        ir, stat="intellect", level=30, probe_deltas=(5., 20.),
        max_evaluations=1, schedule_incoming_attacks=True,
        baseline_cache=cache, opening_action_ids=("mage:fireball",))
    assert second["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", second
    assert second["baseline_reused"] is True
    assert second["baseline_source"] == "source_policy_baseline_cache"
    assert second["paid_evaluations"] == 1
    assert calls == [
        ("mage-source-policy", (), None),
        ("mage-source-policy", ("mage:fireball",), None),
        ("mage-source-policy", ("mage:fireball",), ("spell_power", 5.0)),
        ("mage-source-policy", ("mage:fireball",), ("intellect", 5.0)),
    ]



def test_source_policy_witness_rejects_unexecuted_opening_prefix(monkeypatch):
    from types import SimpleNamespace
    import src.v2.source_budgeted_gear as budgeted

    policy = SimpleNamespace(id="mage-source-policy", provenance={"source": "fixture"})
    ir = SimpleNamespace(id="mage-l30-source", policies=(policy,))
    calls = []

    def evaluate(candidate_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        prefix = tuple(opening_action_ids)
        calls.append(prefix)
        return (
            SimpleNamespace(seconds_per_mob=10.0),
            SimpleNamespace(
                timeline=SimpleNamespace(target_defeated=bool(prefix)),
                selected_actions=[],
            ),
            {},
        )

    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="spell_power", level=30, probe_deltas=(5.,),
        max_evaluations=2, opening_action_ids=("mage:fireball",))

    assert result["status"] == "NO_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert result["paid_evaluations"] == 2
    assert result["attempted_policies"] == []
    assert [failure["reason"] for failure in result["baseline_failures"]] == [
        "BASELINE_TARGET_NOT_DEFEATED",
        "BLOCKED_PREFIX_NOT_EXECUTED",
    ]
    assert calls == [(), ("mage:fireball",)]

def test_live_p3_passes_winning_opening_prefix_to_source_policy_witness(monkeypatch):
    from types import SimpleNamespace
    import src.game.checkpoint_p3_smoke as p3_smoke
    import src.game.data.forever.registry as registry
    import src.v2.source_budgeted_gear as budgeted
    import src.v2.source_stateful_budgeted as stateful
    import tools.wf_gate_p3_live as p3

    ir = SimpleNamespace(
        actor=SimpleNamespace(metadata={"class_key": "mage", "level": 30}),
        policies=(), actions=())
    monkeypatch.setattr(registry, "build_game_ir_slice",
                        lambda **kwargs: ir)
    monkeypatch.setattr(
        p3, "_source_profile_build_ir",
        lambda root, source_ir, class_key, level, spec:
            (source_ir, {"profile": spec, "full_point_source_allocation": None}))
    record = {
        "status": "evaluated",
        "fallback": "fireball", "prefix": ["mage:fireball"],
        "score_s_per_mob": 12.5,
        "selected_actions": [{"action_id": "mage:fireball"}],
        "guarded_action": None, "guarded_conditions": [],
    }
    search_result = {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{"stage": "source_naked",
                                 "values": {"spell_power": 0.0}}],
        "attempted": 41, "evaluated": 42, "status": "EVALUATED_BOUNDED",
        "source_context_sha256": "test-source-context",
    }
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear",
                        lambda **kwargs: search_result)
    winner_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(id="fallback:0", action_id="fireball"),))
    monkeypatch.setattr(stateful, "_make_policy",
                        lambda *args, **kwargs: winner_policy)
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "native-test-binary")
    smoke_calls = []

    def native_smoke(**kwargs):
        smoke_calls.append(kwargs)
        return {
            "blockers": ["NONPOSITIVE_RELEVANT_WEIGHT:spell_power"],
            "legal_item_count": 1, "tested_item_count": 1,
            "slot_count": 1, "tested_stat_assertions": 1,
            "verified_stat_assertions": 1,
            "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
            "slots": {"chest": {"items": [
                {"item_id": 499, "name": "Native robe",
                 "stat_values": {"spell_power": 20.0}},
            ]}},
            "native_item_options_status": "partial_level_unknown",
            "native_unverified_candidate_count": 2239,
            "native_item_options_source": "mythicsim:test-ItemSparse.RequiredLevel",
        }

    monkeypatch.setattr(p3_smoke, "fast_p3_smoke_for_policy", native_smoke)
    captured = {}

    def witness(_ir, **kwargs):
        captured.update(kwargs)
        return {
            "status": "NO_POSITIVE_SOURCE_POLICY_WITNESS",
            "paid_evaluations": 2, "stat": "spell_power",
            "attempted_policies": [],
        }

    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)
    result = p3.run_live(ROOT, "mage", 30, spec="unrestricted")

    assert captured["opening_action_ids"] == ("mage:fireball",)
    assert captured["probe_deltas"] == (20.0,)
    assert captured["preferred_policy"] is winner_policy
    assert captured["baseline_record"] is record
    assert len(smoke_calls) == 1
    assert smoke_calls[0]["native_options_binary"] == "native-test-binary"
    assert result["item_options_source"] == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    assert result["native_item_options_status"] == "partial_level_unknown"
    assert result["native_unverified_candidate_count"] == 2239
    assert result["real_source_search_evaluated"] == 44


def test_source_policy_witness_uses_last_paid_probe_for_cached_later_policy(monkeypatch):
    """A remaining single evaluation must not be consumed by a fresh baseline."""
    from types import SimpleNamespace
    import src.game.gear as gear_module
    import src.v2.source_budgeted_gear as budgeted

    first = SimpleNamespace(id="uncached-first", provenance={"source": "fixture"})
    second = SimpleNamespace(id="cached-second", provenance={"source": "fixture"})
    ir = SimpleNamespace(id="mage-l30", policies=(first, second))
    cache = {(id(ir), 30, True, "cached-second", ()): 10.0}
    calls = []

    def apply_delta(candidate_ir, stat, delta):
        return SimpleNamespace(id=candidate_ir.id, policies=candidate_ir.policies,
                               delta=(stat, float(delta)))

    def evaluate(candidate_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        calls.append((policy_override.id, getattr(candidate_ir, "delta", None)))
        return (SimpleNamespace(seconds_per_mob=9.0),
                SimpleNamespace(timeline=SimpleNamespace(target_defeated=True)), {})

    monkeypatch.setattr(gear_module, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="spell_power", level=30, probe_deltas=(5.,),
        max_evaluations=1, schedule_incoming_attacks=True, baseline_cache=cache)

    assert result["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert result["baseline_reused"] is True
    assert result["policy_id"] == "cached-second"
    assert result["paid_evaluations"] == 1
    assert calls == [("cached-second", ("spell_power", 5.0))]


def test_live_p3_prioritizes_selected_caster_policy_stat_witnesses(monkeypatch):
    """A hard remaining budget must reach caster damage/resource axes first."""
    from types import SimpleNamespace
    import src.game.checkpoint_p3_smoke as p3_smoke
    import src.game.data.forever.registry as registry
    import src.v2.source_budgeted_gear as budgeted
    import src.v2.source_stateful_budgeted as stateful
    import tools.wf_gate_p3_live as p3

    ir = SimpleNamespace(
        actor=SimpleNamespace(metadata={"class_key": "mage", "level": 30}),
        policies=(), actions=())
    monkeypatch.setattr(registry, "build_game_ir_slice",
                        lambda **kwargs: ir)
    monkeypatch.setattr(
        p3, "_source_profile_build_ir",
        lambda root, source_ir, class_key, level, spec:
            (source_ir, {"profile": spec, "full_point_source_allocation": None}))
    record = {
        "status": "evaluated",
        "fallback": "fireball", "prefix": ["mage:fireball"],
        "score_s_per_mob": 12.5,
        "selected_actions": [{"action_id": "mage:fireball"}],
        "guarded_action": None, "guarded_conditions": [],
    }
    search_result = {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{
            "stage": "source_naked",
            "values": {
                "agility": 0.0, "attack_power": 0.0, "intellect": 0.0,
                "mp5": 0.0, "spell_power": 0.0, "spirit": 0.0,
            },
        }],
        "attempted": 40, "evaluated": 40, "status": "EVALUATED_BOUNDED",
        "source_context_sha256": "test-source-context",
    }
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear",
                        lambda **kwargs: search_result)
    winner_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(id="fallback:0", action_id="fireball"),))
    monkeypatch.setattr(stateful, "_make_policy",
                        lambda *args, **kwargs: winner_policy)
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "native-test-binary")

    blockers = [
        "NONPOSITIVE_RELEVANT_WEIGHT:agility",
        "NONPOSITIVE_RELEVANT_WEIGHT:attack_power",
        "NONPOSITIVE_RELEVANT_WEIGHT:intellect",
        "NONPOSITIVE_RELEVANT_WEIGHT:mp5",
        "NONPOSITIVE_RELEVANT_WEIGHT:spell_power",
        "NONPOSITIVE_RELEVANT_WEIGHT:spirit",
    ]
    monkeypatch.setattr(p3_smoke, "fast_p3_smoke_for_policy", lambda **kwargs: {
        "blockers": blockers,
        "slots": {
            "chest": {"items": [
                {"item_id": 401, "name": "Native caster chest",
                 "stat_values": {"spell_power": 20.0}},
            ]},
            "ring": {"items": [
                {"item_id": 402, "name": "Native caster ring",
                 "stat_values": {"spell_power": 15.0}},
            ]},
            "back": {"items": [
                {"item_id": 403, "name": "Native caster back",
                 "stat_values": {"agility": 10.0}},
            ]},
        },
        "legal_item_count": 1, "tested_item_count": 3, "slot_count": 3,
        "tested_stat_assertions": 6, "verified_stat_assertions": 0,
        "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
        "native_item_options_status": "partial_level_unknown",
        "native_unverified_candidate_count": 2239,
        "native_item_options_source": "mythicsim:test-ItemSparse.RequiredLevel",
    })

    witness_calls = []

    def witness(_ir, **kwargs):
        witness_calls.append((kwargs["stat"], kwargs["max_evaluations"],
                              tuple(kwargs["probe_deltas"]),
                              kwargs["preferred_policy"], kwargs["baseline_record"]))
        return {
            "status": "NO_POSITIVE_SOURCE_POLICY_WITNESS",
            "paid_evaluations": kwargs["max_evaluations"],
            "stat": kwargs["stat"],
            "attempted_policies": [],
        }

    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)
    result = p3.run_live(ROOT, "mage", 30, spec="unrestricted")

    # Four evaluations remain. The old alphabetical order spent them on
    # Agility; the selected caster policy must test Spell Power first.
    assert witness_calls == [("spell_power", 4, (20.0, 35.0),
                               winner_policy, record)]
    witness = result["source_policy_stat_witnesses"][0]
    assert witness["probe_delta_sources"] == [
        {"kind": "single_native_item", "delta": 20.0,
         "items": [{"slot": "chest", "item_id": 401,
                    "name": "Native caster chest", "amount": 20.0}]},
        {"kind": "two_distinct_native_item_slots", "delta": 35.0,
         "items": [
             {"slot": "chest", "item_id": 401,
              "name": "Native caster chest", "amount": 20.0},
             {"slot": "ring", "item_id": 402,
              "name": "Native caster ring", "amount": 15.0},
         ]},
    ]
    assert result["real_source_search_evaluated"] == 44
    assert result["status"] == "FAIL"


def test_source_policy_witness_reuses_paid_search_winner_baseline(monkeypatch):
    """The selected paid winner, not the unrelated seed policy, owns the baseline."""
    from types import SimpleNamespace
    import src.game.gear as gear_module
    import src.v2.source_budgeted_gear as budgeted

    source_policy = SimpleNamespace(
        id="canonical-source-policy", provenance={}, rules=())
    preferred_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(id="fallback:0", action_id="mage:fireball"),))
    ir = SimpleNamespace(id="mage-l30", policies=(source_policy,))
    record = {
        "status": "evaluated",
        "score_s_per_mob": 10.0,
        "prefix": ["mage:fireball"],
        "fallback": "mage:fireball",
        "selected_actions": [{"action_id": "mage:fireball"}],
    }
    calls = []

    def apply_delta(candidate_ir, stat, delta):
        return SimpleNamespace(
            id=candidate_ir.id, policies=candidate_ir.policies,
            delta=(stat, float(delta)))

    def evaluate(candidate_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        calls.append((policy_override.id, tuple(opening_action_ids),
                      getattr(candidate_ir, "delta", None)))
        return (
            SimpleNamespace(seconds_per_mob=9.0),
            SimpleNamespace(
                timeline=SimpleNamespace(target_defeated=True),
                selected_actions=[{"action_id": "mage:fireball"}]),
            {},
        )

    monkeypatch.setattr(gear_module, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    cache = {}
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="spell_power", level=30, probe_deltas=(5., 20.),
        max_evaluations=2, schedule_incoming_attacks=True,
        baseline_cache=cache, opening_action_ids=("mage:fireball",),
        preferred_policy=preferred_policy, baseline_record=record)

    assert result["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert result["policy_id"] == "paid-search-winner"
    assert result["policy_source"] == "paid_search_winner"
    assert result["baseline_source"] == "paid_search_winner_record"
    assert result["baseline_seconds_per_mob"] == 10.0
    assert result["perturbed_seconds_per_mob"] == 9.0
    assert result["baseline_reused"] is True
    assert result["paid_evaluations"] == 1
    assert result["attempted_policy_sources"] == ["paid_search_winner"]
    assert calls == [("paid-search-winner", ("mage:fireball",),
                      ("spell_power", 5.0))]
    assert cache[(id(ir), 30, True, "paid-search-winner",
                  ("mage:fireball",))] == 10.0



def test_paid_winner_baseline_requires_exact_provenance_fallback_and_prefix():
    from types import SimpleNamespace
    from src.v2.source_budgeted_gear import paid_search_winner_baseline_record

    policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(id="fallback:0", action_id="mage:fireball"),),
    )
    record = {
        "status": "evaluated",
        "score_s_per_mob": 10.0,
        "prefix": ["mage:fireball"],
        "fallback": "mage:fireball",
        "selected_actions": [{"action_id": "mage:fireball"}],
    }
    prefix = ("mage:fireball",)
    assert paid_search_winner_baseline_record(policy, record, prefix) == (prefix, 10.0)

    untrusted = SimpleNamespace(id="untrusted", provenance={"source": "fixture"}, rules=policy.rules)
    assert paid_search_winner_baseline_record(untrusted, record, prefix) is None
    assert paid_search_winner_baseline_record(
        policy, {**record, "fallback": "mage:frostbolt"}, prefix) is None
    assert paid_search_winner_baseline_record(
        policy, {**record, "selected_actions": [{"action_id": "mage:frostbolt"}]},
        prefix) is None
