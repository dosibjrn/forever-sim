"""Work2 #845: reproduce the Paladin L20 P3 naked-search boundary.

The stateful auto continuation is a useful diagnostic, but its current actor
and weapon values are explicitly scenario proxies. Never promote that result
to P3 evidence until a source-backed actor/weapon context replaces them.
"""
import json
from tools.wf_gate_p3_live import _allow_cooldown_fallback_for_profile
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_gear import run_source_budgeted_gear
from src.v2.source_budgeted_prefix import (
    AUTO_ONLY_FALLBACK, source_prefix_envelope, run_source_budgeted_prefix)
from src.v2.source_stateful_budgeted import _make_policy


def test_paladin_l20_stateful_auto_fallback_reproduces_within_44_evaluations():
    ir = build_game_ir_slice(class_key="paladin", level=20)
    result = run_source_budgeted_gear(
        class_key="paladin", level=20, ir_slice=ir,
        max_evaluations=44, initial_search=22, search_per_gear=12,
        max_gear_states=2,
        probe_stats=("agility", "strength", "stamina"),
        probe_deltas=(5.0,),
        schedule_incoming_attacks=True,
        required_level_policy="observed",
        policy_search_backend="stateful",
        stateful_search_auto_fallback=True,
        stateful_use_l1=False,
        max_event_transitions=7000,
    )
    assert result["status"] == "EVALUATED_BOUNDED", result
    assert result["attempted"] <= 44, result
    naked = next(stage for stage in result["stages"]
                 if stage["stage"] == "source_naked")
    winner = naked["winner"]
    assert winner and winner["fallback"] == AUTO_ONLY_FALLBACK, result

    # Prove that the fallback is the existing runtime auto event, not a
    # fabricated action inserted into GameIR.
    policy = _make_policy(
        ir, winner["fallback"],
        guarded_action=winner.get("guarded_action"),
        guarded_conditions=tuple(winner.get("guarded_conditions", ())),
    )
    evaluation, execution, details = _policy_combat_evaluation(
        ir, level=20, policy_override=policy,
        opening_action_ids=tuple(winner["prefix"]),
        schedule_incoming_attacks=True,
    )
    assert evaluation is not None, result
    assert execution.timeline.target_defeated
    assert details["actor_survived"]
    assert any(event.kind == "AutoAttackSwing"
               for event in execution.timeline.events)
    assert AUTO_ONLY_FALLBACK not in {action.id for action in ir.actions}

    # The existing capture explicitly labels both the naked actor and its
    # ordinary weapon DPS/speed as proxies. This is why the result is not
    # eligible to be wired into the P3 production caller.
    assert ir.actor.metadata["base_stats_are_zero_proxy"] is True
    assert ir.actor.state_status == "qualified_native_class_actor_scenario_not_final"
    assert ir.actor.provenance[0]["authority"] == "scenario_proxy_not_source_backed"
    assert ir.actor.provenance[0]["capture_id"] == "wf251_two_classes_2026-10-11"
    auto = next(a for a in ir.auto_attacks if a.owner_actor_id == ir.actor.id)
    assert auto.provenance[0]["capture_id"] == "wf251_two_classes_2026-10-11"
    assert auto.damage_source.flat_dps == 14.0
    assert auto.provenance[0]["caveat"] == (
        "ordinary_melee_auto_and_weapon_speed_scenario_proxy"
    )

    print("PALADIN_L20_STATEFUL_44_DIAGNOSTIC", json.dumps({
        "status": result["status"],
        "attempted": result["attempted"],
        "evaluated": result["evaluated"],
        "source_naked_prefix": winner["prefix"],
        "fallback": winner["fallback"],
        "auto_attack_swing": True,
        "actor_base_stats_proxy": True,
        "weapon_dps_proxy": auto.damage_source.flat_dps,
        "weapon_source_caveat": auto.provenance[0]["caveat"],
    }, sort_keys=True), flush=True)


def test_paladin_l20_real_cooldown_action_is_a_paid_prefix_continuation():
    """The source's Holy Strike may be tried on cooldown; it is not an auto."""
    ir = build_game_ir_slice(class_key="paladin", level=20)
    old = source_prefix_envelope(ir, level=20)
    assert old["fillers"] == (), old
    expanded = source_prefix_envelope(
        ir, level=20, allow_cooldown_fallback=True)
    assert "holy_strike:1866" in expanded["fillers"], expanded
    assert AUTO_ONLY_FALLBACK not in expanded["fillers"]
    assert all(
        action_id in {action.id for action in ir.actions}
        for action_id in expanded["fillers"])
    assert all(
        next(action for action in ir.actions if action.id == action_id).cooldown_s > 0
        for action_id in expanded["fillers"])

    result = run_source_budgeted_prefix(
        class_key="paladin", level=20, ir_slice=ir,
        max_evaluations=12, allow_cooldown_fallback=True)
    assert 0 < result["attempted"] <= 12, result
    assert result["envelope"]["fillers"] == expanded["fillers"], result
    assert all(
        record["fallback"] in expanded["fillers"]
        for record in (*result.get("trials", ()), *result.get("failures", ())))
    # Source cooldown exploration is a real production search change, but the
    # actor/weapon remain explicitly marked as proxies. It is not P3 credit.
    assert ir.actor.metadata["base_stats_are_zero_proxy"] is True


def test_cooldown_fallback_is_scoped_to_paladin_l20_unrestricted_p3():
    assert _allow_cooldown_fallback_for_profile("paladin", 20, "unrestricted")
    assert _allow_cooldown_fallback_for_profile("PALADIN", 20, "UNRESTRICTED")
    assert not _allow_cooldown_fallback_for_profile("hunter", 20, "unrestricted")
    assert not _allow_cooldown_fallback_for_profile("paladin", 19, "unrestricted")
    assert not _allow_cooldown_fallback_for_profile("paladin", 20, "feral")


def _paladin_paid_winner_identity_fixture():
    from types import SimpleNamespace

    prefix = ("seal_of_fury:1311656", "judgement:20271")
    guarded_conditions = ({"kind": "target_health_below", "value": 0.2},)
    policy = SimpleNamespace(
        id="paladin-paid-search-winner",
        provenance={
            "authority": "source_stateful_budgeted",
            "search_performed": True,
        },
        rules=(
            SimpleNamespace(
                id="fallback:0", action_id="judgement:20271", conditions=()),
            SimpleNamespace(
                id="continuation:guarded",
                action_id="holy_strike:1866",
                conditions=guarded_conditions,
            ),
        ),
    )
    record = {
        "status": "evaluated",
        "score_s_per_mob": 12.0,
        "kill_s": 9.5,
        "prefix": list(prefix),
        "selected_actions": [
            {"action_id": prefix[0], "start_time_s": 0.0, "end_time_s": 1.5},
            {"action_id": prefix[1], "start_time_s": 1.5, "end_time_s": 3.0},
        ],
        "fallback": "judgement:20271",
        "guarded_action": "holy_strike:1866",
        "guarded_conditions": [dict(condition) for condition in guarded_conditions],
    }
    return policy, record, prefix


def test_paladin_paid_winner_validator_reports_exact_identity_mismatches():
    from types import SimpleNamespace
    from src.v2.source_budgeted_gear import (
        paid_search_winner_baseline,
        paid_search_winner_baseline_validation,
    )

    policy, record, prefix = _paladin_paid_winner_identity_fixture()
    accepted = paid_search_winner_baseline_validation(policy, record, prefix)
    assert accepted == {"accepted": True, "score": 12.0, "reason": None}
    assert paid_search_winner_baseline(policy, record, prefix) == 12.0

    bad_provenance = SimpleNamespace(
        id=policy.id,
        provenance={"authority": "forever_python", "search_performed": True},
        rules=policy.rules,
    )
    assert paid_search_winner_baseline_validation(
        bad_provenance, record, prefix
    )["reason"] == "POLICY_AUTHORITY_MISMATCH"

    assert paid_search_winner_baseline_validation(
        policy, record, (prefix[0],)
    )["reason"] == "OPENING_ACTION_PREFIX_MISMATCH"

    bad_selected = dict(record)
    bad_selected["selected_actions"] = [
        {"action_id": "wrong:action"}, *record["selected_actions"][1:]
    ]
    assert paid_search_winner_baseline_validation(
        policy, bad_selected, prefix
    )["reason"] == "SELECTED_ACTION_PREFIX_MISMATCH"

    bad_fallback = SimpleNamespace(
        id=policy.id,
        provenance=policy.provenance,
        rules=(
            SimpleNamespace(
                id="fallback:0", action_id="wrong:fallback", conditions=()),
            policy.rules[1],
        ),
    )
    assert paid_search_winner_baseline_validation(
        bad_fallback, record, prefix
    )["reason"] == "POLICY_FALLBACK_ACTION_MISMATCH"

    bad_guarded_action = SimpleNamespace(
        id=policy.id,
        provenance=policy.provenance,
        rules=(
            policy.rules[0],
            SimpleNamespace(
                id="continuation:guarded",
                action_id="wrong:guarded",
                conditions=policy.rules[1].conditions,
            ),
        ),
    )
    assert paid_search_winner_baseline_validation(
        bad_guarded_action, record, prefix
    )["reason"] == "POLICY_GUARDED_ACTION_MISMATCH"

    bad_guarded_conditions = SimpleNamespace(
        id=policy.id,
        provenance=policy.provenance,
        rules=(
            policy.rules[0],
            SimpleNamespace(
                id="continuation:guarded",
                action_id="holy_strike:1866",
                conditions=({"kind": "target_health_below", "value": 0.9},),
            ),
        ),
    )
    assert paid_search_winner_baseline_validation(
        bad_guarded_conditions, record, prefix
    )["reason"] == "POLICY_GUARDED_CONDITIONS_MISMATCH"


def test_paladin_paid_winner_is_attempted_before_unexecutable_source_seed(monkeypatch):
    from types import SimpleNamespace
    import src.game.gear as gear_module
    import src.v2.source_budgeted_gear as budgeted

    policy, record, prefix = _paladin_paid_winner_identity_fixture()
    source_seed = SimpleNamespace(
        id="paladin:source_seed",
        provenance={"source": "source_ir"},
        rules=(),
    )
    ir = SimpleNamespace(id="paladin-l20", policies=(source_seed,))
    calls = []

    def apply_delta(candidate_ir, stat, delta):
        return SimpleNamespace(
            id=candidate_ir.id,
            policies=candidate_ir.policies,
            delta=(stat, float(delta)),
        )

    def evaluate(candidate_ir, *, level, policy_override,
                 opening_action_ids=(), schedule_incoming_attacks=False):
        calls.append((
            policy_override.id,
            tuple(opening_action_ids),
            getattr(candidate_ir, "delta", None),
        ))
        return (
            SimpleNamespace(seconds_per_mob=11.0),
            SimpleNamespace(
                timeline=SimpleNamespace(target_defeated=True),
                selected_actions=[
                    {"action_id": action_id} for action_id in opening_action_ids
                ],
            ),
            {},
        )

    monkeypatch.setattr(gear_module, "apply_stat_delta", apply_delta)
    monkeypatch.setattr(budgeted, "_policy_combat_evaluation", evaluate)
    result = budgeted.paid_source_policy_stat_witness(
        ir,
        stat="agility",
        level=20,
        probe_deltas=(17.0, 10.0),
        max_evaluations=3,
        opening_action_ids=prefix,
        preferred_policy=policy,
        baseline_record=record,
        prefer_paid_search_winner=True,
    )

    assert result["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS", result
    assert result["policy_id"] == policy.id
    assert result["policy_source"] == "paid_search_winner"
    assert result["baseline_source"] == "paid_search_winner_record"
    assert result["baseline_seconds_per_mob"] == 12.0
    assert result["perturbed_seconds_per_mob"] == 11.0
    assert result["baseline_reused"] is True
    assert result["paid_evaluations"] == 1
    assert result["attempted_policies"] == [policy.id]
    assert result["attempted_policy_sources"] == ["paid_search_winner"]
    assert result["baseline_failures"] == []
    assert calls == [(policy.id, prefix, ("agility", 17.0))]


def _run_paladin_p3_live_with_stubs(
        monkeypatch, policy, record, witness, *, initial_mana=612.0):
    from pathlib import Path
    from types import SimpleNamespace
    import src.game.checkpoint_p3_smoke as smoke_module
    import src.game.data.forever.registry as registry
    import src.game.native_p3_player_context as player_context
    import src.v2.source_budgeted_gear as budgeted
    import src.v2.source_stateful_budgeted as stateful
    import tools.wf_gate_p3_live as p3

    source_seed = SimpleNamespace(
        id="paladin:source_seed", provenance={"source": "source_ir"}, rules=())
    action_cost = lambda amount: SimpleNamespace(resource_id="mana", amount=amount)
    actions = (
        SimpleNamespace(
            id="seal_of_fury:1311656", costs=(action_cost(70.0),), effects=(),
            cooldown_s=0.0, gcd_s=1.5,
        ),
        SimpleNamespace(
            id="judgement:20271", costs=(action_cost(80.0),), effects=(),
            cooldown_s=0.0, gcd_s=1.5,
        ),
        SimpleNamespace(
            id="holy_strike:1866", costs=(action_cost(60.0),), effects=(),
            cooldown_s=0.0, gcd_s=1.5,
        ),
    )
    mana_resource = SimpleNamespace(
        id="mana", owner_actor_id="paladin", scope="actor",
        active_by_default=True, initial_amount=float(initial_mana),
        capacity=float(initial_mana), regeneration_per_s=0.0,
        event_gain_rules=(), metadata={"base_mana": 100.0},
    )
    ir = SimpleNamespace(
        id="paladin-l20-fixture",
        actor=SimpleNamespace(
            id="paladin",
            metadata={"class_key": "paladin", "level": 20},
        ),
        policies=(source_seed,),
        actions=actions,
        resources=(mana_resource,),
        auto_attacks=(),
    )
    native_context = {
        "source_context_id": "paladin-native-context-fixture",
        "source_scope": "test-source-context",
        "context_kind": "source_backed_baseline_context_not_full_native_sim_actor",
        "race": "dwarf",
        "base_stats": {"agility": 28.0, "intellect": 32.0},
        "resources": {"max_health": 471.0, "max_mana": 612.0},
        "weapon": {"item_id": 36, "weapon_damage_min": 1.0, "weapon_damage_max": 3.0},
        "unsupported_fields": [],
    }
    item_check = {
        "source": "MYTHICSIM_NATIVE_ITEM_OPTIONS",
        "blockers": [
            "NONPOSITIVE_RELEVANT_WEIGHT:agility",
            "NONPOSITIVE_RELEVANT_WEIGHT:intellect",
        ],
        "legal_item_count": 2303,
        "tested_item_count": 85,
        "slot_count": 17,
        "tested_stat_assertions": 210,
        "verified_stat_assertions": 154,
        "native_item_options_status": "ok",
        "native_unverified_candidate_count": 0,
        "native_excluded_non_client_item_count": 3820,
        "native_item_options_source": (
            "mythicsim:data/items.jsonl+client:ItemSparse.RequiredLevel+"
            "SkillLine+SkillRaceClassInfo"
        ),
        "slots": {
            "head": {"items": [{
                "item_id": 100, "name": "Native Agility Hood",
                "stat_values": {"agility": 10.0, "intellect": 4.0},
            }]},
            "chest": {"items": [{
                "item_id": 101, "name": "Native Agility Chest",
                "stat_values": {"agility": 7.0, "intellect": 8.0},
            }]},
            "ring": {"items": [{
                "item_id": 102, "name": "Native Intellect Ring",
                "stat_values": {"intellect": 12.0},
            }]},
        },
    }
    search_result = {
        "stages": [{"stage": "source_naked", "winner": record}],
        "sensitivity_history": [{
            "stage": "source_naked",
            "values": {
                "agility": 0.0,
                "intellect": 0.0,
                "strength": 0.2,
                "attack_power": 0.1,
            },
        }],
        "attempted": 41,
        "evaluated": 40,
        "status": "EVALUATED_BOUNDED",
        "source_context_sha256": "paladin-p3-fixture",
    }

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-native")
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **_kwargs: ir)
    monkeypatch.setattr(
        p3, "_source_profile_build_ir",
        lambda _root, source_ir, _class, _level, spec:
            (source_ir, {"profile": spec, "full_point_source_allocation": None}),
    )
    monkeypatch.setattr(
        player_context, "query_native_player_context",
        lambda *_args: native_context,
    )
    monkeypatch.setattr(
        player_context, "apply_native_player_context",
        lambda source_ir, _facts: source_ir,
    )
    monkeypatch.setattr(
        budgeted, "run_source_budgeted_gear",
        lambda **_kwargs: search_result,
    )
    monkeypatch.setattr(stateful, "_make_policy", lambda *_args, **_kwargs: policy)
    monkeypatch.setattr(smoke_module, "policy_uses_weapon_damage", lambda *_args: True)
    monkeypatch.setattr(
        smoke_module, "fast_p3_smoke_for_policy",
        lambda **_kwargs: item_check,
    )
    monkeypatch.setattr(budgeted, "paid_source_policy_stat_witness", witness)
    return p3.run_live(Path("."), "paladin", 20, spec="unrestricted")


def test_paladin_l20_p3_uses_native_item_deltas_and_paid_winner_first(monkeypatch):
    policy, record, prefix = _paladin_paid_winner_identity_fixture()
    calls = []

    def witness(_ir, **kwargs):
        calls.append(kwargs)
        paid = 2 if kwargs["stat"] == "agility" else 1
        return {
            "stat": kwargs["stat"],
            "status": "NO_POSITIVE_SOURCE_POLICY_WITNESS",
            "paid_evaluations": paid,
            "baseline_reused": True,
            "baseline_seconds_per_mob": 12.0,
            "perturbed_seconds_per_mob": 12.0,
            "opening_action_ids": list(kwargs["opening_action_ids"]),
        }

    report = _run_paladin_p3_live_with_stubs(monkeypatch, policy, record, witness)

    assert report["status"] == "FAIL"
    assert report["paid_search_winner_baseline_validation"] == {
        "accepted": True, "score": 12.0, "reason": None,
    }
    assert [call["stat"] for call in calls] == ["agility"]
    assert [call["max_evaluations"] for call in calls] == [3]
    assert calls[0]["probe_deltas"] == (17.0, 10.0)
    assert calls[0]["preferred_policy"] is policy
    assert calls[0]["baseline_record"] is record
    assert calls[0]["prefer_paid_search_winner"] is True
    assert calls[0]["allow_paid_winner_after_nonpositive"] is False
    assert calls[0]["opening_action_ids"] == prefix
    assert report["paladin_in_combat_mana_constraint"]["eligible"] is False
    assert report["paladin_in_combat_mana_constraint"]["reason"] == (
        "BASELINE_MANA_REMAINS_ABOVE_NEXT_POLICY_COST")
    assert report["real_source_search_evaluated"] == 42
    assert report["behavior_probes_executed"] == 42
    assert len(report["source_policy_stat_witnesses"]) == 1
    assert report["source_policy_stat_witnesses"][0]["probe_delta_sources"][0] == {
        "kind": "two_distinct_native_item_slots",
        "delta": 17.0,
        "items": [
            {"slot": "head", "item_id": 100, "name": "Native Agility Hood", "amount": 10.0},
            {"slot": "chest", "item_id": 101, "name": "Native Agility Chest", "amount": 7.0},
        ],
    }
    assert report["source_policy_stat_witnesses"][1]["probe_delta_sources"][0]["delta"] == 20.0


def test_paladin_l20_p3_attempts_intellect_only_when_mana_limited(monkeypatch):
    policy, record, _prefix = _paladin_paid_winner_identity_fixture()
    calls = []

    def witness(_ir, **kwargs):
        calls.append(kwargs)
        paid = 2 if kwargs["stat"] == "agility" else 1
        return {
            "stat": kwargs["stat"],
            "status": "NO_POSITIVE_SOURCE_POLICY_WITNESS",
            "paid_evaluations": paid,
            "baseline_reused": True,
            "baseline_seconds_per_mob": 12.0,
            "perturbed_seconds_per_mob": 12.0,
            "opening_action_ids": list(kwargs["opening_action_ids"]),
        }

    report = _run_paladin_p3_live_with_stubs(
        monkeypatch, policy, record, witness, initial_mana=200.0)

    assert report["paladin_in_combat_mana_constraint"]["eligible"] is True
    assert report["paladin_in_combat_mana_constraint"]["reason"] == (
        "BASELINE_MANA_LIMITED_BEFORE_TARGET_DEATH")
    assert report["paladin_in_combat_mana_constraint"]["estimated_mana_at_kill"] == 50.0
    assert [call["stat"] for call in calls] == ["agility", "intellect"]
    assert [call["max_evaluations"] for call in calls] == [3, 1]
    assert calls[1]["probe_deltas"] == (20.0, 12.0)
    assert calls[1]["prefer_paid_search_winner"] is True
    assert report["real_source_search_evaluated"] == 43
    assert report["behavior_probes_executed"] == 43


def test_paladin_l20_p3_rejects_mismatched_paid_winner_without_generic_probe(monkeypatch):
    from types import SimpleNamespace

    policy, record, _prefix = _paladin_paid_winner_identity_fixture()
    policy.provenance = {"authority": "forever_python", "search_performed": True}
    calls = []

    def forbidden_witness(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("rejected paid winner must not fall back to generic probes")

    report = _run_paladin_p3_live_with_stubs(
        monkeypatch, policy, record, forbidden_witness)

    assert calls == []
    assert report["paid_search_winner_baseline_validation"] == {
        "accepted": False, "score": None, "reason": "POLICY_AUTHORITY_MISMATCH",
    }
    assert report["source_policy_stat_witnesses"] == [{
        "stat": "agility",
        "status": "PAID_SEARCH_WINNER_BASELINE_REJECTED",
        "validation_reason": "POLICY_AUTHORITY_MISMATCH",
        "paid_evaluations": 0,
        "opening_action_ids": record["prefix"],
    }]
    assert report["real_source_search_evaluated"] == 40
