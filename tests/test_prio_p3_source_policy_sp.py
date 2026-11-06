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


def test_real_p3_balance_keeps_measured_zero_without_positive_retry():
    result = run_live(ROOT, "druid", 60, spec="balance")
    assert result["status"] == "PASS", result
    assert result["pass_count"] == result["reachability_count"], result
    assert "spell_power" in result["real_measured_stat_weights"]
    assert not any(w["stat"] == "spell_power"
                   for w in result["source_policy_stat_witnesses"]), result
    assert result["behavior_probes_executed"] <= 44

def test_real_unrestricted_l40_p3_preserves_paid_neutral_spirit():
    result = run_live(ROOT, "druid", 40, spec="unrestricted")
    assert result["status"] == "PASS", result
    assert result["real_measured_stat_weights"]["spirit"] == 0.0, result
    assert not any(w["stat"] == "spirit"
                   for w in result["source_policy_stat_witnesses"]), result
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
        policies=(),
        # The paid winner references a real source-IR action. Keep this fixture
        # faithful to production: P3 must reject policies with unknown actions.
        actions=(SimpleNamespace(id="fireball", effects=(), requirements=()),))
    monkeypatch.setattr(registry, "build_game_ir_slice",
                        lambda **kwargs: ir)
    monkeypatch.setattr(
        p3, "_source_profile_build_ir",
        lambda root, source_ir, class_key, level, spec:
            (source_ir, {"profile": spec, "full_point_source_allocation": None}))
    record = {
        "status": "evaluated",
        "fallback": "fireball", "prefix": ["mage:fireball"],
        "score_s_per_mob": 12.5, "guarded_action": None,
        "guarded_conditions": [],
        "selected_actions": [{"action_id": "mage:fireball"}],
    }
    search_result = {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{"stage": "source_naked",
                                 "values": {}}],
        "stat_probe_axis_selection": {"selected_for_paid_probe": ("spell_power",)},
        "attempted": 43, "evaluated": 43, "status": "EVALUATED_BOUNDED",
        "source_context_sha256": "test-source-context",
    }
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear",
                        lambda **kwargs: search_result)
    winner_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(id="fallback:0", action_id="fireball", conditions=()),))
    monkeypatch.setattr(stateful, "_make_policy",
                        lambda *args, **kwargs: winner_policy)
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "native-test-binary")
    import src.game.native_p3_item_options as native_options
    monkeypatch.setattr(
        native_options, "query_native_mage_spell_coefficients",
        lambda _binary: {
            "source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
            "engine_revision": "native-test-revision",
            "spell_power_coefficients": {8401: 0.857},
        },
    )
    monkeypatch.setattr(
        native_options, "apply_native_mage_spell_coefficients",
        lambda source_ir, _facts: (source_ir, [{
            "action_id": "fireball", "spell_id": 8401,
            "spell_power_coefficient": 0.857,
        }]),
    )
    smoke_calls = []

    def native_smoke(**kwargs):
        smoke_calls.append(kwargs)
        return {
            "blockers": ["MISSING_WEIGHT:spell_power"],
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
            "paid_evaluations": 1, "stat": "spell_power",
            "attempted_policies": [],
        }

    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)
    result = p3.run_live(ROOT, "mage", 30, spec="unrestricted")

    assert captured["opening_action_ids"] == ("mage:fireball",)
    assert captured["preferred_policy"] is winner_policy
    assert captured["baseline_record"] is record
    assert captured["max_evaluations"] == 1
    assert captured["probe_deltas"] == (20.0,)
    assert captured["allow_paid_winner_after_nonpositive"] is True
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
        "fallback": "fireball", "prefix": ["mage:fireball"],
        "score_s_per_mob": 12.5, "guarded_action": None,
        "guarded_conditions": [],
    }
    search_result = {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{
            "stage": "source_naked",
            "values": {
                # All these axes were genuinely absent from the paid
                # sensitivity receipt, rather than measured as zero.
            },
        }],
        "attempted": 40, "evaluated": 40, "status": "EVALUATED_BOUNDED",
        "stat_probe_axis_selection": {"selected_for_paid_probe": (
            "spell_power", "intellect", "spirit", "mp5", "agility", "attack_power")},
        "source_context_sha256": "test-source-context",
    }
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear",
                        lambda **kwargs: search_result)
    winner_policy = SimpleNamespace(
        id="paid-search-winner", provenance={}, rules=())
    monkeypatch.setattr(stateful, "_make_policy",
                        lambda *args, **kwargs: winner_policy)
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "native-test-binary")
    import src.game.native_p3_item_options as native_options
    monkeypatch.setattr(
        native_options, "query_native_mage_spell_coefficients",
        lambda _binary: {
            "source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
            "engine_revision": "native-test-revision",
            "spell_power_coefficients": {8401: 0.857},
        },
    )
    monkeypatch.setattr(
        native_options, "apply_native_mage_spell_coefficients",
        lambda source_ir, _facts: (source_ir, []),
    )

    blockers = [
        "MISSING_WEIGHT:agility",
        "MISSING_WEIGHT:attack_power",
        "MISSING_WEIGHT:intellect",
        "MISSING_WEIGHT:mp5",
        "MISSING_WEIGHT:spell_power",
        "MISSING_WEIGHT:spirit",
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
                              tuple(kwargs["probe_deltas"])))
        return {
            "status": "NO_POSITIVE_SOURCE_POLICY_WITNESS",
            "paid_evaluations": kwargs["max_evaluations"],
            "stat": kwargs["stat"],
            "attempted_policies": [],
        }

    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)
    result = p3.run_live(ROOT, "mage", 30, spec="unrestricted")

    # Four paid evaluations remain for genuinely missing executable axes.
    # A selected caster priority must probe Spell Power ahead of Agility.
    assert witness_calls == [("spell_power", 4, (35.0, 20.0))]
    witness = result["source_policy_stat_witnesses"][0]
    assert witness["probe_delta_sources"] == [
        {"kind": "two_distinct_native_item_slots", "delta": 35.0,
         "items": [
             {"slot": "chest", "item_id": 401,
              "name": "Native caster chest", "amount": 20.0},
             {"slot": "ring", "item_id": 402,
              "name": "Native caster ring", "amount": 15.0},
         ]},
        {"kind": "single_native_item", "delta": 20.0,
         "items": [{"slot": "chest", "item_id": 401,
                    "name": "Native caster chest", "amount": 20.0}]},
    ]
    assert result["real_source_search_evaluated"] == 44
    assert result["status"] == "FAIL"


def test_source_policy_witness_reuses_exact_paid_search_winner_baseline(monkeypatch):
    """The paid winner score is reused only for the exact selected policy."""
    from types import SimpleNamespace
    import src.game.gear as gear_module
    import src.v2.source_budgeted_gear as budgeted

    source_policy = SimpleNamespace(
        id="canonical-source-policy", provenance={"source": "fixture"}, rules=())
    preferred_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(
            id="fallback:0", action_id="mage:fireball", conditions=()),))
    # This fixture tests the fallback itself; a separate regression below
    # checks that source-IR item-sized probes retain first opportunity.
    ir = SimpleNamespace(id="mage-l30", policies=())
    record = {
        "status": "evaluated",
        "score_s_per_mob": 10.0,
        "prefix": ["mage:fireball"],
        "fallback": "mage:fireball",
        "guarded_action": None,
        "guarded_conditions": [],
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


def test_native_item_sized_source_probe_precedes_paid_winner_fallback(monkeypatch):
    """Do not spend the last Mage P3 probes before the source Intellect witness."""
    from types import SimpleNamespace
    import src.game.gear as gear_module
    import src.v2.source_budgeted_gear as budgeted

    source_policy = SimpleNamespace(
        id="source-policy", provenance={"source": "fixture"}, rules=())
    preferred_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(
            id="fallback:0", action_id="mage:fireball", conditions=()),))
    ir = SimpleNamespace(id="mage-l30", policies=(source_policy,))
    record = {
        "status": "evaluated", "score_s_per_mob": 10.0,
        "prefix": ["mage:fireball"], "fallback": "mage:fireball",
        "guarded_action": None, "guarded_conditions": [],
        "selected_actions": [{"action_id": "mage:fireball"}],
    }
    calls = []

    def apply_delta(candidate_ir, stat, delta):
        return SimpleNamespace(
            id=candidate_ir.id, policies=candidate_ir.policies,
            delta=(stat, float(delta)))

    def evaluate(candidate_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        delta = getattr(candidate_ir, "delta", None)
        calls.append((policy_override.id, tuple(opening_action_ids), delta))
        if policy_override.id != "source-policy":
            raise AssertionError("winner must not preempt native source probes")
        # Only the second real paid perturbation has a positive derivative.
        seconds = 9.0 if delta == ("intellect", 50.0) else 10.0
        return (
            SimpleNamespace(seconds_per_mob=seconds),
            SimpleNamespace(
                timeline=SimpleNamespace(target_defeated=True),
                selected_actions=[{"action_id": "mage:fireball"}]),
            {},
        )

    monkeypatch.setattr(gear_module, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="intellect", level=30, probe_deltas=(25., 50.),
        max_evaluations=3, schedule_incoming_attacks=True,
        opening_action_ids=("mage:fireball",),
        preferred_policy=preferred_policy, baseline_record=record)

    assert result["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert result["policy_source"] == "source_ir_policy"
    assert result["policy_id"] == "source-policy"
    assert result["delta"] == 50.0
    assert result["paid_evaluations"] == 3
    assert calls == [
        ("source-policy", ("mage:fireball",), None),
        ("source-policy", ("mage:fireball",), ("intellect", 25.0)),
        ("source-policy", ("mage:fireball",), ("intellect", 50.0)),
    ]


def test_paid_winner_fallback_runs_when_source_baseline_fails(monkeypatch):
    """The already-paid winner remains reachable with one real probe left."""
    from types import SimpleNamespace
    import src.game.gear as gear_module
    import src.v2.source_budgeted_gear as budgeted

    source_policy = SimpleNamespace(
        id="source-policy", provenance={"source": "fixture"}, rules=())
    preferred_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(
            id="fallback:0", action_id="mage:fireball", conditions=()),))
    ir = SimpleNamespace(id="mage-l30", policies=(source_policy,))
    record = {
        "status": "evaluated", "score_s_per_mob": 10.0,
        "prefix": ["mage:fireball"], "fallback": "mage:fireball",
        "guarded_action": None, "guarded_conditions": [],
        "selected_actions": [{"action_id": "mage:fireball"}],
    }
    calls = []

    def apply_delta(candidate_ir, stat, delta):
        return SimpleNamespace(
            id=candidate_ir.id, policies=candidate_ir.policies,
            delta=(stat, float(delta)))

    def evaluate(candidate_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        delta = getattr(candidate_ir, "delta", None)
        calls.append((policy_override.id, tuple(opening_action_ids), delta))
        if policy_override.id == "source-policy":
            return None, None, {}
        seconds = 9.0 if policy_override.id == "paid-search-winner" and delta else 10.0
        return (
            SimpleNamespace(seconds_per_mob=seconds),
            SimpleNamespace(
                timeline=SimpleNamespace(target_defeated=True),
                selected_actions=[{"action_id": "mage:fireball"}]),
            {},
        )

    monkeypatch.setattr(gear_module, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="spell_power", level=30, probe_deltas=(25.,),
        max_evaluations=2, schedule_incoming_attacks=True,
        opening_action_ids=("mage:fireball",),
        preferred_policy=preferred_policy, baseline_record=record)

    assert result["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert result["policy_source"] == "paid_search_winner"
    assert result["baseline_source"] == "paid_search_winner_record"
    assert result["paid_evaluations"] == 2
    assert result["baseline_failures"] == [{
        "policy_id": "source-policy",
        "opening_action_ids": ["mage:fireball"],
        "reason": "BASELINE_NO_EVALUATION",
    }]
    assert result["attempted_policies"] == ["paid-search-winner"]
    assert result["attempted_policy_sources"] == ["paid_search_winner"]
    assert calls == [
        ("source-policy", ("mage:fireball",), None),
        ("paid-search-winner", ("mage:fireball",), ("spell_power", 25.0)),
    ]


def test_source_policy_witness_executes_instead_of_reusing_mismatched_guarded_policy(monkeypatch):
    """A fallback score cannot stand in for a different guarded continuation."""
    from types import SimpleNamespace
    import src.game.gear as gear_module
    import src.v2.source_budgeted_gear as budgeted

    preferred_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(
            SimpleNamespace(id="continuation:guarded", action_id="mage:frostbolt",
                            conditions=()),
            SimpleNamespace(id="fallback:0", action_id="mage:fireball",
                            conditions=()),
        ))
    ir = SimpleNamespace(id="mage-l30", policies=())
    record = {
        "status": "evaluated",
        "score_s_per_mob": 10.0,
        "prefix": ["mage:fireball"],
        "fallback": "mage:fireball",
        "guarded_action": "mage:fireball",
        "guarded_conditions": [],
        "selected_actions": [{"action_id": "mage:fireball"}],
    }
    calls = []

    def apply_delta(candidate_ir, stat, delta):
        return SimpleNamespace(
            id=candidate_ir.id, policies=candidate_ir.policies,
            delta=(stat, float(delta)))

    def evaluate(candidate_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        delta = getattr(candidate_ir, "delta", None)
        calls.append((tuple(opening_action_ids), delta))
        seconds = 10.0 if delta is None else 9.0
        return (
            SimpleNamespace(seconds_per_mob=seconds),
            SimpleNamespace(
                timeline=SimpleNamespace(target_defeated=True),
                selected_actions=[{"action_id": "mage:fireball"}]),
            {},
        )

    monkeypatch.setattr(gear_module, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    result = budgeted.paid_source_policy_stat_witness(
        ir, stat="spell_power", level=30, probe_deltas=(5.,),
        max_evaluations=2, schedule_incoming_attacks=True,
        opening_action_ids=("mage:fireball",),
        preferred_policy=preferred_policy, baseline_record=record)

    assert result["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert result["baseline_source"] == "paid_policy_baseline"
    assert result["baseline_reused"] is False
    assert result["paid_evaluations"] == 2
    assert calls == [(("mage:fireball",), None),
                     (("mage:fireball",), ("spell_power", 5.0))]



def test_native_item_stat_probe_deltas_try_largest_source_delta_first():
    from tools.wf_gate_p3_live import _native_item_stat_probe_deltas

    item_check = {
        "slots": {
            "chest": {"items": [{
                "item_id": 401, "name": "Chest", 
                "stat_values": {"intellect": 25.0},
            }]},
            "ring": {"items": [{
                "item_id": 402, "name": "Ring",
                "stat_values": {"intellect": 25.0},
            }]},
        },
    }
    deltas, sources = _native_item_stat_probe_deltas(item_check, "intellect")

    assert deltas == (50.0, 25.0)
    assert [source["kind"] for source in sources] == [
        "two_distinct_native_item_slots", "single_native_item"]
    assert [source["delta"] for source in sources] == [50.0, 25.0]



def _patch_shaman_live_p3(monkeypatch, *, fallback="lightning_bolt:915",
                          applied_rows=None, query_error=None, attempted=43,
                          witness_status="NO_POSITIVE_SOURCE_POLICY_WITNESS",
                          initial_spell_power_weight=0.0,
                          initial_pass_count=66, next_pass_count=67):
    from types import SimpleNamespace
    import src.game.checkpoint_p3_smoke as p3_smoke
    import src.game.data.forever.registry as registry
    import src.v2.source_budgeted_gear as budgeted
    import src.v2.source_stateful_budgeted as stateful
    import src.game.native_p3_item_options as native_options
    import tools.wf_gate_p3_live as p3

    ir = SimpleNamespace(
        actor=SimpleNamespace(metadata={"class_key": "shaman", "level": 20}),
        policies=(),
        actions=(
            SimpleNamespace(id="lightning_bolt:915", cooldown_s=0),
            SimpleNamespace(id="rockbiter:8019", cooldown_s=0),
        ),
        auto_attacks=(),
    )
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **kwargs: ir)
    monkeypatch.setattr(
        p3, "_source_profile_build_ir",
        lambda root, source_ir, class_key, level, spec:
            (source_ir, {"profile": spec, "full_point_source_allocation": None}))
    record = {
        "status": "evaluated",
        "fallback": fallback,
        "prefix": ["rockbiter:8019", "lightning_bolt:915"],
        "score_s_per_mob": 12.5,
        "guarded_action": None,
        "guarded_conditions": [],
        "selected_actions": [
            {"action_id": "rockbiter:8019"},
            {"action_id": "lightning_bolt:915"},
        ],
    }
    search_result = {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{
            "stage": "source_naked",
            "values": {
                "spell_power": initial_spell_power_weight, "intellect": 0.0, "agility": 0.0,
                "attack_power": 0.0, "mp5": 0.0, "spirit": 0.0,
            },
        }],
        "attempted": attempted,
        "evaluated": attempted,
        "status": "EVALUATED_BOUNDED",
        "source_context_sha256": "test-shaman-source-context",
    }
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear",
                        lambda **kwargs: search_result)
    winner_policy = SimpleNamespace(
        id="paid-search-winner",
        provenance={"authority": "source_stateful_budgeted", "search_performed": True},
        rules=(SimpleNamespace(
            id="fallback:0", action_id=fallback, conditions=()),))
    monkeypatch.setattr(stateful, "_make_policy",
                        lambda *args, **kwargs: winner_policy)
    monkeypatch.setattr(budgeted, "paid_search_winner_baseline",
                        lambda *args, **kwargs: 12.5)
    monkeypatch.setattr(p3, "_p3_stat_witness_priority",
                        lambda _ir, _policy: ("spell_power", "intellect", "agility"))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "native-shaman-test-binary")

    def query(_binary):
        if query_error:
            raise native_options.NativeItemOptionsError(query_error)
        return {
            "source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
            "engine_revision": "native-shaman-test-revision",
            "spell_power_coefficients": {915: 0.42},
        }

    if applied_rows is None:
        applied_rows = [{
            "action_id": "lightning_bolt:915",
            "spell_id": 915,
            "spell_power_coefficient": 0.42,
        }]
    monkeypatch.setattr(native_options, "query_native_shaman_spell_coefficients", query)
    monkeypatch.setattr(
        native_options, "apply_native_shaman_lightning_bolt_coefficient",
        lambda source_ir, _facts: (source_ir, applied_rows))

    smoke_calls = []

    def native_smoke(**kwargs):
        smoke_calls.append(kwargs)
        first = len(smoke_calls) == 1
        return {
            "blockers": (
                (["NONPOSITIVE_RELEVANT_WEIGHT:spell_power"]
                 if initial_spell_power_weight == 0.0 else [])
                + ["NONPOSITIVE_RELEVANT_WEIGHT:intellect",
                   "NONPOSITIVE_RELEVANT_WEIGHT:agility"]
                if first else
                ["NONPOSITIVE_RELEVANT_WEIGHT:intellect",
                 "NONPOSITIVE_RELEVANT_WEIGHT:agility"]),
            "slots": {
                "chest": {"items": [{
                    "item_id": 401, "name": "Native Shaman chest",
                    "stat_values": {"spell_power": 20.0},
                }]},
                "ring": {"items": [{
                    "item_id": 402, "name": "Native Shaman ring",
                    "stat_values": {"spell_power": 15.0},
                }]},
            },
            "legal_item_count": 1955,
            "tested_item_count": 85,
            "slot_count": 17,
            "tested_stat_assertions": 204,
            "verified_stat_assertions": (
                initial_pass_count if first else next_pass_count),
            "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
            "native_item_options_status": "ok",
            "native_unverified_candidate_count": 0,
            "native_excluded_non_client_item_count": 3075,
            "native_item_options_source": (
                "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel"
                "+SkillLine+SkillRaceClassInfo"),
        }

    monkeypatch.setattr(p3_smoke, "fast_p3_smoke_for_policy", native_smoke)
    witness_calls = []

    def witness(_ir, **kwargs):
        witness_calls.append(kwargs)
        return {
            "status": witness_status,
            "paid_evaluations": 1,
            "stat": kwargs["stat"],
            "weight_s_saved_per_mob_per_unit": 0.01,
            "attempted_policies": ["forever:shaman:hybrid@20"],
            "attempted_policy_sources": ["source_ir_policy"],
        }

    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)
    return p3, record, winner_policy, smoke_calls, witness_calls


def test_live_shaman_p3_does_not_force_positive_witness_for_measured_zero(monkeypatch):
    p3, _record, _policy, smoke_calls, witness_calls = _patch_shaman_live_p3(
        monkeypatch, fallback="lightning_bolt:915",
        witness_status="MEASURED_POSITIVE_SOURCE_POLICY_WITNESS")
    result = p3.run_live(ROOT, "shaman", 20, spec="unrestricted")
    assert witness_calls == []
    assert len(smoke_calls) == 1
    assert result["source_policy_stat_witnesses"] == []
    assert result["native_spell_coefficients_applied"] == [{
        "action_id": "lightning_bolt:915",
        "spell_id": 915,
        "spell_power_coefficient": 0.42,
    }]
    assert result["native_paid_winner_spell_probe_enabled"] is True
    assert result["native_spell_coefficients_error"] is None
    assert result["real_measured_stat_weights"]["spell_power"] == 0.0
    assert result["reachability_count"] == 204
    assert result["pass_count"] == 66
    assert result["real_source_search_evaluated"] == 43

def test_live_shaman_p3_non_matching_fallback_never_triggers_positive_probe(monkeypatch):
    p3, _record, _policy, smoke_calls, witness_calls = _patch_shaman_live_p3(
        monkeypatch, fallback="rockbiter:8019", attempted=40)
    result = p3.run_live(ROOT, "shaman", 20, spec="unrestricted")
    assert witness_calls == []
    assert len(smoke_calls) == 1
    assert result["source_policy_stat_witnesses"] == []
    assert result["native_spell_coefficients_applied"][0]["action_id"] == (
        "lightning_bolt:915")
    assert result["native_paid_winner_spell_probe_enabled"] is False
    assert result["pass_count"] == 66
    assert result["reachability_count"] == 204

def test_live_shaman_p3_missing_native_coefficient_preserves_66_of_204(monkeypatch):
    p3, _record, _winner_policy, smoke_calls, witness_calls = _patch_shaman_live_p3(
        monkeypatch,
        query_error="P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_COEFFICIENT_UNAVAILABLE",
        attempted=40)

    result = p3.run_live(ROOT, "shaman", 20, spec="unrestricted")

    assert result["status"] == "FAIL"
    assert len(smoke_calls) == 1
    assert witness_calls == []
    assert result["native_spell_coefficients_applied"] == []
    assert result["native_spell_coefficients_error"] == (
        "P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_COEFFICIENT_UNAVAILABLE")
    assert result["native_paid_winner_spell_probe_enabled"] is False
    assert result["real_measured_stat_weights"]["spell_power"] == 0.0
    assert result["reachability_count"] == 204
    assert result["pass_count"] == 66



def test_live_shaman_p3_keeps_already_measured_positive_sensitivity(monkeypatch):
    p3, _record, _policy, smoke_calls, witness_calls = _patch_shaman_live_p3(
        monkeypatch,
        fallback="lightning_bolt:915",
        attempted=33,
        initial_spell_power_weight=0.16382978723404254,
        initial_pass_count=93,
        next_pass_count=94,
        witness_status="MEASURED_POSITIVE_SOURCE_POLICY_WITNESS")
    result = p3.run_live(ROOT, "shaman", 20, spec="unrestricted")
    assert witness_calls == []
    assert len(smoke_calls) == 1
    assert result["source_policy_stat_witnesses"] == []
    assert result["real_measured_stat_weights"]["spell_power"] == 0.16382978723404254
    assert result["native_paid_winner_spell_probe_enabled"] is True
    assert result["reachability_count"] == 204
    assert result["pass_count"] == 93
    assert result["real_source_search_evaluated"] == 33

def test_shaman_native_fallback_does_not_reprobe_already_measured_sp(monkeypatch):
    from types import SimpleNamespace
    import src.game.checkpoint_p3_smoke as p3_smoke
    import src.game.data.forever.registry as registry
    import src.game.native_p3_item_options as native_options
    import src.v2.source_budgeted_gear as budgeted
    import src.v2.source_stateful_budgeted as stateful
    import tools.wf_gate_p3_live as p3

    ir = SimpleNamespace(
        actor=SimpleNamespace(metadata={"class_key": "shaman", "level": 20}),
        policies=(),
        actions=(
            SimpleNamespace(id="lightning_bolt:915", cooldown_s=0,
                            effects=(), requirements=()),
            SimpleNamespace(id="rockbiter:8019", cooldown_s=0,
                            effects=(), requirements=()),
        ),
    )
    monkeypatch.setattr(registry, "build_game_ir_slice",
                        lambda **kwargs: ir)
    monkeypatch.setattr(
        p3, "_source_profile_build_ir",
        lambda root, source_ir, class_key, level, spec:
            (source_ir, {"profile": spec, "full_point_source_allocation": None}))
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "native-test-binary")
    native_facts = {
        "source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
        "engine_revision": "native-shaman-test-revision",
        "spell_power_coefficients": {915: 0.714},
    }
    applied = [{
        "action_id": "lightning_bolt:915",
        "spell_id": 915,
        "spell_power_coefficient": 0.714,
    }]
    monkeypatch.setattr(
        native_options, "query_native_shaman_spell_coefficients",
        lambda _binary: native_facts)
    monkeypatch.setattr(
        native_options, "apply_native_shaman_lightning_bolt_coefficient",
        lambda source_ir, _facts: (source_ir, applied))

    def run_case(fallback):
        prefix = [f"shaman:{fallback}"]
        record = {
            "status": "evaluated",
            "fallback": fallback,
            "prefix": prefix,
            "score_s_per_mob": 12.5,
            "guarded_action": None,
            "guarded_conditions": [],
            "selected_actions": [{"action_id": prefix[0]}],
        }
        search_result = {
            "stages": [{"stage": "source_naked", "winner": record}],
            "sensitivity_history": [{
                "stage": "source_naked",
                "values": {"spell_power": 0.1, "agility": 0.1, "intellect": 0.1},
            }],
            "attempted": 41,
            "evaluated": 41,
            "status": "EVALUATED_BOUNDED",
            "source_context_sha256": "test-shaman-source-context",
        }
        winner_policy = SimpleNamespace(
            id="paid-search-winner",
            provenance={"authority": "source_stateful_budgeted",
                        "search_performed": True},
            rules=(SimpleNamespace(
                id="fallback:0", action_id=fallback, conditions=()),),
        )
        monkeypatch.setattr(budgeted, "run_source_budgeted_gear",
                            lambda **kwargs: search_result)
        monkeypatch.setattr(stateful, "_make_policy",
                            lambda *args, **kwargs: winner_policy)
        monkeypatch.setattr(budgeted, "paid_search_winner_baseline",
                            lambda *args, **kwargs: 12.5)

        smoke_calls = []

        def native_smoke(**kwargs):
            smoke_calls.append(kwargs)
            return {
                "blockers": [],
                "legal_item_count": 1,
                "tested_item_count": 1,
                "slot_count": 1,
                "tested_stat_assertions": 1,
                "verified_stat_assertions": 1,
                "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
                "slots": {"chest": {"items": [{
                    "item_id": 499, "name": "Native robe",
                    "stat_values": {"spell_power": 20.0},
                }]}},
                "native_item_options_status": "ok",
                "native_unverified_candidate_count": 0,
                "native_excluded_non_client_item_count": 3075,
                "native_item_options_source": "mythicsim:test-ItemSparse",
            }

        monkeypatch.setattr(p3_smoke, "fast_p3_smoke_for_policy", native_smoke)
        witness_calls = []

        def witness(_ir, **kwargs):
            witness_calls.append(kwargs)
            return {
                "status": "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS",
                "stat": "spell_power",
                "weight_s_saved_per_mob_per_unit": 0.25,
                "paid_evaluations": 1,
                "policy_id": "paid-search-winner",
                "policy_source": "paid_search_winner",
                "baseline_reused": True,
                "baseline_source": "paid_search_winner_record",
                "probe_deltas": list(kwargs["probe_deltas"]),
            }

        monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)
        result = p3.run_live(ROOT, "shaman", 20, spec="unrestricted")
        return result, record, winner_policy, witness_calls, smoke_calls

    exact, record, winner_policy, calls, smoke_calls = run_case("lightning_bolt:915")
    assert calls == []
    assert exact["native_paid_winner_spell_probe_enabled"] is True
    assert exact["source_policy_stat_witnesses"] == []
    assert exact["real_measured_stat_weights"]["spell_power"] == 0.1
    assert exact["real_source_search_evaluated"] == 41
    assert len(smoke_calls) == 1
    assert exact["behavior_probes_executed"] <= 44

    other, _record, _policy, other_calls, other_smoke_calls = run_case("rockbiter:8019")
    assert other_calls == []
    assert other["native_spell_coefficients_applied"] == applied
    assert other["native_paid_winner_spell_probe_enabled"] is False
    assert other["source_policy_stat_witnesses"] == []
    assert other["real_measured_stat_weights"]["spell_power"] == 0.1
    assert len(other_smoke_calls) == 1
